# -*- coding: utf-8 -*-
"""Обработчики текстовых (и в будущем голосовых) сообщений."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from handlers.commands import is_allowed
from claude_agent import run_claude_agent

logger = logging.getLogger(__name__)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # В групповых чатах бот молчит — только постит по расписанию
    if update.effective_chat.type in ("group", "supergroup"):
        return

    if not is_allowed(update):
        await update.message.reply_text("⛔ Доступ закрыт.")
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    thinking_msg = await update.message.reply_text("⏳ Думаю...")

    try:
        answer = await run_claude_agent(user_id, text)
        # Разбиваем длинные ответы (Telegram лимит 4096 символов)
        if len(answer) <= 4096:
            await thinking_msg.edit_text(answer, parse_mode="Markdown")
        else:
            # Первый чанк — редактируем thinking_msg
            await thinking_msg.edit_text(answer[:4096], parse_mode="Markdown")
            # Остальные — отдельными сообщениями
            for i in range(4096, len(answer), 4096):
                await update.message.reply_text(answer[i:i + 4096], parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Agent error for user {user_id}: {e}")
        try:
            await thinking_msg.edit_text("❌ Что-то пошло не так. Попробуй ещё раз или напиши /clear")
        except Exception:
            pass
