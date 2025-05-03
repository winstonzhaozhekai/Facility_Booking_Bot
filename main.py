from config import logger, bot

if __name__ == "__main__":
    logger.critical("Bot is starting polling...")
    try:
        bot.polling(none_stop=True)
    except Exception:
        logger.exception("Unhandled exception in bot polling:")
        raise