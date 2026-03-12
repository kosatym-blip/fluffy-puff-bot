# -*- coding: utf-8 -*-
"""
Fluffy Puff — AI Telegram Bot
Команда пишет свободным текстом → Claude анализирует данные МС → умный ответ

pip install python-telegram-bot httpx anthropic python-dotenv
"""

import asyncio
import logging
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

import httpx
from anthropic import AsyncAnthropic
from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters,
)

load_dotenv()

# ─── Конфигурация ─────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
ANTHROPIC_KEY    = os.getenv("ANTHROPIC_API_KEY", "")
MOYSKLAD_TOKEN   = os.getenv("MOYSKLAD_TOKEN", "")
ALLOWED_USER_IDS = set(
    int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()
)

MS_BASE    = "https://api.moysklad.ru/api/remap/1.2"
MS_HEADERS = {"Authorization": f"Bearer {MOYSKLAD_TOKEN}", "Accept-Encoding": "gzip"}

WAREHOUSE_RAW = "e931e894-16dc-11ee-0a80-044400023b0b"
WAREHOUSE_FG  = "6bef019c-16eb-11ee-0a80-05460002d477"
WAREHOUSE_WIP = "65a5f7c5-16eb-11ee-0a80-09ad000284be"

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

anthropic = AsyncAnthropic(api_key=ANTHROPIC_KEY)

# История диалогов на пользователя (в памяти)
user_histories: dict[int, list] = {}


# ─── Инструменты для Claude (он сам решает что вызвать) ───────────────────────
TOOLS = [
    {
        "name": "get_stock",
        "description": "Получить остатки товаров на складах Fluffy Puff. warehouse: 'raw'=сырьё, 'fg'=готовая продукция, 'all'=все склады. search — поиск по коду (цифры) или названию.",
        "input_schema": {
            "type": "object",
            "properties": {
                "warehouse": {"type": "string", "enum": ["raw", "fg", "wip", "all"], "default": "all"},
                "search": {"type": "string", "description": "Поиск по коду товара или названию"},
                "only_critical": {"type": "boolean", "description": "Только критические (нулевые и < 5 шт/500 мл)"}
            }
        }
    },
    {
        "name": "get_sales",
        "description": "Получить данные о продажах (отгрузки) за период.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "За сколько последних дней", "default": 7},
                "limit": {"type": "integer", "default": 50}
            }
        }
    },
    {
        "name": "get_sales_report",
        "description": "Топ продаж по выручке за период — какие SKU продаются лучше всего.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
                "limit": {"type": "integer", "default": 15}
            }
        }
    },
    {
        "name": "get_orders",
        "description": "Заказы покупателей за период.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 7},
                "limit": {"type": "integer", "default": 30}
            }
        }
    },
    {
        "name": "get_cashflow",
        "description": "Движение денег (DDS) — входящие и исходящие платежи за период.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30}
            }
        }
    },
    {
        "name": "get_processing_plans",
        "description": "Техкарты (BOM) — состав материалов для производства конкретного продукта.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Название продукта для поиска техкарты"}
            }
        }
    },
    {
        "name": "calculate_purchase_needs",
        "description": "Рассчитать что нужно закупить для выполнения плана производства.",
        "input_schema": {
            "type": "object",
            "properties": {
                "production_plan": {
                    "type": "object",
                    "description": "Словарь {название_продукта: количество_единиц}",
                    "additionalProperties": {"type": "integer"}
                }
            },
            "required": ["production_plan"]
        }
    }
]


# ─── Реализация инструментов ──────────────────────────────────────────────────
async def ms_get(path: str, params: dict = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{MS_BASE}{path}", headers=MS_HEADERS, params=params or {})
        r.raise_for_status()
        return r.json()


async def tool_get_stock(warehouse="all", search=None, only_critical=False) -> str:
    params = {"limit": 500}
    wh_map = {"raw": WAREHOUSE_RAW, "fg": WAREHOUSE_FG, "wip": WAREHOUSE_WIP}

    if warehouse != "all" and warehouse in wh_map:
        params["filter"] = f"storeId={wh_map[warehouse]}"

    # Если поиск по коду — находим имя
    name_filter = None
    if search and search.strip().isdigit():
        try:
            d = await ms_get("/entity/product", {"filter": f"code={search.strip()}"})
            if d.get("rows"):
                name_filter = d["rows"][0].get("name", "")
        except Exception:
            pass

    data = await ms_get("/report/stock/all", params)
    rows = data.get("rows", [])

    if name_filter:
        rows = [r for r in rows if name_filter.lower() in r.get("name", "").lower()]
    elif search and not search.strip().isdigit():
        rows = [r for r in rows if search.lower() in r.get("name", "").lower()]

    if only_critical:
        rows = [r for r in rows if r.get("stock", 0) <= 5]

    result = []
    for r in rows[:80]:
        result.append({
            "name": r.get("name", ""),
            "code": r.get("code", ""),
            "stock": r.get("stock", 0),
            "uom": r.get("uom", {}).get("name", ""),
            "folder": r.get("folder", {}).get("name", "")
        })

    return json.dumps(result, ensure_ascii=False)


async def tool_get_sales(days=7, limit=50) -> str:
    dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    data = await ms_get("/entity/demand", {
        "filter": f"moment>{dt_from}",
        "order": "moment,desc",
        "limit": limit,
        "expand": "agent"
    })
    rows = data.get("rows", [])
    total = sum(r.get("sum", 0) for r in rows) / 100
    result = {
        "period_days": days,
        "count": len(rows),
        "total_uah": round(total, 2),
        "avg_uah": round(total / len(rows), 2) if rows else 0,
        "items": [
            {
                "date": r.get("moment", "")[:10],
                "agent": r.get("agent", {}).get("name", "?"),
                "sum_uah": round(r.get("sum", 0) / 100, 2)
            }
            for r in rows[:20]
        ]
    }
    return json.dumps(result, ensure_ascii=False)


async def tool_get_sales_report(days=30, limit=15) -> str:
    dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    dt_to   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        data = await ms_get("/report/turnover/all", {
            "momentFrom": dt_from, "momentTo": dt_to,
            "limit": limit, "order": "revenue,desc"
        })
        rows = data.get("rows", [])
        result = [
            {
                "name": r.get("assortment", {}).get("name", r.get("name", "?")),
                "revenue_uah": round(r.get("revenue", 0) / 100, 2),
                "qty": r.get("sellQuantity", 0)
            }
            for r in rows
        ]
        return json.dumps({"days": days, "top_products": result}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


async def tool_get_orders(days=7, limit=30) -> str:
    dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    data = await ms_get("/entity/customerorder", {
        "filter": f"moment>{dt_from}",
        "order": "moment,desc",
        "limit": limit,
        "expand": "agent,state"
    })
    rows = data.get("rows", [])
    total = sum(r.get("sum", 0) for r in rows) / 100
    result = {
        "period_days": days,
        "count": len(rows),
        "total_uah": round(total, 2),
        "items": [
            {
                "date": r.get("moment", "")[:10],
                "agent": r.get("agent", {}).get("name", "?"),
                "sum_uah": round(r.get("sum", 0) / 100, 2),
                "status": r.get("state", {}).get("name", "")
            }
            for r in rows[:20]
        ]
    }
    return json.dumps(result, ensure_ascii=False)


async def tool_get_cashflow(days=30) -> str:
    dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    params  = {"filter": f"moment>{dt_from}", "limit": 200}
    inc = await ms_get("/entity/paymentin", params)
    out = await ms_get("/entity/paymentout", params)
    income  = sum(r.get("sum", 0) for r in inc.get("rows", [])) / 100
    outcome = sum(r.get("sum", 0) for r in out.get("rows", [])) / 100
    return json.dumps({
        "days": days,
        "income_uah": round(income, 2),
        "outcome_uah": round(outcome, 2),
        "balance_uah": round(income - outcome, 2)
    }, ensure_ascii=False)


async def tool_get_processing_plans(search=None) -> str:
    params = {"limit": 50, "expand": "materials.assortment"}
    data = await ms_get("/entity/processingplan", params)
    rows = data.get("rows", [])
    if search:
        rows = [r for r in rows if search.lower() in r.get("name", "").lower()]
    result = []
    for r in rows[:10]:
        materials = []
        for m in r.get("materials", {}).get("rows", []):
            materials.append({
                "name": m.get("assortment", {}).get("name", "?"),
                "quantity": m.get("quantity", 0)
            })
        result.append({"name": r.get("name", ""), "materials": materials})
    return json.dumps(result, ensure_ascii=False)


async def tool_calculate_purchase_needs(production_plan: dict) -> str:
    # Загружаем техкарты
    data = await ms_get("/entity/processingplan", {"limit": 100, "expand": "materials.assortment"})
    plans = data.get("rows", [])
    # Загружаем остатки сырья
    stock_data = await ms_get("/report/stock/all", {"limit": 500, "filter": f"storeId={WAREHOUSE_RAW}"})
    stock = {r.get("name", ""): r.get("stock", 0) for r in stock_data.get("rows", [])}

    needs: dict[str, float] = {}
    not_found = []

    for product_name, qty in production_plan.items():
        plan = next((p for p in plans if product_name.lower() in p.get("name", "").lower()), None)
        if not plan:
            not_found.append(product_name)
            continue
        for m in plan.get("materials", {}).get("rows", []):
            mat_name = m.get("assortment", {}).get("name", "?")
            mat_qty  = m.get("quantity", 0) * qty
            needs[mat_name] = needs.get(mat_name, 0) + mat_qty

    to_order = {}
    for mat, needed in needs.items():
        current = stock.get(mat, 0)
        if needed > current:
            to_order[mat] = round(needed - current, 1)

    return json.dumps({
        "production_plan": production_plan,
        "to_order": to_order,
        "not_found_plans": not_found
    }, ensure_ascii=False)



async def tool_ms_query(endpoint: str, params: dict = None, method: str = "GET", body: dict = None) -> str:
    """Universal MoySklad API query - any endpoint, any params."""
    try:
        url = f"{MS_BASE}{endpoint}" if endpoint.startswith("/") else endpoint
        logger.info(f"ms_query {method} {endpoint} params={params}")
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.request(method.upper(), url, headers=MS_HEADERS, params=params or {}, json=body)
            r.raise_for_status()
            data = r.json()
        if isinstance(data, dict) and "rows" in data:
            rows = data["rows"]
            return json.dumps({"total": data.get("meta", {}).get("size", len(rows)), "rows": rows}, ensure_ascii=False, default=str)
        return json.dumps(data, ensure_ascii=False, default=str)
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"HTTP {e.response.status_code}: {e.response.text[:500]}"})
    except Exception as e:
        return json.dumps({"error": str(e)})

TOOL_MAP = {
    "get_stock": tool_get_stock,
    "get_sales": tool_get_sales,
    "get_sales_report": tool_get_sales_report,
    "get_orders": tool_get_orders,
    "get_cashflow": tool_get_cashflow,
    "get_processing_plans": tool_get_processing_plans,
    "calculate_purchase_needs": tool_calculate_purchase_needs,
    "ms_query": tool_ms_query,
}


# ─── Claude agent loop ────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Ты — AI-ассистент компании Fluffy Puff, производителя вейп-жидкостей (Украина, UAH).

У тебя есть доступ к системе Мой Склад через инструменты. Используй ихчтобы отвечать на вопросы команды.

Продуктовые линейки:
- Alpha 50/50 Ped
- Tсокеов позыции:
- Отвечай кратко и по делу, без лишней воды
- Используй цифры и факты из реальных данных мх
- Форматирует ответ для заголовков ##, используй эмодзи и жирный текст *текст*)
- Если данных нет — скажи честно
- Язык ответа — русский
- Валюта — UAH (₴)"""


async def run_claude_agent(user_id: int, user_message: str) -> str:
    """Запускает Claude сы инструментами, возвращает финальный ответ."""
    history = user_histories.setdefault(user_id, [])
    history.append({"role": "user", "content": user_message})

    # Ограничиваем историю последним 20 сообщениями
    if len(history) > 20:
        history = history[-20:]
        user_histories[user_id] = history

    messages = list(history)

    while True:
        response = await anthropic.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Если Claude хочет вызвать инструменты
        if response.stop_reason == "tool_use":
            # Добавляем ответ Claude в историю
            messages.append({"role": "assistant", "content": response.content})

            # Выполняем все вызванные инструменты
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info(f"Tool call: {block.name}({block.input})")
                    try:
                        fn = TOOL_MAP.get(block.name)
                        if fn:
                            result = await fn(**block.input)
                        else:
                            result = json.dumps({"error": f"Unknown tool: {block.name}"})
                    except Exception as e:
                        result = json.dumps({"error": str(e)})

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result
                    })

            messages.append({"role": "user", "content": tool_results})

        else:
            # Финальный текстовый ответ
            final_text = next(
                (b.text for b in response.content if hasattr(b, "text")),
                "Не могу ответить на этот вопрос."
            )
            # Сохраняем в историю
            history.append({"role": "assistant", "content": final_text})
            return final_text


# ─── Telegram handlers ────────────────────────────────────────────────────────
def is_allowed(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else None
    if not ALLOWED_USER_IDS:
        return True
    return uid in ALLOWED_USER_IDS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        parse_mode="Markdown"
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return
    user_histories.pop(update.effective_user.id, None)
    await update.message.reply_text("🧹 История диалога очищена. Начинаем заново!")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update): return
    await update.message.reply_text(
        "💡 *Что я умею:*\n\n"
        "📦 *Склад и остатки**\n"
        "• _Что заканчиваетс?_ Что в нуле?\n"
        "— Сколько осталось название товара]?\n\n"
        "📈 *Продажи*\n"
        "— Топ продаж за месяц\n"
        "— Сколько продали на этой неделе?\n\n"
        "💰 *Финансы*\n"
        "— Движение денег за 30 дней\n"
        "— Сколько пришло платежей?\n\n"
        "🏭 *Производство*\n"
        "— Что нужно закупить для производства X единиц Y?\n"
        "— Покажи состав [продукт]\n\n"
        "Командь:\n"
        "/clear — очистить историю диалога",
        parse_mode="Markdown"
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("⛔ Доступ закрыт.")
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Показываем что обрабатываем
    thinking_msg = await update.message.reply_text("⏳ Думаю...")

    try:
        answer = await run_claude_agent(user_id, text)
        await thinking_msg.edit_text(answer, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Agent error for user {user_id}: {e}")
        await thinking_msg.edit_text(
            f"❌ Что-то пошло не так. Попробуй ещё раз или напиши /clear"
        )


# ─── Запуск ───────────────────────────────────────────────────────────────────
async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "Начать работу"),
        BotCommand("help", "Что умеет бот"),
        BotCommand("clear", "Очистить историю диалога"),
    ])


def main():
    assert TELEGRAM_TOKEN,   "TELEGRAM_TOKEN не задан"
    assert ANTHROPIC_KEY,    "ANTHROPIC_API_KEY не задан"
    assert MOYSKLAD_TOKEN,   "MOYSKLAD_TOKEN не задан"

    logger.info("🚀 Запуск Fluffy Puff AI Bot...")
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
