# -*- coding: utf-8 -*-
"""Инструменты: техкарты, расчёт закупок, история производства."""

import json
from datetime import datetime, timedelta

from ms_client import ms_get
from config import WAREHOUSE_RAW, store_filter

PRODUCTION_TOOLS = [
    {
        "name": "get_processing_plans",
        "description": "Техкарты (BOM) — состав материалов для производства конкретного продукта.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Название продукта для поиска техкарты"},
            },
        },
    },
    {
        "name": "get_processing_history",
        "description": "История производственных операций за период (старый формат /entity/processing).",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30},
                "limit": {"type": "integer", "default": 50},
            },
        },
    },
    {
        "name": "get_stage_completions",
        "description": "Выполнения этапов производства за период. Используй для ответов на вопросы 'что произведено', 'производство за день/неделю'. Это основной инструмент учёта производства.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 7, "description": "За сколько дней смотреть"},
                "limit": {"type": "integer", "default": 100},
            },
        },
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
                    "additionalProperties": {"type": "integer"},
                },
            },
            "required": ["production_plan"],
        },
    },
]


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
                "quantity": m.get("quantity", 0),
            })
        result.append({"name": r.get("name", ""), "materials": materials})
    return json.dumps(result, ensure_ascii=False)


async def tool_calculate_purchase_needs(production_plan: dict) -> str:
    # Загружаем техкарты
    data = await ms_get("/entity/processingplan", {"limit": 100, "expand": "materials.assortment"})
    plans = data.get("rows", [])
    # Загружаем остатки сырья
    stock_data = await ms_get("/report/stock/all", {"limit": 500, "filter": store_filter(WAREHOUSE_RAW)})
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
            mat_qty = m.get("quantity", 0) * qty
            needs[mat_name] = needs.get(mat_name, 0) + mat_qty

    to_order = {}
    for mat, needed in needs.items():
        current = stock.get(mat, 0)
        if needed > current:
            to_order[mat] = round(needed - current, 1)

    return json.dumps({
        "production_plan": production_plan,
        "to_order": to_order,
        "not_found_plans": not_found,
    }, ensure_ascii=False)


async def tool_get_stage_completions(days=7, limit=100) -> str:
    dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    data = await ms_get("/entity/productionstagecompletion", {
        "filter": f"moment>{dt_from}",
        "order": "moment,desc",
        "limit": limit,
        "expand": "processingStage,processingOrder,products.assortment",
    })
    rows = data.get("rows", [])

    # Aggregate totals by product name from output products
    totals: dict[str, float] = {}
    items = []
    for r in rows:
        moment = r.get("moment", "")
        stage = r.get("processingStage", {}).get("name", "?")
        order_name = r.get("processingOrder", {}).get("name", "?")
        products = r.get("products", {}).get("rows", [])

        if products:
            for p in products:
                product_name = p.get("assortment", {}).get("name", "?")
                qty = p.get("quantity", 0)
                totals[product_name] = totals.get(product_name, 0) + qty
                items.append({
                    "date": moment[:10],
                    "time": moment[11:16],
                    "stage": stage,
                    "order": order_name,
                    "product": product_name,
                    "quantity": qty,
                })
        else:
            # Fallback: top-level quantity + order name
            qty = r.get("quantity", 0)
            totals[order_name] = totals.get(order_name, 0) + qty
            items.append({
                "date": moment[:10],
                "time": moment[11:16],
                "stage": stage,
                "order": order_name,
                "product": order_name,
                "quantity": qty,
            })

    result = {
        "period_days": days,
        "completions_count": len(rows),
        "totals_by_product": [
            {"name": k, "quantity": v} for k, v in sorted(totals.items(), key=lambda x: -x[1])
        ],
        "items": items,
    }
    return json.dumps(result, ensure_ascii=False)


async def tool_get_processing_history(days=30, limit=50) -> str:
    dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    data = await ms_get("/entity/processing", {
        "filter": f"moment>{dt_from}",
        "order": "moment,desc",
        "limit": limit,
        "expand": "processingPlan",
    })
    rows = data.get("rows", [])

    result = {
        "period_days": days,
        "count": len(rows),
        "items": [
            {
                "date": r.get("moment", "")[:10],
                "plan_name": r.get("processingPlan", {}).get("name", "?"),
                "quantity": r.get("quantity", 0),
                "name": r.get("name", ""),
            }
            for r in rows[:30]
        ],
    }
    return json.dumps(result, ensure_ascii=False)


PRODUCTION_TOOL_MAP = {
    "get_processing_plans": tool_get_processing_plans,
    "get_processing_history": tool_get_processing_history,
    "get_stage_completions": tool_get_stage_completions,
    "calculate_purchase_needs": tool_calculate_purchase_needs,
}
