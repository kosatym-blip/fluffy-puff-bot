# -*- coding: utf-8 -*-
"""Инструмент: ежедневный дайджест."""

import json
from datetime import datetime, timedelta

from ms_client import ms_get
from config import WAREHOUSE_FG, WAREHOUSE_RAW

DIGEST_TOOLS = [
    {
        "name": "get_daily_digest",
        "description": "Утренняя сводка: продажи и платежи за сегодня, критические остатки сырья, нулевые позиции ГП.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


async def tool_get_daily_digest() -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    dt_from = f"{today} 00:00:00"

    # Today's demands
    demands = await ms_get("/entity/demand", {
        "filter": f"moment>{dt_from}",
        "expand": "agent",
        "limit": 50,
    })
    demand_rows = demands.get("rows", [])
    demand_total = sum(r.get("sum", 0) for r in demand_rows) / 100

    # Today's payments in
    payments = await ms_get("/entity/paymentin", {
        "filter": f"moment>{dt_from}",
        "limit": 50,
    })
    payment_rows = payments.get("rows", [])
    payment_total = sum(r.get("sum", 0) for r in payment_rows) / 100

    # Critical raw stock (< 500 ml/units)
    raw_stock = await ms_get("/report/stock/all", {
        "filter": store_filter(WAREHOUSE_RAW),
        "limit": 500,
    })
    critical_raw = [
        {"name": r.get("name", ""), "stock": r.get("stock", 0), "uom": r.get("uom", {}).get("name", "")}
        for r in raw_stock.get("rows", [])
        if 0 < r.get("stock", 0) < 500
    ]

    # Zero FG stock
    fg_stock = await ms_get("/report/stock/all", {
        "filter": store_filter(WAREHOUSE_FG),
        "limit": 500,
    })
    zero_fg = [
        r.get("name", "")
        for r in fg_stock.get("rows", [])
        if r.get("stock", 0) <= 0
    ]

    result = {
        "date": today,
        "sales_today": {
            "count": len(demand_rows),
            "total_uah": round(demand_total, 2),
            "items": [
                {"agent": r.get("agent", {}).get("name", "?"), "sum_uah": round(r.get("sum", 0) / 100, 2)}
                for r in demand_rows[:10]
            ],
        },
        "payments_today": {
            "count": len(payment_rows),
            "total_uah": round(payment_total, 2),
        },
        "critical_raw_materials": critical_raw[:15],
        "zero_fg_stock": zero_fg[:20],
    }

    return json.dumps(result, ensure_ascii=False)


DIGEST_TOOL_MAP = {
    "get_daily_digest": tool_get_daily_digest,
}
