# -*- coding: utf-8 -*-
"""Инструменты: финансы (ДДС)."""

import json
from datetime import datetime, timedelta

from ms_client import ms_get

FINANCE_TOOLS = [
    {
        "name": "get_cashflow",
        "description": "Движение денег (DDS) — входящие и исходящие платежи за период.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
            },
        },
    },
    {
        "name": "get_dashboard",
        "description": "Сводный дашборд МойСклад: продажи, заказы, деньги за сегодня/неделю/месяц.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_profit_report",
        "description": "Рентабельность по товарам за период. Топ-N по прибыли/выручке.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
                "top_n": {"type": "integer", "default": 15},
                "sort_by": {"type": "string", "enum": ["profit", "revenue", "quantity"], "default": "profit"},
            },
        },
    },
]


async def tool_get_cashflow(days=30) -> str:
    dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    params = {"filter": f"moment>{dt_from}", "limit": 200}
    inc = await ms_get("/entity/paymentin", params)
    out = await ms_get("/entity/paymentout", params)
    income = sum(r.get("sum", 0) for r in inc.get("rows", [])) / 100
    outcome = sum(r.get("sum", 0) for r in out.get("rows", [])) / 100
    return json.dumps({
        "days": days,
        "income_uah": round(income, 2),
        "outcome_uah": round(outcome, 2),
        "balance_uah": round(income - outcome, 2),
    }, ensure_ascii=False)


async def tool_get_dashboard() -> str:
    data = await ms_get("/report/dashboard")
    return json.dumps(data, ensure_ascii=False, default=str)


async def tool_get_profit_report(days=30, top_n=15, sort_by="profit") -> str:
    dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    dt_to = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Fetch with pagination (server-side sort broken, must sort locally)
    all_rows = []
    offset = 0
    while True:
        data = await ms_get("/report/profit/byproduct", {
            "momentFrom": dt_from,
            "momentTo": dt_to,
            "limit": 100,
            "offset": offset,
        })
        rows = data.get("rows", [])
        all_rows.extend(rows)
        if len(rows) < 100:
            break
        offset += 100
        if offset > 500:  # safety limit
            break

    # Sort locally
    sort_key_map = {
        "profit": "profit",
        "revenue": "sellSum",
        "quantity": "sellQuantity",
    }
    key = sort_key_map.get(sort_by, "profit")
    all_rows.sort(key=lambda r: r.get(key, 0), reverse=True)

    result = []
    for r in all_rows[:top_n]:
        result.append({
            "name": r.get("assortment", {}).get("name", "?"),
            "revenue_uah": round(r.get("sellSum", 0) / 100, 2),
            "cost_uah": round(r.get("sellCostSum", 0) / 100, 2),
            "profit_uah": round(r.get("profit", 0) / 100, 2),
            "margin_pct": round(r.get("margin", 0), 1),
            "quantity": r.get("sellQuantity", 0),
        })

    return json.dumps({"days": days, "sort_by": sort_by, "products": result}, ensure_ascii=False)


FINANCE_TOOL_MAP = {
    "get_cashflow": tool_get_cashflow,
    "get_dashboard": tool_get_dashboard,
    "get_profit_report": tool_get_profit_report,
}
