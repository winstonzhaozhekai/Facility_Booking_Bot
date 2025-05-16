import logging
import sys
import os
import pytz
from dotenv import load_dotenv
import telebot
from supabase import create_client, Client

load_dotenv()

# Minimal logging setup: only errors plus startup/restart messages
logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.ERROR)
file_handler = logging.FileHandler("bot_debug.log", encoding="utf-8")
file_handler.setLevel(logging.ERROR)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)
logger.addHandler(console_handler)
logger.addHandler(file_handler)
telebot.logger.setLevel(logging.ERROR)

# Bot configuration
TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# Timezone and Supabase
TZ = pytz.timezone('Asia/Singapore')
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Global constants (roles, blocks, etc.)
ROLES = {
    "Admin": "Admin",
    "JCRC": "JCRC",
    "Resident": "Resident"
}
VENUE_COLORS = {
    "Reading Room": "2",
    "Dining Hall": "3",
}

# Global dictionaries to keep track of ongoing flows
user_booking_flow = {}
admin_update_flow = {}

# List of group chat IDs (if any)
GROUP_CHAT_IDS = []
