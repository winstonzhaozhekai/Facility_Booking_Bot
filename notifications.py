from datetime import datetime as dt
from config import bot, GROUP_CHAT_IDS, supabase
from db_helpers import parse_duration, get_user_info

def notify_approval(booking):
    booking_id = booking["booking_id"]
    user_id = booking["user_id"]
    user_info = get_user_info(user_id)
    user_name = user_info.get("name", "Unknown User") if user_info else "Unknown User"
    venue_data = supabase.table("venues").select("*").eq("venue_id", booking["venue_id"]).execute()
    venue = venue_data.data[0] if venue_data.data else {}
    venue_name = venue.get("name", "Unknown Venue")
    booking_start = dt.fromisoformat(booking["booking_date"])
    dur = parse_duration(booking["duration"])
    end_dt = booking_start + dur
    start_str = booking_start.strftime("%Y-%m-%d %H:%M")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M")
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
    try:
        bot.send_message(user_id, f"Your booking has been approved!\n\n{detail_message}")
    except Exception as e:
        print(f"Failed to message user {user_id}: {e}")
    broadcast_text = f"Booking Approved!\n\n{detail_message}"
    for chat_id in GROUP_CHAT_IDS:
        try:
            bot.send_message(chat_id, broadcast_text)
        except Exception as e:
            print(f"Failed to notify group {chat_id}: {e}")

def notify_jcrc_of_new_request(booking):
    jcrc_result = supabase.table("users").select("*").eq("role", "jcrc").execute()
    jcrc_users = jcrc_result.data if jcrc_result.data else []
    if not jcrc_users:
        return
    booking_id = booking["booking_id"]
    user_id = booking["user_id"]
    user_info = get_user_info(user_id)
    user_name = user_info.get("name", "Unknown User") if user_info else "Unknown User"
    venue_data = supabase.table("venues").select("*").eq("venue_id", booking["venue_id"]).execute()
    venue = venue_data.data[0] if venue_data.data else {}
    venue_name = venue.get("name", "Unknown Venue")
    booking_start = dt.fromisoformat(booking["booking_date"])
    dur = parse_duration(booking["duration"])
    end_dt = booking_start + dur
    start_str = booking_start.strftime("%Y-%m-%d %H:%M")
    end_str = end_dt.strftime("%Y-%m-%d %H:%M")
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
    for jcrc_user in jcrc_users:
        jcrc_user_id = jcrc_user["user_id"]
        try:
            bot.send_message(jcrc_user_id, detail_msg)
        except Exception as e:
            print(f"Failed to notify JCRC user {jcrc_user_id}: {e}")
