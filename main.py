import logging
import sys
import os
from dotenv import load_dotenv
import telebot
from telebot import types
from supabase import create_client, Client
from datetime import datetime as dt, timedelta
import pytz
import json
load_dotenv()

# ------------------------------------------------------------------------------
# 1) MINIMAL LOGGING: ONLY ERRORS + STARTUP MESSAGE (AND RESTART MESSAGE)
# ------------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # Only show ERROR and CRITICAL

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.ERROR)

file_handler = logging.FileHandler("bot_debug.log", encoding="utf-8")
file_handler.setLevel(logging.ERROR)

formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)

telebot.logger.setLevel(logging.ERROR)

# ------------------------------------------------------------------------------
# BOT CONFIG
# ------------------------------------------------------------------------------
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

TZ = pytz.timezone('Asia/Singapore')

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

ROLES = {
    "Admin": "Admin",
    "JCRC": "JCRC",
    "Captain": "Captain",
    "Chairman": "Chairman",
    "Block Head": "Block Head",
    "Resident": "Resident"
}

CCAS = [
    "No CCA", "Steppers", "Dance", "Badminton", "Volleyball",
    "Table Tennis", "Floorball", "Takraw", "Rockers", "Inspire",
    "A Blk", "B Blk", "C Blk", "D Blk", "E Blk",
    "Welfare D", "Sports D", "Culture D"
]

user_booking_flow = {}
admin_update_flow = {}

GROUP_CHAT_IDS = []  # Add your group chat IDs here

# IGNORE commands in group chats
@bot.message_handler(func=lambda m: m.chat.type in ["supergroup", "group"])
def ignore_group_messages(message):
    pass

# ------------------- Google Calendar Setup -------------------
import google.oauth2.service_account
from googleapiclient.discovery import build

# Define the scope and path to your JSON credentials file.
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = r'Facility_Booking_Bot\facility-booking-bot-3b36d365b812.json'
calendar_id = 'fde2719902f4ca8ada620b4922fa8365a333b2cf79885e048e107dd6d7834b9a@group.calendar.google.com'

# Create credentials and build the Google Calendar service.
credentials = google.oauth2.service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
calendar_service = build('calendar', 'v3', credentials=credentials)

# ------------------- Calendar Helper Functions -------------------
def add_event_to_calendar(booking, venue):
    # Convert booking_date from ISO format to datetime.
    start_dt = dt.fromisoformat(booking["booking_date"])
    duration_td = parse_duration(booking["duration"])
    end_dt = start_dt + duration_td

    # Retrieve user info based on booking["user_id"]
    user = get_user_info(booking["user_id"])
    user_name = user.get("name", "Unknown User") if user else "Unknown User"
    user_role = user.get("role", "No role") if user else "No role"
    user_cca = user.get("cca", "No CCA") if user else "No CCA"

    # Set the event summary as the short reason, and description as who booked it plus their role.
    event = {
        'summary': booking.get("reason", "No Reason Provided"),
        'description': f"Booked by: {user_name}, ({user_role} of {user_cca})",
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': 'Asia/Singapore',  # Adjust if needed.
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': 'Asia/Singapore',
        },
    }
    created_event = calendar_service.events().insert(calendarId=calendar_id, body=event).execute()
    print('Event created on Calendar: {}'.format(created_event.get('htmlLink')))
    return created_event.get("id")

def remove_event_from_calendar(event_id):
    """
    Remove the event from Google Calendar given its event ID.
    """
    try:
        calendar_service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        print(f"Event {event_id} removed from Google Calendar.")
    except Exception as e:
        print(f"Failed to remove event from calendar: {e}")

# ------------------------------------------------------------------------------
# HELPER FUNCTIONS
# ------------------------------------------------------------------------------
def parse_duration(duration_text):
    parts = duration_text.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    return timedelta(hours=hours, minutes=minutes)

def get_user_info(user_id):
    response = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if response.data and len(response.data) > 0:
        return response.data[0]
    return None

def ensure_registered(message):
    user = get_user_info(message.from_user.id)
    if user is None:
        bot.send_message(message.from_user.id, "Please /start first to register.")
        return None
    return user

def get_all_venues():
    response = supabase.table("venues").select("*").execute()
    return response.data if response.data else []

def get_all_users():
    response = supabase.table("users").select("*").execute()
    return response.data if response.data else []

def user_can_access_venue(user, venue):
    if user is None:
        bot.send_message(user["user_id"], "Please /start first to register.")
        return False

    user_role = user["role"].strip().lower()
    user_cca = user.get("cca", "").strip().lower()
    venue_name = venue["name"].strip().lower()
    
    # Special case for Band Room
    if venue_name == "band room":
        if user_role == "chairman" and user_cca in ["rockers", "inspire"]:
            return True
        return False

    # Residents can always book these
    if user_role == "resident" and venue_name in ["reading room", "dining hall"]:
        return True

    allowed_roles = venue.get("allowed_roles") or []
    allowed_ccas = venue.get("allowed_ccas") or []
    if isinstance(allowed_roles, str):
        allowed_roles = json.loads(allowed_roles)
    if isinstance(allowed_ccas, str):
        allowed_ccas = json.loads(allowed_ccas)
        
    if user_role in [r.lower() for r in allowed_roles]:
        return True
    if allowed_ccas and len(allowed_ccas) > 0:
        if user_cca and user_cca in [cca.lower() for cca in allowed_ccas]:
            return True
        return False
    return False

def create_booking(user_id, venue, booking_start, duration_text, user_role, reason):
    venue_name = venue["name"].strip().lower()
    if venue_name in ["reading room", "dining hall"]:
        status = "confirmed" if user_role.strip().lower() == "jcrc" else "pending approval"
    elif venue_name in ["mpsh", "band room"]:
        status = "confirmed"
    else:
        status = "pending approval"
    
    booking_start_str = booking_start.strftime("%Y-%m-%d %H:%M:%S")
    data = {
        "user_id": user_id,
        "venue_id": venue["venue_id"],
        "booking_date": booking_start_str,
        "duration": duration_text,
        "status": status,
        "reason": reason
    }
    supabase.table("bookings").insert(data).execute()

    # Fetch the newly inserted booking (using a combination of unique fields)
    result = supabase.table("bookings").select("*") \
        .eq("user_id", user_id) \
        .eq("venue_id", venue["venue_id"]) \
        .eq("booking_date", booking_start_str) \
        .eq("duration", duration_text) \
        .eq("reason", reason) \
        .execute()
    new_booking_data = result.data[0] if result.data else None

    # If the booking is auto-confirmed, add it to Google Calendar.
    if new_booking_data and status == "confirmed":
        event_id = add_event_to_calendar(new_booking_data, venue)
        supabase.table("bookings").update({"calendar_event_id": event_id}).eq("booking_id", new_booking_data["booking_id"]).execute()

    # If it's Reading Room or Dining Hall AND status is "pending approval",
    # let's fetch the inserted booking from DB and notify JCRC
    if venue_name in ["reading room", "dining hall"] and status == "pending approval":
        # 1) Re-fetch the newly created booking so we have full data (including booking_id)
        #    Typically, you'd do another query to get the booking row you just inserted
        #    For example, if your table has a serial "booking_id":
        #      we can fetch by user_id & booking_date & reason as a quick hack
        #      or use returning= after insertion if your DB supports it

        result = supabase.table("bookings").select("*") \
            .eq("user_id", user_id) \
            .eq("venue_id", venue["venue_id"]) \
            .eq("booking_date", booking_start_str) \
            .eq("status", "pending approval") \
            .eq("reason", reason) \
            .execute()

        new_booking_data = result.data[0] if result.data else None
        if new_booking_data:
            notify_jcrc_of_new_request(new_booking_data)

def check_conflict(venue, new_booking_start, duration_text, user_id):
    """
    Check for overlapping confirmed bookings.
    If there is a conflict, remove the user from booking flow and return True.
    Otherwise, return False.
    """
    new_duration = parse_duration(duration_text)
    new_booking_end = new_booking_start + new_duration

    response = supabase.table("bookings").select("*") \
        .eq("venue_id", venue["venue_id"]) \
        .eq("status", "confirmed") \
        .execute()
    bookings = response.data if response.data else []

    for b in bookings:
        confirmed_start = dt.fromisoformat(b["booking_date"])
        try:
            confirmed_duration = parse_duration(b["duration"])
        except Exception:
            confirmed_duration = timedelta(0)
        confirmed_end = confirmed_start + confirmed_duration

        # Overlap check: if new start < existing end AND new end > existing start
        if new_booking_start < confirmed_end and new_booking_end > confirmed_start:
            # CONFLICT FOUND: Remove this user from booking flow and return True
            user_booking_flow.pop(user_id, None)
            return True

    # No conflicts
    return False


def check_start_conflict(venue, proposed_start):
    """
    Checks if 'proposed_start' falls within the interval of any
    confirmed booking for the specified venue. If yes, returns True.
    Otherwise, returns False.
    """
    # Query all confirmed bookings for this venue
    response = supabase.table("bookings").select("*") \
        .eq("venue_id", venue["venue_id"]) \
        .eq("status", "confirmed") \
        .execute()
    bookings = response.data if response.data else []

    # Check if proposed_start is in any [confirmed_start, confirmed_end) interval
    for b in bookings:
        confirmed_start = dt.fromisoformat(b["booking_date"])
        try:
            confirmed_duration = parse_duration(b["duration"])
        except Exception:
            confirmed_duration = timedelta(0)
        confirmed_end = confirmed_start + confirmed_duration

        # If proposed_start is >= confirmed_start and < confirmed_end, we have a conflict
        if confirmed_start <= proposed_start < confirmed_end:
            return True

    # If no interval contains proposed_start, there's no conflict
    return False

def get_venue_ids_for(names):
    venues = get_all_venues()
    return [v["venue_id"] for v in venues if v["name"].strip().lower() in [n.lower() for n in names]]

def cancel_booking(booking_id, user_id, is_admin=False):
    query = supabase.table("bookings").select("*").eq("booking_id", booking_id)
    if not is_admin:
        query = query.eq("user_id", user_id)
    result = query.execute()
    if not result.data:
        return False
    booking = result.data[0]
    supabase.table("bookings").update({"status": "cancelled"}).eq("booking_id", booking_id).execute()
    if booking.get("calendar_event_id"):
        remove_event_from_calendar(booking["calendar_event_id"])
    return True

def get_user_bookings(user_id, is_admin=False):
    query = supabase.table("bookings").select("*").neq("status", "cancelled")
    if not is_admin:
        query = query.eq("user_id", user_id)
    result = query.execute()
    return result.data if result.data else []

def notify_approval(booking):
    """
    Notifies the user and all group chats that a booking has been approved,
    displaying the booking data in the same multi-line format used by cancel_command/view_command.
    """
    booking_id = booking["booking_id"]
    user_id = booking["user_id"]
    
    # 1) Fetch user info
    user_info = get_user_info(user_id)
    user_name = user_info.get("name", "Unknown User") if user_info else "Unknown User"
    
    # 2) Fetch the venue record
    venue_data = supabase.table("venues").select("*").eq("venue_id", booking["venue_id"]).execute()
    venue = venue_data.data[0] if venue_data.data else {}
    venue_name = venue.get("name", "Unknown Venue")
    
    # 3) Parse booking start time and duration for multi-line format
    booking_start = dt.fromisoformat(booking["booking_date"])
    dur = parse_duration(booking["duration"])
    end_dt = booking_start + dur
    
    start_str = booking_start.strftime("%Y-%m-%d %H:%M")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M")
    
    # 4) Build a multi-line string, similar to cancel_command or view_command
    detail_message = (
        f"Booking ID: {booking_id}\n"
        f"Venue: {venue_name}\n"
        f"Name: {user_name}\n"
        f"Start: {start_str}\n"
        f"End: {end_str}\n"
        f"Status: {booking['status']}\n"
        f"Reason: {booking.get('reason','')}\n"
        "----------------------"
    )
    
    # 5) Notify the user in a private message
    try:
        bot.send_message(user_id, f"Your booking has been approved!\n\n{detail_message}")
    except Exception as e:
        # Handle edge cases if the user blocks the bot or any other error
        print(f"Failed to message user {user_id}: {e}")
    
    # 6) Broadcast to each group chat
    broadcast_text = f"Booking Approved!\n\n{detail_message}"
    
    for chat_id in GROUP_CHAT_IDS:
        try:
            bot.send_message(chat_id, broadcast_text)
        except Exception as e:
            # If the bot can't send to a particular group, you can log or ignore
            print(f"Failed to notify group {chat_id}: {e}")

def notify_jcrc_of_new_request(booking):
    """
    Notifies all JCRC members that a new booking request
    (pending approval) has been created for Reading Room or Dining Hall.
    """

    # 1) Fetch JCRC users
    jcrc_result = supabase.table("users").select("*").eq("role", "jcrc").execute()
    jcrc_users = jcrc_result.data if jcrc_result.data else []
    if not jcrc_users:
        # If there are no JCRC users, do nothing or log a warning
        return

    # 2) Gather booking details (similar format to view_command/cancel_command)
    booking_id = booking["booking_id"]
    user_id = booking["user_id"]
    user_info = get_user_info(user_id)  # to display requestor's name
    user_name = user_info.get("name", "Unknown User") if user_info else "Unknown User"

    # 2a) Venue info
    venue_data = supabase.table("venues").select("*").eq("venue_id", booking["venue_id"]).execute()
    venue = venue_data.data[0] if venue_data.data else {}
    venue_name = venue.get("name", "Unknown Venue")

    # 2b) Times & Duration
    booking_start = dt.fromisoformat(booking["booking_date"])
    dur = parse_duration(booking["duration"])
    end_dt = booking_start + dur
    
    start_str = booking_start.strftime("%Y-%m-%d %H:%M")
    end_str   = end_dt.strftime("%Y-%m-%d %H:%M")

    # 3) Build the message
    detail_msg = (
        f"New booking request (Pending Approval)!\n"
        f"Booking ID: {booking_id}\n"
        f"Venue: {venue_name}\n"
        f"Name: {user_name}\n"
        f"Start: {start_str}\n"
        f"End: {end_str}\n"
        f"Status: {booking['status']}\n"
        f"Reason: {booking.get('reason', '')}\n"
        "----------------------"
    )

    # 4) Send this detail to each JCRC user
    for jcrc_user in jcrc_users:
        jcrc_user_id = jcrc_user["user_id"]
        try:
            bot.send_message(jcrc_user_id, detail_msg)
        except Exception as e:
            # In case the user blocked the bot or another send error
            print(f"Failed to notify JCRC user {jcrc_user_id}: {e}")

# ------------------------------------------------------------------------------
# BOT COMMAND HANDLERS
# ------------------------------------------------------------------------------
@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        "Available Commands:\n"
        "/start - Register or login\n"
        "/getid - Get your Telegram User ID\n"
        "/book - Start a venue booking\n"
        "/cancel - Cancel an existing booking\n"
        "/view - View your active bookings\n"
        "/restart - Restart the bot (admin-only)\n"
        "\nFor further assistance, contact: @winstonzhao or @Jaredee"
    )
    bot.send_message(message.chat.id, help_text)

@bot.message_handler(commands=['start'])
def start(message):
    user = get_user_info(message.from_user.id)
    if user is None:
        bot.send_message(
            message.from_user.id,
            "Welcome! It looks like you're new here. Please tell us your name:"
        )
        bot.register_next_step_handler(message, register_new_user)
    else:
        bot.send_message(
            message.from_user.id,
            f"Welcome back {user.get('name', '')}! "
            f"You are registered as: {user['role']}"
        )
        send_main_menu(message.from_user.id)

def register_new_user(message):
    user_id = message.from_user.id
    name = message.text.strip()
    new_user = {
        "user_id": user_id,
        "name": name,
        "role": "Resident",
        "cca": "No CCA"
    }
    supabase.table("users").insert(new_user).execute()
    bot.send_message(user_id, f"Thanks {name}! You are now registered as a Resident.")
    send_main_menu(user_id)

def send_main_menu(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        types.KeyboardButton("/book"),
        types.KeyboardButton("/cancel"),
        types.KeyboardButton("/view"),
        types.KeyboardButton("/getid")
    ]
    user = get_user_info(chat_id)
    if user and user["role"].strip().lower() == "admin":
        buttons.append(types.KeyboardButton("/admin_update"))
        buttons.append(types.KeyboardButton("/restart"))
    if user and user["role"].strip().lower() == "jcrc":
        buttons.append(types.KeyboardButton("/approve"))
    markup.add(*buttons)
    bot.send_message(chat_id, "Choose an option:", reply_markup=markup)

@bot.message_handler(commands=['getid'])
def getid_command(message):
    user_id = message.from_user.id
    bot.send_message(user_id, f"Your User ID is: {user_id}. Press /start to restart the process.")

@bot.message_handler(commands=['approve'])
def approve_command(message):
    user = ensure_registered(message)
    if not user:
        return
    if user["role"].strip().lower() != "jcrc":
        bot.send_message(user["user_id"], "You do not have permission to approve bookings. Press /start to restart the process.")
        return
    
    # Get only pending bookings for Reading Room / Dining Hall
    venue_ids = get_venue_ids_for(["Reading Room", "Dining Hall"])
    response = supabase.table("bookings").select("*") \
        .eq("status", "pending approval") \
        .in_("venue_id", venue_ids) \
        .execute()
    pending = response.data if response.data else []
    
    if not pending:
        bot.send_message(user["user_id"], "No pending bookings for approval. Press /start to restart the process.")
        return
    
    # Fetch all venues and users so we can map IDs to names
    venues = get_all_venues()
    users = get_all_users()  # Make sure you have a get_all_users() function
    venue_dict = {str(v["venue_id"]): v["name"] for v in venues}
    users_dict = {str(u["user_id"]): u["name"] for u in users}

    # Build the message in the same format as view_command
    msg = "Pending bookings for approval:\n"
    for b in pending:
        booking_start = dt.fromisoformat(b["booking_date"])
        dur = parse_duration(b["duration"])
        end_dt = booking_start + dur
        
        # Format start & end times
        start_str = booking_start.strftime("%Y-%m-%d %H:%M")
        end_str = end_dt.strftime("%Y-%m-%d %H:%M")
        
        # Look up venue name & user name
        venue_name = venue_dict.get(str(b["venue_id"]), "Unknown Venue")
        user_name = users_dict.get(str(b["user_id"]), "Unknown User")
        
        # Format one entry
        line = (
            f"Booking ID: {b['booking_id']}\n"
            f"Venue: {venue_name}\n"
            f"Name: {user_name}\n"
            f"Start: {start_str}\n"
            f"End: {end_str}\n"
            f"Status: {b['status']}\n"
            f"Reason: {b.get('reason', '')}\n"
            "----------------------"
        )
        msg += line + "\n"
    
    # Prompt for the Booking ID to approve
    msg += "\nPlease enter the Booking ID to approve:"
    bot.send_message(user["user_id"], msg)
    bot.register_next_step_handler(message, process_approval)

def process_approval(message):
    user = ensure_registered(message)
    if not user:
        return
    try:
        booking_id = int(message.text.strip())
        res = supabase.table("bookings").select("*").eq("booking_id", booking_id).execute()
        if not res.data:
            bot.send_message(message.from_user.id, "Invalid Booking ID: booking not found. Press /start to restart the process.")
            return
        booking = res.data[0]
        if booking["status"] != "pending approval":
            bot.send_message(message.from_user.id, "Invalid Booking ID: booking is not pending approval. Press /start to restart the process.")
            return
        
        # 1) Update status to confirmed
        supabase.table("bookings").update({"status": "confirmed"}).eq("booking_id", booking_id).execute()

        # Re-fetch the updated booking so we can update Google Calendar.
        updated_res = supabase.table("bookings").select("*").eq("booking_id", booking_id).execute()
        updated_booking = updated_res.data[0] if updated_res.data else None

        if updated_booking:
            # If the booking does not already have a calendar event, add it.
            if not updated_booking.get("calendar_event_id"):
                venue_data = supabase.table("venues").select("*").eq("venue_id", updated_booking["venue_id"]).execute()
                venue = venue_data.data[0] if venue_data.data else {}
                event_id = add_event_to_calendar(updated_booking, venue)
                supabase.table("bookings").update({"calendar_event_id": event_id}).eq("booking_id", booking_id).execute()
            notify_approval(updated_booking)

        bot.send_message(message.from_user.id, f"Booking {booking_id} approved. Press /start to restart the process.")

    except ValueError:
        bot.send_message(message.from_user.id, "Invalid Booking ID. Press /start to restart the process.")


@bot.message_handler(commands=['admin_update'])
def admin_update_command(message):
    user = ensure_registered(message)
    if not user:
        return
    # Must be admin to proceed
    if user["role"].strip().lower() != "admin":
        bot.send_message(message.from_user.id, "You do not have permission to update other users. Press /start to restart the process.")
        return
    
    bot.send_message(message.from_user.id, "Please enter the User ID of the user you want to update:")
    bot.register_next_step_handler(message, admin_update_user_id)

def admin_update_user_id(message):
    # 1) Check if input is numeric
    try:
        target_user_id = int(message.text.strip())
    except ValueError:
        bot.send_message(
            message.from_user.id,
            "Invalid input. Please enter a numeric User ID. Exiting admin update. Press /start to restart the process."
        )
        # Remove from flow and return
        admin_update_flow.pop(message.from_user.id, None)
        return
    
    # 2) Check if that user actually exists in your "users" table
    target_user_info = get_user_info(target_user_id)
    if not target_user_info:
        bot.send_message(
            message.from_user.id,
            "No user found with that ID. Exiting admin update."
        )
        # Remove from flow and return
        admin_update_flow.pop(message.from_user.id, None)
        return

    # 3) If ID is valid and user exists, continue the flow
    admin_update_flow[message.from_user.id] = {"target_user_id": target_user_id}
    
    markup = types.InlineKeyboardMarkup()
    for role in ROLES.keys():
        btn = types.InlineKeyboardButton(ROLES[role], callback_data=f"setrole_{target_user_id}_{ROLES[role]}")
        markup.add(btn)
    
    bot.send_message(
        message.from_user.id,
        f"User found: {target_user_info['name']}. Select the new role:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("setrole_"))
def callback_set_role(call):
    parts = call.data.split("_")
    target_user_id = parts[1]
    selected_role = parts[2]
    admin_id = call.from_user.id
    if admin_id in admin_update_flow:
        admin_update_flow[admin_id]["new_role"] = selected_role
    markup = types.InlineKeyboardMarkup()
    for cca in CCAS:
        btn = types.InlineKeyboardButton(cca, callback_data=f"setcca_{target_user_id}_{cca}")
        markup.add(btn)
    bot.edit_message_text("Select the new CCA (or 'No CCA'):",
                          call.message.chat.id, call.message.message_id,
                          reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("setcca_"))
def callback_set_cca(call):
    parts = call.data.split("_")
    target_user_id = parts[1]
    selected_cca = parts[2]
    admin_id = call.from_user.id
    new_role = admin_update_flow.get(admin_id, {}).get("new_role", "resident")
    new_cca = None if selected_cca == "No CCA" else selected_cca
    supabase.table("users").upsert({
        "user_id": int(target_user_id),
        "role": new_role,
        "cca": new_cca
    }).execute()
    bot.edit_message_text(
        f"User {target_user_id} updated: Role = {ROLES[new_role]}, "
        f"CCA = {new_cca if new_cca else 'None'}.",
        call.message.chat.id,
        call.message.message_id
    )
    try:
        bot.send_message(
            target_user_id,
            f"You has been updated as: {ROLES[new_role]} of {new_cca if new_cca else 'None'}."
        )
    except Exception as e:
        print(f"Error sending update notification to user {target_user_id}: {e}")
    admin_update_flow.pop(admin_id, None)

@bot.message_handler(commands=['book'])
def book_command(message):
    try:
        # Attempt to ensure user is registered
        user = ensure_registered(message)
        
        # If not registered, ensure_registered() has already sent
        # "Please /start first to register." So just exit cleanly.
        if not user:
            return
        
        # Otherwise, continue with booking flow
        venues = get_all_venues()
        accessible_venues = [v for v in venues if user_can_access_venue(user, v)]
        if not accessible_venues:
            bot.send_message(user["user_id"], "No venues available for booking. Press /start to restart the process.")
            return
        
        user_booking_flow[user["user_id"]] = {
            "user": user,
            "step": 1,
            "accessible_venues": accessible_venues
        }
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
        for v in accessible_venues:
            markup.add(types.KeyboardButton(v["name"]))
        
        bot.send_message(
            user["user_id"],
            "Select a venue to book:",
            reply_markup=markup
        )
        bot.register_next_step_handler(message, handle_venue_selection)
    
    except Exception as e:
        # Catch any unexpected errors and notify the user
        print(f"ERROR in book_command: {e}")
        bot.send_message(
            message.chat.id,
            "An error occurred. Please try /start first to register if you're not registered."
        )

def handle_venue_selection(message):
    user_id = message.from_user.id
    if user_id not in user_booking_flow:
        bot.send_message(user_id, "Booking flow expired. Please try /book again.")
        return
    flow_data = user_booking_flow[user_id]
    venue_name = message.text.strip().lower()
    chosen_venue = next(
        (v for v in flow_data["accessible_venues"] if v["name"].strip().lower() == venue_name),
        None
    )
    if not chosen_venue:
        bot.send_message(user_id, "Invalid venue selection. Please try /book again.")
        user_booking_flow.pop(user_id, None)
        return
    flow_data["venue"] = chosen_venue
    flow_data["step"] = 2

    # Display confirmed bookings for next 7 days
    start_of_week = dt.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_week = start_of_week + timedelta(days=7)
    response = supabase.table("bookings").select("*")\
        .eq("venue_id", chosen_venue["venue_id"])\
        .eq("status", "confirmed")\
        .gte("booking_date", start_of_week.strftime("%Y-%m-%d 00:00:00"))\
        .lte("booking_date", end_of_week.strftime("%Y-%m-%d 23:59:59"))\
        .execute()
    bookings = response.data if response.data else []
    if bookings:
        msg = "Slots booked for this venue for the next 7 days:\n"
        for b in bookings:
            b_start = dt.fromisoformat(b['booking_date'])
            b_date = b_start.strftime("%Y-%m-%d")
            dur = parse_duration(b["duration"])
            b_end = (b_start + dur).strftime("%H:%M")
            b_start_str = b_start.strftime("%H:%M")
            msg += f"Date: {b_date}, {b_start_str} - {b_end}\n"
        bot.send_message(user_id, msg)
    else:
        bot.send_message(user_id, f"No confirmed bookings for {chosen_venue['name']} in the next 7 days. Press /start to restart the process.")
    
    send_date_selection(user_id)

def send_date_selection(user_id):
    markup = types.InlineKeyboardMarkup()
    today = dt.now(TZ).date()
    for i in range(0, 8):
        booking_date = today + timedelta(days=i)
        btn = types.InlineKeyboardButton(
            booking_date.strftime("%Y-%m-%d"),
            callback_data=f"bookdate_{booking_date.strftime('%Y-%m-%d')}"
        )
        markup.add(btn)
    bot.send_message(user_id, "Select a booking date:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("bookdate_"))
def callback_booking_date(call):
    user_id = call.from_user.id
    date_str = call.data.split("_")[1]
    if user_id not in user_booking_flow:
        bot.answer_callback_query(call.id, "Booking flow expired. Press /start to restart the process.")
        return
    flow_data = user_booking_flow[user_id]
    try:
        booking_date = dt.strptime(date_str, "%Y-%m-%d")
        flow_data["booking_date"] = booking_date
        flow_data["step"] = 3
        bot.edit_message_text(f"Date selected: {date_str}",
                              call.message.chat.id, call.message.message_id)
        msg = bot.send_message(user_id, "Enter start time (HH:MM in 24-hr format):")
        bot.register_next_step_handler(msg, handle_start_time)
    except Exception:
        bot.answer_callback_query(call.id, "Invalid date selected. Press /start to restart the process.")

def handle_start_time(message):
    user_id = message.from_user.id
    if user_id not in user_booking_flow:
        bot.send_message(user_id, "Booking flow expired. Please try /book again.")
        return
    flow_data = user_booking_flow[user_id]
    time_str = message.text.strip()
    try:
        proposed_start = dt.strptime(time_str, "%H:%M").time()
        if proposed_start.minute % 15 != 0:
            bot.send_message(user_id, "Start time must be in 15-minute increments (e.g., 18:00, 18:15, 18:30, 18:45).")
            bot.register_next_step_handler(message, handle_start_time)
            return
        # Combine with the selected booking date
        proposed_dt = dt.combine(flow_data["booking_date"].date(), proposed_start)
        if check_start_conflict(flow_data["venue"], proposed_dt):
            bot.send_message(
                user_id,
                "The specified start time conflicts with an existing confirmed booking. "
                "Exiting booking process. Press /start to restart the process."
            )
            user_booking_flow.pop(user_id, None)
            return
        # Save proposed start time temporarily
        flow_data["proposed_start"] = proposed_start
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Confirm", callback_data="confirm_start"),
            types.InlineKeyboardButton("Re-enter", callback_data="reenter_start"),
            types.InlineKeyboardButton("Exit", callback_data="exit_start")
        )
        bot.send_message(
            user_id,
            f"You entered {proposed_start.strftime('%H:%M')}. Confirm?",
            reply_markup=markup
        )
    except ValueError:
        bot.send_message(user_id, "Invalid start time format. Please try again (HH:MM).")
        bot.register_next_step_handler(message, handle_start_time)

@bot.callback_query_handler(func=lambda call: call.data in ["confirm_start", "reenter_start", "exit_start"])
def handle_start_time_confirm(call):
    user_id = call.from_user.id
    if user_id not in user_booking_flow:
        bot.answer_callback_query(call.id, "Booking flow expired.")
        return
    flow_data = user_booking_flow[user_id]
    if call.data == "confirm_start":
        flow_data["start_time"] = flow_data["proposed_start"]
        flow_data["step"] = 4
        bot.edit_message_text(
            f"Start time confirmed as {flow_data['start_time'].strftime('%H:%M')}.",
            call.message.chat.id,
            call.message.message_id
        )
        msg = bot.send_message(user_id, "Enter duration (H:MM) (e.g., 1:30 for 1 hour 30 minutes):")
        bot.register_next_step_handler(msg, handle_duration)
    elif call.data == "reenter_start":
        bot.edit_message_text(
            "Please re-enter start time (HH:MM in 24-hr format):",
            call.message.chat.id,
            call.message.message_id
        )
        msg = bot.send_message(user_id, "Input your new timing")
        bot.register_next_step_handler(msg, handle_start_time)
    else:  # exit_start
        bot.edit_message_text(
            "Booking process cancelled. Press /start to restart the process",
            call.message.chat.id,
            call.message.message_id
        )
        user_booking_flow.pop(user_id, None)

def handle_duration(message):
    user_id = message.from_user.id
    if user_id not in user_booking_flow:
        bot.send_message(user_id, "Booking flow expired. Please try /book again.")
        return
    flow_data = user_booking_flow[user_id]
    duration_str = message.text.strip()
    try:
        parts = duration_str.split(":")
        if len(parts) != 2:
            raise ValueError("Invalid format")
        hours = int(parts[0])
        minutes = int(parts[1])
        total_minutes = hours * 60 + minutes
        if total_minutes <= 0 or total_minutes % 15 != 0:
            raise ValueError("Duration must be positive and in 15-minute increments")
        if total_minutes > 1440:
            raise ValueError("Duration cannot exceed 24 hours")
        # Save the proposed duration for later confirmation.
        flow_data["proposed_duration"] = duration_str
        start_dt = dt.combine(flow_data["booking_date"].date(), flow_data["start_time"])
        end_dt = start_dt + timedelta(hours=hours, minutes=minutes)
        if check_conflict(flow_data["venue"], start_dt, duration_str, user_id):
            bot.send_message(
                user_id,
                "This time slot overlaps with an existing approved booking. "
                "Exiting booking process. Press /start to restart the process."
            )
            user_booking_flow.pop(user_id, None)
            return
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Confirm", callback_data="confirm_duration"),
            types.InlineKeyboardButton("Re-enter", callback_data="reenter_duration"),
            types.InlineKeyboardButton("Exit", callback_data="exit_duration")
        )
        bot.send_message(
            user_id,
            f"You entered duration {duration_str} (ending at {end_dt.strftime('%H:%M')}). Confirm?",
            reply_markup=markup
        )
    except ValueError as ve:
        bot.send_message(
            user_id,
            f"Invalid duration format: {ve}. Please enter duration as H:MM (in 15-minute increments, e.g., 1:30), and not more than 24 hours."
        )
        bot.register_next_step_handler(message, handle_duration)

@bot.callback_query_handler(func=lambda call: call.data in ["confirm_duration", "reenter_duration", "exit_duration"])
def handle_duration_confirm(call):
    user_id = call.from_user.id
    if user_id not in user_booking_flow:
        bot.answer_callback_query(call.id, "Booking flow expired.")
        return
    flow_data = user_booking_flow[user_id]
    if call.data == "confirm_duration":
        flow_data["duration"] = flow_data["proposed_duration"]
        bot.edit_message_text(
            f"Duration confirmed as {flow_data['duration']}.",
            call.message.chat.id,
            call.message.message_id
        )
        bot.send_message(user_id, "Enter a short reason for booking the venue:")
        bot.register_next_step_handler(call.message, handle_reason)
    elif call.data == "reenter_duration":
        bot.edit_message_text(
            "Please re-enter duration (H:MM in 24-hr format):",
            call.message.chat.id,
            call.message.message_id
        )
        msg = bot.send_message(user_id, "Input your duration again")
        bot.register_next_step_handler(msg, handle_duration)
    else:  # exit_duration
        bot.edit_message_text(
            "Booking process cancelled. Please try /book again.",
            call.message.chat.id,
            call.message.message_id
        )
        user_booking_flow.pop(user_id, None)

def handle_reason(message):
    user_id = message.from_user.id
    if user_id not in user_booking_flow:
        bot.send_message(user_id, "Booking flow expired. Please try /book again.")
        return
    flow_data = user_booking_flow[user_id]
    reason = message.text.strip()
    flow_data["reason"] = reason
    venue = flow_data["venue"]
    booking_start = dt.combine(flow_data["booking_date"].date(), flow_data["start_time"])
    create_booking(
        user_id=user_id,
        venue=venue,
        booking_start=booking_start,
        duration_text=flow_data["duration"],
        user_role=flow_data["user"]["role"],
        reason=reason
    )
    display_date = booking_start.strftime("%Y-%m-%d")
    display_start = flow_data["start_time"].strftime("%H:%M")
    display_end = (booking_start + parse_duration(flow_data["duration"])).strftime("%H:%M")
    msg = (
        f"Booking for {venue['name']} on {display_date} "
        f"from {display_start} to {display_end} has been placed.\n"
    )
    if (
        flow_data["user"]["role"].strip().lower() != "jcrc"
        and venue["name"].strip().lower() in ["reading room", "dining hall"]
    ):
        msg += "It is pending approval by JCRC."
    else:
        msg += "It is confirmed."
    msg += "\nPress /start to restart the process."
    bot.send_message(user_id, msg)
    user_booking_flow.pop(user_id, None)

@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    user = ensure_registered(message)
    if not user:
        return
    
    # Admins see all non-cancelled bookings; others only see their own
    is_admin = (user["role"].strip().lower() == "admin")
    bookings = get_user_bookings(user["user_id"], is_admin=is_admin)
    
    if not bookings:
        bot.send_message(user["user_id"], "You have no active bookings to cancel. Press /start to restart the process.")
        return
    
    # Fetch extra data to display names properly
    venues = get_all_venues()
    users = get_all_users()  # Make sure you have this function
    venue_dict = {str(v["venue_id"]): v["name"] for v in venues}
    users_dict = {str(u["user_id"]): u["name"] for u in users}
    
    # Build output lines in the same format as view_command
    response_lines = []
    for b in bookings:
        booking_start = dt.fromisoformat(b["booking_date"])
        dur = parse_duration(b["duration"])
        end_dt = booking_start + dur
        
        start_str = booking_start.strftime("%Y-%m-%d %H:%M")
        end_str   = end_dt.strftime("%Y-%m-%d %H:%M")
        
        venue_name = venue_dict.get(str(b["venue_id"]), "Unknown Venue")
        user_name  = users_dict.get(str(b["user_id"]), "Unknown User")
        
        line = (
            f"Booking ID: {b['booking_id']}\n"
            f"Venue: {venue_name}\n"
            f"Name: {user_name}\n"
            f"Start: {start_str}\n"
            f"End: {end_str}\n"
            f"Status: {b['status']}\n"
            f"Reason: {b.get('reason','')}\n"
            "----------------------"
        )
        response_lines.append(line)
    
    # Prompt for the Booking ID to cancel
    final_msg = "\n".join(response_lines)
    final_msg += "\nPlease enter the Booking ID to cancel:"
    
    bot.send_message(user["user_id"], final_msg)
    bot.register_next_step_handler(message, process_cancel)


def process_cancel(message):
    try:
        booking_id = int(message.text.strip())
        user_id = message.from_user.id
        user = get_user_info(user_id)
        is_admin = (user and user["role"].strip().lower() == "admin")
        if cancel_booking(booking_id, user_id, is_admin=is_admin):
            bot.send_message(
                message.from_user.id,
                f"Booking {booking_id} cancelled successfully. Press /start to restart the process."
            )
        else:
            bot.send_message(
                message.from_user.id,
                "Unable to cancel booking. Please check the Booking ID. Press /start to restart the process."
            )
    except ValueError:
        bot.send_message(message.from_user.id, "Invalid Booking ID. Press /start to restart the process.")

@bot.message_handler(commands=['view'])
def view_command(message):
    user = ensure_registered(message)
    if not user:
        return
    
    # If user is JCRC, show ALL confirmed bookings for Dining Hall, Reading Room, and MPSH.
    if user["role"].strip().lower() == "jcrc":
        # 1) Get all relevant venue IDs
        venue_ids = get_venue_ids_for(["Dining Hall", "Reading Room", "MPSH"])
        
        # 2) Fetch confirmed bookings for those venues
        data = supabase.table("bookings").select("*") \
            .in_("venue_id", venue_ids) \
            .eq("status", "confirmed") \
            .execute()
        bookings = data.data if data.data else []
    else:
        # Non-JCRC behavior remains the same
        is_admin = (user["role"].strip().lower() == "admin")
        bookings = get_user_bookings(user["user_id"], is_admin=is_admin)
    
    # If no bookings found, inform the user
    if not bookings:
        bot.send_message(user["user_id"], "No active bookings found.")
        return
    
    # Get venue & user info for name lookups
    venues = get_all_venues()
    users = get_all_users()  # Ensure you have a get_all_users() function
    venue_dict = {str(v["venue_id"]): v["name"] for v in venues}
    users_dict = {str(u["user_id"]): u["name"] for u in users}
    
    # Build output lines
    response_lines = []
    for b in bookings:
        booking_start = dt.fromisoformat(b["booking_date"])
        dur = parse_duration(b["duration"])
        end_dt = booking_start + dur

        start_time = booking_start.strftime("%Y-%m-%d %H:%M")
        end_time = end_dt.strftime("%Y-%m-%d %H:%M")

        venue_name = venue_dict.get(str(b["venue_id"]), "Unknown Venue")
        user_name = users_dict.get(str(b["user_id"]), "Unknown User")
        
        line = (
            f"Booking ID: {b['booking_id']}\n"
            f"Venue: {venue_name}\n"
            f"Name: {user_name}\n"
            f"Start: {start_time}\n"
            f"End: {end_time}\n"
            f"Status: {b['status']}\n"
            f"Reason: {b.get('reason','')}\n"
            "----------------------"
        )
        response_lines.append(line)
    
    # Send the final message
    bot.send_message(user["user_id"], "\n".join(response_lines))

# ------------------------------------------------------------------------------
# NEW MASTER COMMAND: /restart
# ------------------------------------------------------------------------------
@bot.message_handler(commands=['restart'])
def restart_command(message):
    user = ensure_registered(message)
    if not user:
        return
    # Only allow admin role to restart
    if user["role"].strip().lower() == "admin":
        bot.send_message(message.chat.id, "Restarting the bot...")
        # Log a CRITICAL message so it shows in minimal logs
        logger.critical("Bot is restarting upon admin request...")
        # This will re-run the current Python script
        os.execv(sys.executable, [sys.executable] + sys.argv)
    else:
        bot.send_message(message.chat.id, "You do not have permission to restart the bot.")

# ------------------------------------------------------------------------------
# START BOT: ONLY LOG START OF POLLING & ERRORS
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    logger.critical("Bot is starting polling...")  # Startup message
    try:
        bot.polling(none_stop=True)
    except Exception:
        logger.exception("Unhandled exception in bot polling:")
        raise