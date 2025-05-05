from datetime import datetime as dt
from config import bot, supabase
from db_helpers import get_user_info, get_all_venues, get_all_users, parse_duration
from notifications import notify_approval

@bot.message_handler(commands=['approve'])
def approve_command(message):
    user = get_user_info(message.from_user.id)
    if not user:
        return
    if user["role"].strip().lower() != "jcrc":
        bot.send_message(user["user_id"], "You do not have permission to approve bookings. Press /start to restart.")
        return
    venue_ids = get_venue_ids_for(["Reading Room", "Dining Hall"])
    response = supabase.table("bookings").select("*") \
        .eq("status", "pending approval") \
        .in_("venue_id", venue_ids) \
        .execute()
    pending = response.data if response.data else []
    if not pending:
        bot.send_message(user["user_id"], "No pending bookings for approval. Press /start to restart.")
        return
    venues = get_all_venues()
    users = get_all_users()
    venue_dict = {str(v["venue_id"]): v["name"] for v in venues}
    users_dict = {str(u["user_id"]): u["name"] for u in users}
    msg = "Pending bookings for approval:\n"
    for b in pending:
        booking_start = dt.fromisoformat(b["booking_date"])
        dur = parse_duration(b["duration"])
        end_dt = booking_start + dur
        start_str = booking_start.strftime("%Y-%m-%d %H:%M")
        end_str = end_dt.strftime("%Y-%m-%d %H:%M")
        venue_name = venue_dict.get(str(b["venue_id"]), "Unknown Venue")
        user_name = users_dict.get(str(b["user_id"]), "Unknown User")
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
    msg += "\nPlease enter the Booking ID to approve:"
    bot.send_message(user["user_id"], msg)
    bot.register_next_step_handler(message, process_approval)

def get_venue_ids_for(names):
    from db_helpers import get_all_venues
    venues = get_all_venues()
    return [v["venue_id"] for v in venues if v["name"].strip().lower() in [n.lower() for n in names]]

def process_approval(message):
    user = get_user_info(message.from_user.id)
    if not user:
        return
    try:
        booking_id = int(message.text.strip())
        res = supabase.table("bookings").select("*").eq("booking_id", booking_id).execute()
        if not res.data:
            bot.send_message(message.from_user.id, "Invalid Booking ID: booking not found. Press /start to restart.")
            return
        booking = res.data[0]
        if booking["status"] != "pending approval":
            bot.send_message(message.from_user.id, "Invalid Booking ID: booking is not pending approval. Press /start to restart.")
            return
        supabase.table("bookings").update({"status": "confirmed"}).eq("booking_id", booking_id).execute()
        updated_res = supabase.table("bookings").select("*").eq("booking_id", booking_id).execute()
        updated_booking = updated_res.data[0] if updated_res.data else None
        if updated_booking:
            if not updated_booking.get("calendar_event_id"):
                from calendar_helpers import add_event_to_calendar
                venue_data = supabase.table("venues").select("*").eq("venue_id", updated_booking["venue_id"]).execute()
                venue = venue_data.data[0] if venue_data.data else {}
                event_id = add_event_to_calendar(updated_booking, venue)
                supabase.table("bookings").update({"calendar_event_id": event_id}).eq("booking_id", booking_id).execute()
            notify_approval(updated_booking)
        bot.send_message(message.from_user.id, f"Booking {booking_id} approved. Press /start to restart.")
    except ValueError:
        bot.send_message(message.from_user.id, "Invalid Booking ID. Press /start to restart.")
