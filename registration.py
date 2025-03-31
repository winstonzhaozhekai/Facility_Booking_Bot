from config import bot, supabase, user_booking_flow, BLOCKS
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
        if user['role'] == "Resident":
            bot.send_message(
                message.from_user.id,
                f"Welcome back {user.get('name', '')}! You are registered as: {user['role']} from {user.get('block', 'Unknown Block')}"
            )
        else:
            bot.send_message(
                message.from_user.id,
                f"Welcome back {user.get('name', '')}! You are registered as: {user['role']} of {user['cca']} from {user.get('block', 'Unknown Block')}"
            )
        send_main_menu(message.from_user.id)

def register_new_user(message):
    user_id = message.from_user.id
    name = message.text.strip()
    user_booking_flow[user_id] = {"name": name}
    markup = types.InlineKeyboardMarkup()
    for blk in BLOCKS:
        btn = types.InlineKeyboardButton(blk, callback_data=f"setblock_{blk.replace(' ', '')}")
        markup.add(btn)
    bot.send_message(
        user_id,
        f"Hi {name}! Please select your block (choices are permanent):",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("setblock_"))
def callback_set_block(call):
    user_id = call.from_user.id
    block = call.data.split("_")[1]
    block_name = " ".join([block[0], "Blk"]) if len(block) == 4 else block.replace('Blk', ' Blk')
    name = user_booking_flow.get(user_id, {}).get("name", None)
    if not name:
        bot.send_message(user_id, "Session expired. Please /start again.")
        return
    new_user = {
        "user_id": user_id,
        "name": name,
        "role": "Resident",
        "cca": "No CCA",
        "block": block_name
    }
    supabase.table("users").insert(new_user).execute()
    bot.edit_message_text(
        f"Thanks {name}! You are now registered as a Resident in {block_name}.",
        call.message.chat.id,
        call.message.message_id
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
