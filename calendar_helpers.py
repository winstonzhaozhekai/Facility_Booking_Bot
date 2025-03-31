import google.oauth2.service_account
from googleapiclient.discovery import build
from datetime import datetime as dt
from config import VENUE_COLORS
from db_helpers import parse_duration, get_user_info

# Google Calendar setup
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = r'facility-booking-bot-cc90373ee34e.json'
calendar_id = 'fde2719902f4ca8ada620b4922fa8365a333b2cf79885e048e107dd6d7834b9a@group.calendar.google.com'

credentials = google.oauth2.service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
calendar_service = build('calendar', 'v3', credentials=credentials)

def add_event_to_calendar(booking, venue):
    start_dt = dt.fromisoformat(booking["booking_date"])
    from booking_utils import parse_duration  # to get duration
    duration_td = parse_duration(booking["duration"])
    end_dt = start_dt + duration_td

    # Get user info from booking if needed (omitted here; assume already available)
    summary = f"{venue['name']}: {booking.get('reason', 'No Reason Provided')}"
    user_info = get_user_info(booking["user_id"])
    print(user_info)
    description = f"Booked by: {user_info.get('name', 'Unknown User')}"
    if user_info.get("role", "Resident") != "Resident":
        description += f", ({user_info.get('role','')}, {user_info.get('cca','')})"
    description += f" from {user_info.get('block', 'No Block')}"
    color_id = VENUE_COLORS.get(venue["name"], "1")
    event = {
        'summary': summary,
        'description': description,
        'location': venue['name'],
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': 'Asia/Singapore',
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': 'Asia/Singapore',
        },
        'colorId': color_id
    }
    created_event = calendar_service.events().insert(calendarId=calendar_id, body=event).execute()
    print('Event created on Calendar: {}'.format(created_event.get('htmlLink')))
    return created_event.get("id")

def remove_event_from_calendar(event_id):
    try:
        calendar_service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        print(f"Event {event_id} removed from Google Calendar.")
    except Exception as e:
        print(f"Failed to remove event from calendar: {e}")