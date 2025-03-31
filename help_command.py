from config import bot

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        "Available Commands:\n"
        "/start - Register or login\n"
        "/getid - Get your Telegram User ID\n"
        "/book - Start a venue booking\n"
        "/cancel - Cancel an existing booking\n"
        "/view - View your active bookings\n"
        "/restart - Restart the bot (admin-only)\n"
        "\nFor further assistance, contact: @winstonzhao or @Jaredee"
    )
    bot.send_message(message.chat.id, help_text)
