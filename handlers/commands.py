# -*- coding: utf-8 -*-
"""Обработчики команд /start, /help, /clear."""

from telegram import Update
from telegram.ext import ContextTypes

from config import ALLOWED_USER_IDS
from claude_agent import clear_history


def is_group_chat(update: Update) -> bool:
    return update.effective_chat.type in ("group", "supergroup")


def is_allowed(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    if not ALLOWED_USER_IDS:
        return True
    return uid in ALLOWED_USER_IDS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_group_chat(update):
        return
    if not is_allowed(update):
        await update.message.reply_text("⛔ Доступ закрыт. Обратитесь к администратору.")
        return
    name = update.effective_user.first_name or "коллега"
    await update.message.reply_text(
        f"👋 Привет, {name}!\n\n"
        "Я AI-ассистент *Fluffy Puff* с доступом к Мой Склад.\n\n"
        "Спрашивай что угодно, например:\n"
        "• _Что нам нужно срочно закупить?_\n"
        "• _Какие SKU лучше всего продаются?_\n"
        "• _Сколько мы заработали за месяц?_\n"
        "• _Что продаётся лучше всего?_\n"
        "• _Какой остаток ароматизаторов?_\n"
        "• _Что у нас с движением денег за месяц?_\n\n"
        "Просто пиши свободным текстом 👇",
        parse_mode="Markdown",
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_group_chat(update):
        return
    if not is_allowed(update):
        return
    clear_history(update.effective_user.id)
    await update.message.reply_text("🧹 История диалога очищена. Начинаем заново!")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_group_chat(update):
        return
    if not is_allowed(update):
        return
    await update.message.reply_text(
        "💡 *Что я умею:*\n\n"
        "📦 *Склад и остатки*\n"
        "• Что заканчивается? Что в нуле?\n"
        "• Сколько осталось [название товара]?\n\n"
        "📈 *Продажи*\n"
        "• Топ продаж за месяц\n"
        "• Сколько продали на этой неделе?\n\n"
        "💰 *Финансы*\n"
        "• Движение денег за 30 дней\n"
        "• Сколько пришло платежей?\n\n"
        "🏭 *Производство*\n"
        "• Что нужно закупить для производства X единиц Y?\n"
        "• Покажи состав [продукт]\n\n"
        "Команды:\n"
        "/clear — очистить историю диалога",
        parse_mode="Markdown",
    )
