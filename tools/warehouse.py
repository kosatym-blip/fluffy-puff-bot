# -*- coding: utf-8 -*-
"""Инструменты: приёмки, перемещения, списания."""

import json
from datetime import datetime, timedelta

from ms_client import ms_get

WAREHOUSE_TOOLS = [
    {
        "name": "get_supplies",
        "description": "Приёмки (закупки от поставщиков) за период.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 90},
                "limit": {"type": "integer", "default": 50},
                "search": {"type": "string", "description": "Фильтр по поставщику"},
            },
        },
    },
    {
        "name": "get_moves",
        "description": "Перемещения между складами за период.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
                "limit": {"type": "integer", "default": 30},
            },
        },
    },
    {
        "name": "get_losses",
        "description": "Списания за период.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
                "limit": {"type": "integer", "default": 30},
            },
        },
    },
]


async def tool_get_supplies(days=90, limit=50, search=None) -> str:
    dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    params = {
        "filter": f"moment>{dt_from}",
        "order": "moment,desc",
        "limit": limit,
        "expand": "agent",
    }

    data = await ms_get("/entity/supply", params)
    rows = data.get("rows", [])

    if search:
        rows = [r for r in rows if search.lower() in r.get("agent", {}).get("name", "").lower()]

    total = sum(r.get("sum", 0) for r in rows) / 100
    result = {
        "period_days": days,
        "count": len(rows),
        "total_uah": round(total, 2),
        "items": [
            {
                "date": r.get("moment", "")[:10],
                "supplier": r.get("agent", {}).get("name", "?"),
                "sum_uah": round(r.get("sum", 0) / 100, 2),
                "positions": r.get("positions", {}).get("meta", {}).get("size", 0),
            }
            for r in rows[:20]
        ],
    }
    return json.dumps(result, ensure_ascii=False)


async def tool_get_moves(days=30, limit=30) -> str:
    dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    data = await ms_get("/entity/move", {
        "filter": f"moment>{dt_from}",
        "order": "moment,desc",
        "limit": limit,
        "expand": "sourceStore,targetStore",
    })
    rows = data.get("rows", [])

    result = {
        "period_days": days,
        "count": len(rows),
        "items": [
            {
                "date": r.get("moment", "")[:10],
                "name": r.get("name", ""),
                "from": r.get("sourceStore", {}).get("name", "?"),
                "to": r.get("targetStore", {}).get("name", "?"),
                "positions": r.get("positions", {}).get("meta", {}).get("size", 0),
            }
            for r in rows[:20]
        ],
    }
    return json.dumps(result, ensure_ascii=False)


async def tool_get_losses(days=30, limit=30) -> str:
    dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    data = await ms_get("/entity/loss", {
        "filter": f"moment>{dt_from}",
        "order": "moment,desc",
        "limit": limit,
        "expand": "store",
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
                "name": r.get("name", ""),
                "store": r.get("store", {}).get("name", "?"),
                "sum_uah": round(r.get("sum", 0) / 100, 2),
            }
            for r in rows[:20]
        ],
    }
    return json.dumps(result, ensure_ascii=False)


WAREHOUSE_TOOL_MAP = {
    "get_supplies": tool_get_supplies,
    "get_moves": tool_get_moves,
    "get_losses": tool_get_losses,
}
