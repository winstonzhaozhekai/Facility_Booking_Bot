from datetime import timedelta, datetime as dt
from config import supabase
from calendar_helpers import add_event_to_calendar, remove_event_from_calendar
from db_helpers import parse_duration
from notifications import notify_jcrc_of_new_request

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
    result = supabase.table("bookings").select("*") \
        .eq("user_id", user_id) \
        .eq("venue_id", venue["venue_id"]) \
        .eq("booking_date", booking_start_str) \
        .eq("duration", duration_text) \
        .eq("reason", reason) \
        .execute()
    new_booking_data = result.data[0] if result.data else None
    if new_booking_data and status == "confirmed":
        event_id = add_event_to_calendar(new_booking_data, venue)
        supabase.table("bookings").update({"calendar_event_id": event_id}).eq("booking_id", new_booking_data["booking_id"]).execute()
    if venue_name in ["reading room", "dining hall"] and status == "pending approval":
        result = supabase.table("bookings").select("*") \
            .eq("user_id", user_id) \
            .eq("venue_id", venue["venue_id"]) \
            .eq("booking_date", booking_start_str) \
            .eq("status", "pending approval") \
            .eq("reason", reason) \
            .execute()
        new_booking_data = result.data[0] if result.data else None
        if new_booking_data: 
            print(new_booking_data)
            notify_jcrc_of_new_request(new_booking_data)

def check_conflict(venue, new_booking_start, duration_text, user_id):
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
        if new_booking_start < confirmed_end and new_booking_end > confirmed_start:
            return True
    return False

def check_start_conflict(venue, proposed_start):
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
        if confirmed_start <= proposed_start < confirmed_end:
            return True
    return False

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