from config import bot, supabase, admin_update_flow, ROLES
from telebot import types
from db_helpers import get_user_info

@bot.message_handler(commands=['admin_update'])
def admin_update_command(message):
    user = get_user_info(message.from_user.id)
    if not user:
        return
    if user["role"].strip().lower() != "admin":
        bot.send_message(message.from_user.id, "You do not have permission to update other users. Press /start to restart.")
        return
    bot.send_message(message.from_user.id, "Please enter the User ID of the user you want to update:")
    bot.register_next_step_handler(message, admin_update_user_id)

def admin_update_user_id(message):
    try:
        target_user_id = int(message.text.strip())
    except ValueError:
        bot.send_message(message.from_user.id, "Invalid input. Please enter a numeric User ID. Exiting admin update.")
        admin_update_flow.pop(message.from_user.id, None)
        return
    target_user_info = get_user_info(target_user_id)
    if not target_user_info:
        bot.send_message(message.from_user.id, "No user found with that ID. Exiting admin update.")
        admin_update_flow.pop(message.from_user.id, None)
        return
    admin_update_flow[message.from_user.id] = {"target_user_id": target_user_id}
    markup = types.InlineKeyboardMarkup()
    for role in ROLES.keys():
        btn = types.InlineKeyboardButton(ROLES[role], callback_data=f"setrole_{target_user_id}_{ROLES[role]}")
        markup.add(btn)
    bot.send_message(message.from_user.id, f"User found: {target_user_info['name']}. Select the new role:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("setrole_"))
def callback_set_role(call):
    parts = call.data.split("_")
    target_user_id = parts[1]
    selected_role = parts[2]
    admin_id = call.from_user.id
    if admin_id in admin_update_flow:
        admin_update_flow[admin_id]["new_role"] = selected_role
    markup = types.InlineKeyboardMarkup()

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
        f"User {target_user_id} updated: Role = {ROLES[new_role]}, CCA = {new_cca if new_cca else 'None'}.",
        call.message.chat.id,
        call.message.message_id
    )
    try:
        bot.send_message(target_user_id, f"You have been updated as: {ROLES[new_role]} of {new_cca if new_cca else 'None'}.")
    except Exception as e:
        print(f"Error sending update notification to user {target_user_id}: {e}")
    admin_update_flow.pop(admin_id, None)
