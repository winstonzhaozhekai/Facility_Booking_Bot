from config import bot, supabase, user_booking_flow
from telebot import types
from db_helpers import get_user_info

@bot.message_handler(commands=['start'])
def start(message):
    user = get_user_info(message.from_user.id)
    if user is None:
        bot.send_message(
            message.from_user.id,
            "Welcome! It looks like you're new here. Please tell us your name! (Use your real name.)"
        )
        bot.register_next_step_handler(message, register_new_user)
    else:
        bot.send_message(
            message.from_user.id,
            f"Welcome back {user.get('name', '')}! You are registered as: {user['role']}"
        )
        send_main_menu(message.from_user.id)

def register_new_user(message):
    user_id = message.from_user.id
    name = message.text.strip()
    user_booking_flow[user_id] = {"name": name}
    markup = types.InlineKeyboardMarkup()
    if not name:
        bot.send_message(user_id, "Session expired. Please /start again.")
        return
    new_user = {
        "user_id": user_id,
        "name": name,
        "role": "Resident",
        "cca": "No CCA",
        "block": None,
    }
    supabase.table("users").insert(new_user).execute()
    bot.send_message(
        user_id, f"Thanks {name}! You are now registered as a Resident."
    )
    send_main_menu(user_id)
    user_booking_flow.pop(user_id, None)

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
