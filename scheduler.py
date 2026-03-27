# -*- coding: utf-8 -*-
"""Планировщик задач: еженедельный пересчёт кэша, ежедневные оповещения."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import GROUP_CHAT_ID, ALERT_CHAT_ID

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Europe/Kyiv")

# Ссылка на бот-приложение (устанавливается при запуске)
_bot = None


def set_bot(bot):
    """Сохраняет ссылку на Telegram bot для отправки сообщений."""
    global _bot
    _bot = bot


async def _send_to_group(text: str):
    """Отправляет сообщение в групповой чат."""
    if not _bot or not GROUP_CHAT_ID:
        logger.warning("Cannot send alert: bot or GROUP_CHAT_ID not set")
        return
    try:
        await _bot.send_message(
            chat_id=int(GROUP_CHAT_ID),
            text=text,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Failed to send group message: {e}")


async def _send_to_admin(text: str):
    """Отправляет сообщение админу (личный чат)."""
    chat_id = ALERT_CHAT_ID or GROUP_CHAT_ID
    if not _bot or not chat_id:
        return
    try:
        await _bot.send_message(chat_id=int(chat_id), text=text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to send admin message: {e}")


# ─── Задачи ──────────────────────────────────────────────────────────────────

async def _daily_production_plan():
    """07:00 — план производства на день."""
    logger.info("=== Scheduled: daily production plan ===")
    try:
        from tools.planning import tool_get_production_plan
        import json
        result = await tool_get_production_plan(days=1)
        data = json.loads(result)

        items = data.get("plan", [])
        if not items:
            await _send_to_group("📋 **План производства на сегодня**\n\nВсё в наличии, производство не требуется.")
            return

        lines = ["📋 **План производства на сегодня**\n"]
        for item in items[:20]:
            priority = item.get("priority", "")
            emoji = "🔴" if priority == "high" else "🟡" if priority == "medium" else "🟢"
            lines.append(
                f"{emoji} {item['product']}: **{item['to_produce']:.0f}** шт "
                f"(остаток {item['current_stock']}, {item['days_of_supply']} дн.)"
            )

        await _send_to_group("\n".join(lines))
    except Exception as e:
        logger.error(f"Daily production plan failed: {e}")


async def _daily_deficit_check():
    """08:00 — проверка дефицитов ГП и сырья."""
    logger.info("=== Scheduled: daily deficit check ===")
    try:
        from analytics.alerts import check_fg_deficit, check_raw_deficit

        fg_alert = await check_fg_deficit()
        if fg_alert:
            await _send_to_group(fg_alert)

        raw_alert = await check_raw_deficit()
        if raw_alert:
            await _send_to_group(raw_alert)
    except Exception as e:
        logger.error(f"Daily deficit check failed: {e}")


async def _daily_sales_alerts():
    """09:00 — оповещения отделу продаж."""
    logger.info("=== Scheduled: daily sales alerts ===")
    try:
        from analytics.alerts import check_sleeping_clients

        sleeping = await check_sleeping_clients()
        if sleeping:
            await _send_to_group(sleeping)
    except Exception as e:
        logger.error(f"Daily sales alerts failed: {e}")


async def _weekly_declining_clients():
    """Пн 09:00 — еженедельно: негативная динамика клиентов."""
    logger.info("=== Scheduled: weekly declining clients ===")
    try:
        from analytics.alerts import check_declining_clients

        declining = await check_declining_clients()
        if declining:
            await _send_to_group(declining)
    except Exception as e:
        logger.error(f"Weekly declining clients failed: {e}")


async def _daily_production_digest():
    """18:00 — дайджест: что произвели за день."""
    logger.info("=== Scheduled: daily production digest ===")
    try:
        from analytics.alerts import get_production_digest

        digest = await get_production_digest()
        await _send_to_group(digest)
    except Exception as e:
        logger.error(f"Daily production digest failed: {e}")


async def _weekly_cache_rebuild():
    """Пн 06:00 — еженедельный пересчёт аналитического кэша."""
    logger.info("=== Scheduled: weekly cache rebuild ===")
    try:
        from analytics.forecast import rebuild_analytics_cache
        await rebuild_analytics_cache()
        logger.info("=== Weekly cache rebuild complete ===")
    except Exception as e:
        logger.error(f"Weekly cache rebuild failed: {e}")


async def _weekly_production_plan():
    """Пн 07:00 — план производства на неделю."""
    logger.info("=== Scheduled: weekly production plan ===")
    try:
        from tools.planning import tool_get_production_plan
        import json
        result = await tool_get_production_plan(days=7)
        data = json.loads(result)

        items = data.get("plan", [])
        if not items:
            await _send_to_group("📋 **План производства на неделю**\n\nВсё в наличии.")
            return

        lines = ["📋 **План производства на неделю**\n"]
        for item in items[:25]:
            priority = item.get("priority", "")
            emoji = "🔴" if priority == "high" else "🟡" if priority == "medium" else "🟢"
            lines.append(
                f"{emoji} {item['product']}: **{item['to_produce']:.0f}** шт "
                f"(остаток {item['current_stock']})"
            )

        lines.append(f"\nВсего позиций: **{len(items)}**")
        await _send_to_group("\n".join(lines))
    except Exception as e:
        logger.error(f"Weekly production plan failed: {e}")


# ─── Регистрация ─────────────────────────────────────────────────────────────

def register_jobs():
    """Регистрирует все cron-задачи."""

    # Ежедневные
    scheduler.add_job(_daily_production_plan,
                      CronTrigger(hour=7, minute=0, timezone="Europe/Kyiv"),
                      id="daily_production_plan", replace_existing=True)

    scheduler.add_job(_daily_deficit_check,
                      CronTrigger(hour=8, minute=0, timezone="Europe/Kyiv"),
                      id="daily_deficit_check", replace_existing=True)

    scheduler.add_job(_daily_sales_alerts,
                      CronTrigger(hour=9, minute=0, timezone="Europe/Kyiv"),
                      id="daily_sales_alerts", replace_existing=True)

    scheduler.add_job(_daily_production_digest,
                      CronTrigger(hour=18, minute=0, timezone="Europe/Kyiv"),
                      id="daily_production_digest", replace_existing=True)

    # Еженедельные (понедельник)
    scheduler.add_job(_weekly_cache_rebuild,
                      CronTrigger(day_of_week="mon", hour=6, minute=0, timezone="Europe/Kyiv"),
                      id="weekly_cache_rebuild", replace_existing=True)

    scheduler.add_job(_weekly_production_plan,
                      CronTrigger(day_of_week="mon", hour=7, minute=0, timezone="Europe/Kyiv"),
                      id="weekly_production_plan", replace_existing=True)

    scheduler.add_job(_weekly_declining_clients,
                      CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="Europe/Kyiv"),
                      id="weekly_declining_clients", replace_existing=True)

    logger.info("Scheduled: 4 daily + 3 weekly jobs registered")


def start_scheduler():
    """Запускает планировщик."""
    register_jobs()
    scheduler.start()
    logger.info("Scheduler started")
