# -*- coding: utf-8 -*-
"""Инструменты: продажи, отчёт по продажам."""

import json
from datetime import datetime, timedelta

from ms_client import ms_get

SALES_TOOLS = [
    {
        "name": "get_sales",
        "description": "Получить данные о продажах (отгрузки) за период. Поддерживает точные даты или days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "За последние N дней (если нет date_from)", "default": 7},
                "date_from": {"type": "string", "description": "Начало периода YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "Конец периода YYYY-MM-DD"},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "get_sales_report",
        "description": "Топ продаж по выручке за период — какие SKU продаются лучше всего.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
                "date_from": {"type": "string", "description": "Начало периода YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "Конец периода YYYY-MM-DD"},
                "limit": {"type": "integer", "default": 15},
            },
        },
    },
    {
        "name": "get_returns",
        "description": "Возвраты от покупателей за период.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
                "limit": {"type": "integer", "default": 30},
            },
        },
    },
]


async def tool_get_sales(days=7, limit=50, date_from=None, date_to=None) -> str:
    if date_from:
        dt_from = f"{date_from} 00:00:00"
    else:
        dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    filters = [f"moment>{dt_from}"]
    if date_to:
        filters.append(f"moment<{date_to} 23:59:59")
    data = await ms_get("/entity/demand", {
        "filter": ";".join(filters),
        "order": "moment,desc",
        "limit": limit,
        "expand": "agent",
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
                "sum_uah": round(r.get("sum", 0) / 100, 2),
            }
            for r in rows[:20]
        ],
    }
    return json.dumps(result, ensure_ascii=False)


async def tool_get_sales_report(days=30, limit=15, date_from=None, date_to=None) -> str:
    if date_from:
        dt_from = f"{date_from} 00:00:00"
    else:
        dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    if date_to:
        dt_to = f"{date_to} 23:59:59"
    else:
        dt_to = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        data = await ms_get("/report/turnover/all", {
            "momentFrom": dt_from, "momentTo": dt_to,
            "limit": limit, "order": "revenue,desc",
        })
        rows = data.get("rows", [])
        result = [
            {
                "name": r.get("assortment", {}).get("name", r.get("name", "?")),
                "revenue_uah": round(r.get("revenue", 0) / 100, 2),
                "qty": r.get("sellQuantity", 0),
            }
            for r in rows
        ]
        return json.dumps({"days": days, "top_products": result}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


async def tool_get_returns(days=30, limit=30) -> str:
    dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    data = await ms_get("/entity/salesreturn", {
        "filter": f"moment>{dt_from}",
        "order": "moment,desc",
        "limit": limit,
        "expand": "agent",
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
            }
            for r in rows[:20]
        ],
    }
    return json.dumps(result, ensure_ascii=False)


SALES_TOOL_MAP = {
    "get_sales": tool_get_sales,
    "get_sales_report": tool_get_sales_report,
    "get_returns": tool_get_returns,
}
