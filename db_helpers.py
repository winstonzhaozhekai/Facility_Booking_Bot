from datetime import timedelta, datetime as dt
import json
from config import supabase

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

def get_all_venues():
    response = supabase.table("venues").select("*").execute()
    return response.data if response.data else []

def get_all_users():
    response = supabase.table("users").select("*").execute()
    return response.data if response.data else []

def user_can_access_venue(user, venue):
    if user is None:
        return False
    user_role = user["role"].strip().lower()
    user_cca = user.get("cca", "").strip().lower()
    user_block = user.get("block", "").strip().lower()
    allowed_roles = venue.get("allowed_roles") or []
    allowed_ccas = venue.get("allowed_ccas") or []
    allowed_blocks = venue.get("allowed_blocks") or []
    if isinstance(allowed_roles, str):
        allowed_roles = json.loads(allowed_roles)
    if isinstance(allowed_ccas, str):
        allowed_ccas = json.loads(allowed_ccas)
    if isinstance(allowed_blocks, str):
        allowed_blocks = json.loads(allowed_blocks)
    allowed_roles = [r.lower() for r in allowed_roles]
    allowed_ccas = [cca.lower() for cca in allowed_ccas]
    allowed_blocks = [b.lower() for b in allowed_blocks]
    if allowed_blocks and user_block in allowed_blocks:
        return True
    if allowed_roles and allowed_ccas:
        return user_role in allowed_roles and user_cca in allowed_ccas
    if allowed_roles and not allowed_ccas:
        return user_role in allowed_roles
    return False
