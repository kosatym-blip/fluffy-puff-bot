# -*- coding: utf-8 -*-
"""Инструменты: заказы покупателей."""

import json
from datetime import datetime, timedelta

from ms_client import ms_get

ORDERS_TOOLS = [
    {
        "name": "get_orders",
        "description": "Заказы покупателей за период.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 7},
                "limit": {"type": "integer", "default": 30},
            },
        },
    },
    {
        "name": "get_purchase_orders",
        "description": "Заказы поставщикам за период.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
                "limit": {"type": "integer", "default": 30},
            },
        },
    },
    {
        "name": "get_order_positions",
        "description": "Позиции (товары) конкретного заказа или отгрузки — SKU-level детализация. Нужен UUID документа.",
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "UUID заказа или отгрузки"},
                "document_type": {
                    "type": "string",
                    "enum": ["customerorder", "demand", "supply", "purchaseorder"],
                    "default": "customerorder",
                },
            },
            "required": ["document_id"],
        },
    },
]


async def tool_get_orders(days=7, limit=30) -> str:
    dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    data = await ms_get("/entity/customerorder", {
        "filter": f"moment>{dt_from}",
        "order": "moment,desc",
        "limit": limit,
        "expand": "agent,state",
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
                "status": r.get("state", {}).get("name", ""),
            }
            for r in rows[:20]
        ],
    }
    return json.dumps(result, ensure_ascii=False)


async def tool_get_purchase_orders(days=30, limit=30) -> str:
    dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    data = await ms_get("/entity/purchaseorder", {
        "filter": f"moment>{dt_from}",
        "order": "moment,desc",
        "limit": limit,
        "expand": "agent,state",
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
                "supplier": r.get("agent", {}).get("name", "?"),
                "sum_uah": round(r.get("sum", 0) / 100, 2),
                "status": r.get("state", {}).get("name", ""),
            }
            for r in rows[:20]
        ],
    }
    return json.dumps(result, ensure_ascii=False)


async def tool_get_order_positions(document_id: str, document_type: str = "customerorder") -> str:
    data = await ms_get(f"/entity/{document_type}/{document_id}/positions", {
        "expand": "assortment",
        "limit": 100,
    })
    rows = data.get("rows", [])
    result = []
    for r in rows:
        result.append({
            "name": r.get("assortment", {}).get("name", "?"),
            "code": r.get("assortment", {}).get("code", ""),
            "quantity": r.get("quantity", 0),
            "price_uah": round(r.get("price", 0) / 100, 2),
            "sum_uah": round(r.get("quantity", 0) * r.get("price", 0) / 100, 2),
        })
    return json.dumps({"document_id": document_id, "type": document_type, "positions": result}, ensure_ascii=False)


ORDERS_TOOL_MAP = {
    "get_orders": tool_get_orders,
    "get_purchase_orders": tool_get_purchase_orders,
    "get_order_positions": tool_get_order_positions,
}
