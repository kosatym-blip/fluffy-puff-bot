# -*- coding: utf-8 -*-
"""
Fluffy Puff AI Bot — точка входа.

pip install python-telegram-bot httpx anthropic python-dotenv
"""

import logging

from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from config import TELEGRAM_TOKEN, ANTHROPIC_KEY, MOYSKLAD_TOKEN, ALLOWED_USER_IDS
from handlers.commands import cmd_start, cmd_help, cmd_clear
from handlers.messages import message_handler
from scheduler import start_scheduler, set_bot

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Начать работу"),
        BotCommand("help", "Что умеет бот"),
        BotCommand("clear", "Очистить историю диалога"),
    ])
    # Запускаем планировщик внутри event loop
    set_bot(app.bot)
    start_scheduler()


def main():
    assert TELEGRAM_TOKEN, "TELEGRAM_TOKEN не задан"
    assert ANTHROPIC_KEY, "ANTHROPIC_API_KEY не задан"
    assert MOYSKLAD_TOKEN, "MOYSKLAD_TOKEN не задан"

    logger.info("🚀 Запуск Fluffy Puff AI Bot v2...")
    if ALLOWED_USER_IDS:
        logger.info(f"Whitelist: {ALLOWED_USER_IDS}")
    else:
        logger.warning("ALLOWED_USER_IDS пустой — бот открыт для всех!")

    app = Application.builder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    logger.info("Bot running. Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
