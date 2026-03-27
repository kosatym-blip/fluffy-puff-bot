# -*- coding: utf-8 -*-
"""Инструменты: аудит складских операций."""

import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict

from ms_client import ms_get

logger = logging.getLogger(__name__)

AUDIT_TOOLS = [
    {
        "name": "find_negative_stock_shipments",
        "description": "Найти отгрузки, при которых товар отгружался при нулевом/отрицательном остатке на складе. Признак: себестоимость позиции = 0 (МойСклад ставит 0 когда товара нет на складе). Быстрый анализ — один запрос.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 14, "description": "За последние N дней"},
                "date_from": {"type": "string", "description": "Начало периода YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "Конец периода YYYY-MM-DD"},
            },
        },
    },
]


async def tool_find_negative_stock_shipments(days=14, date_from=None, date_to=None) -> str:
    """Находит отгрузки с нулевой себестоимостью — признак отгрузки при отсутствии товара.

    МойСклад ставит себестоимость = 0, когда товара нет на складе.
    Загружаем отгрузки за период с позициями, проверяем cost = 0.
    """
    if date_from:
        dt_from = f"{date_from} 00:00:00"
    else:
        dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    filters = [f"moment>{dt_from}"]
    if date_to:
        filters.append(f"moment<{date_to} 23:59:59")

    # Загружаем все отгрузки за период
    all_demands = []
    offset = 0
    while True:
        data = await ms_get("/entity/demand", {
            "filter": ";".join(filters),
            "order": "moment,desc",
            "limit": 100,
            "offset": offset,
            "expand": "agent",
        })
        rows = data.get("rows", [])
        all_demands.extend(rows)
        if len(rows) < 100:
            break
        offset += 100
        if offset > 500:
            break

    # Проверяем позиции каждой отгрузки на нулевую себестоимость
    zero_cost_events = []

    for demand in all_demands:
        demand_id = demand.get("id", "")
        demand_name = demand.get("name", "")
        demand_moment = demand.get("moment", "")[:10]
        agent_name = demand.get("agent", {}).get("name", "?")

        try:
            pos_data = await ms_get(f"/entity/demand/{demand_id}/positions", {
                "expand": "assortment",
                "limit": 100,
            })
            for pos in pos_data.get("rows", []):
                cost = pos.get("cost", 0)
                # cost = 0 при quantity > 0 — признак отгрузки без остатка
                if cost == 0 and pos.get("quantity", 0) > 0:
                    product_name = pos.get("assortment", {}).get("name", "?")
                    product_code = pos.get("assortment", {}).get("code", "")
                    zero_cost_events.append({
                        "date": demand_moment,
                        "doc": demand_name,
                        "agent": agent_name,
                        "product": product_name,
                        "code": product_code,
                        "quantity": pos.get("quantity", 0),
                        "price_uah": round(pos.get("price", 0) / 100, 2),
                    })
        except Exception as e:
            logger.warning(f"Failed to load positions for demand {demand_id}: {e}")

    if not zero_cost_events:
        return json.dumps({
            "period": f"{dt_from[:10]} — сегодня",
            "demands_checked": len(all_demands),
            "result": "Отгрузок с нулевой себестоимостью не найдено. Все товары были на складе.",
        }, ensure_ascii=False)

    # Группируем по продукту
    by_product = defaultdict(list)
    for ev in zero_cost_events:
        by_product[ev["product"]].append(ev)

    summary = []
    for product, events in sorted(by_product.items(), key=lambda x: len(x[1]), reverse=True):
        summary.append({
            "product": product,
            "code": events[0].get("code", ""),
            "times": len(events),
            "total_qty": sum(e["quantity"] for e in events),
            "shipments": [
                {"date": e["date"], "doc": e["doc"], "agent": e["agent"], "qty": e["quantity"]}
                for e in events[:5]
            ],
        })

    return json.dumps({
        "period": f"{dt_from[:10]} — сегодня",
        "demands_checked": len(all_demands),
        "products_with_zero_cost": len(by_product),
        "total_zero_cost_positions": len(zero_cost_events),
        "details": summary[:20],
    }, ensure_ascii=False)


AUDIT_TOOL_MAP = {
    "find_negative_stock_shipments": tool_find_negative_stock_shipments,
}
