from datetime import datetime as dt, timedelta
from telebot import types
from config import bot, user_booking_flow, TZ, supabase
from db_helpers import parse_duration, get_all_venues, user_can_access_venue, get_user_info
from booking_utils import check_start_conflict, check_conflict, create_booking

@bot.message_handler(commands=['book'])
def book_command(message):
    try:
        user = get_user_info(message.from_user.id)
        if not user:
            bot.send_message(message.from_user.id, "Please /start first to register.")
            return
        venues = get_all_venues()
        accessible_venues = [v for v in venues if user_can_access_venue(user, v)]
        if not accessible_venues:
            bot.send_message(user["user_id"], "No venues available for booking. Press /start to restart.")
            return
        user_booking_flow[user["user_id"]] = {
            "user": user,
            "step": 1,
            "accessible_venues": accessible_venues
        }
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
        for v in accessible_venues:
            markup.add(types.KeyboardButton(v["name"]))
        bot.send_message(user["user_id"], "Select a venue to book:", reply_markup=markup)
        bot.register_next_step_handler(message, handle_venue_selection)
    except Exception as e:
        print(f"ERROR in book_command: {e}")
        bot.send_message(message.chat.id, "An error occurred. Please try /start first to register if not registered.")

def handle_venue_selection(message):
    user_id = message.from_user.id
    if user_id not in user_booking_flow:
        bot.send_message(user_id, "Booking flow expired. Please try /start again.")
        return
    flow_data = user_booking_flow[user_id]
    venue_name = message.text.strip().lower()
    chosen_venue = next((v for v in flow_data["accessible_venues"] if v["name"].strip().lower() == venue_name), None)
    if not chosen_venue:
        bot.send_message(user_id, "Invalid venue selection. Please try /start again.")
        user_booking_flow.pop(user_id, None)
        return
    flow_data["venue"] = chosen_venue
    flow_data["step"] = 2

    # Display confirmed bookings for the next 7 days
    start_of_week = dt.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_week = start_of_week + timedelta(days=7)
    response = supabase.table("bookings").select("*") \
        .eq("venue_id", chosen_venue["venue_id"]) \
        .eq("status", "confirmed") \
        .gte("booking_date", start_of_week.strftime("%Y-%m-%d 00:00:00")) \
        .lte("booking_date", end_of_week.strftime("%Y-%m-%d 23:59:59")) \
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
        bot.send_message(user_id, f"No confirmed bookings for {chosen_venue['name']} in the next 7 days. Press /start to restart.")
    
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
        bot.answer_callback_query(call.id, "Booking flow expired. Press /start to restart.")
        return
    flow_data = user_booking_flow[user_id]
    try:
        booking_date = dt.strptime(date_str, "%Y-%m-%d")
        flow_data["booking_date"] = booking_date
        flow_data["step"] = 3
        bot.edit_message_text(f"Date selected: {date_str}", call.message.chat.id, call.message.message_id)
        msg = bot.send_message(user_id, "Enter start time (HH:MM in 24-hr format):")
        bot.register_next_step_handler(msg, handle_start_time)
    except Exception:
        bot.answer_callback_query(call.id, "Invalid date selected. Press /start to restart.")

def handle_start_time(message):
    user_id = message.from_user.id
    if user_id not in user_booking_flow:
        bot.send_message(user_id, "Booking flow expired. Please try /start again.")
        return
    flow_data = user_booking_flow[user_id]
    time_str = message.text.strip()
    try:
        proposed_start = dt.strptime(time_str, "%H:%M").time()
        if proposed_start.minute % 15 != 0:
            bot.send_message(user_id, "Start time must be in 15-minute increments.")
            bot.register_next_step_handler(message, handle_start_time)
            return
        proposed_dt = dt.combine(flow_data["booking_date"].date(), proposed_start)
        if check_start_conflict(flow_data["venue"], proposed_dt):
            bot.send_message(user_id, "The specified start time conflicts with an existing confirmed booking. Exiting booking process.")
            user_booking_flow.pop(user_id, None)
            return
        flow_data["proposed_start"] = proposed_start
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Confirm", callback_data="confirm_start"),
            types.InlineKeyboardButton("Re-enter", callback_data="reenter_start"),
            types.InlineKeyboardButton("Exit", callback_data="exit_start")
        )
        bot.send_message(user_id, f"You entered {proposed_start.strftime('%H:%M')}. Confirm?", reply_markup=markup)
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
        bot.edit_message_text(f"Start time confirmed as {flow_data['start_time'].strftime('%H:%M')}.", call.message.chat.id, call.message.message_id)
        msg = bot.send_message(user_id, "Enter duration (H:MM):")
        bot.register_next_step_handler(msg, handle_duration)
    elif call.data == "reenter_start":
        bot.edit_message_text("Please re-enter start time (HH:MM):", call.message.chat.id, call.message.message_id)
        msg = bot.send_message(user_id, "Input your new timing")
        bot.register_next_step_handler(msg, handle_start_time)
    else:
        bot.edit_message_text("Booking process cancelled. Press /start to restart.", call.message.chat.id, call.message.message_id)
        user_booking_flow.pop(user_id, None)

def handle_duration(message):
    user_id = message.from_user.id
    if user_id not in user_booking_flow:
        bot.send_message(user_id, "Booking flow expired. Please try /start again.")
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
        flow_data["proposed_duration"] = duration_str
        start_dt = dt.combine(flow_data["booking_date"].date(), flow_data["start_time"])
        end_dt = start_dt + timedelta(hours=hours, minutes=minutes)
        if check_conflict(flow_data["venue"], start_dt, duration_str, user_id):
            bot.send_message(user_id, "This time slot overlaps with an existing approved booking. Exiting booking process.")
            user_booking_flow.pop(user_id, None)
            return
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Confirm", callback_data="confirm_duration"),
            types.InlineKeyboardButton("Re-enter", callback_data="reenter_duration"),
            types.InlineKeyboardButton("Exit", callback_data="exit_duration")
        )
        bot.send_message(user_id, f"You entered duration {duration_str} (ending at {end_dt.strftime('%H:%M')}). Confirm?", reply_markup=markup)
    except ValueError as ve:
        bot.send_message(user_id, f"Invalid duration format: {ve}. Please try again.")
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
        bot.edit_message_text(f"Duration confirmed as {flow_data['duration']}.", call.message.chat.id, call.message.message_id)
        bot.send_message(user_id, "Enter a short reason for booking the venue:")
        bot.register_next_step_handler(call.message, handle_reason)
    elif call.data == "reenter_duration":
        bot.edit_message_text("Please re-enter duration (H:MM):", call.message.chat.id, call.message.message_id)
        msg = bot.send_message(user_id, "Input your duration again")
        bot.register_next_step_handler(msg, handle_duration)
    else:
        bot.edit_message_text("Booking process cancelled. Please try /start again.", call.message.chat.id, call.message.message_id)
        user_booking_flow.pop(user_id, None)

def handle_reason(message):
    user_id = message.from_user.id
    if user_id not in user_booking_flow:
        bot.send_message(user_id, "Booking flow expired. Please try /start again.")
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
    msg = (f"Booking for {venue['name']} on {display_date} from {display_start} to {display_end} has been placed.\n")
    if (flow_data["user"]["role"].strip().lower() != "jcrc" and 
        venue["name"].strip().lower() in ["reading room", "dining hall"]):
        msg += "It is pending approval by JCRC."
    else:
        msg += "It is confirmed."
    msg += "\nPress /start to restart the process."
    bot.send_message(user_id, msg)
    user_booking_flow.pop(user_id, None)
