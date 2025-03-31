from config import logger, bot
import help_command
import registration
import booking_flow
import booking_utils
import admin
import approval
import view_cancel
import restart

if __name__ == "__main__":
    logger.critical("Bot is starting polling...")
    try:
        bot.polling(none_stop=True)
    except Exception:
        logger.exception("Unhandled exception in bot polling:")
        raise