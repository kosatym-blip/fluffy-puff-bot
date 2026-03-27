# -*- coding: utf-8 -*-
"""Инструменты: контрагенты (клиенты и поставщики)."""

import json
from datetime import datetime, timedelta

from ms_client import ms_get

COUNTERPARTY_TOOLS = [
    {
        "name": "get_counterparties",
        "description": "Список контрагентов (клиенты и поставщики). Поиск по имени, фильтр по тегу.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Поиск по имени контрагента"},
                "tag": {"type": "string", "description": "Фильтр: 'customer' или 'supplier'"},
                "limit": {"type": "integer", "default": 30},
            },
        },
    },
    {
        "name": "get_counterparty_detail",
        "description": "Профиль контрагента: контакты, баланс, история отгрузок. Нужен UUID или точное имя.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "UUID контрагента"},
                "name": {"type": "string", "description": "Точное или частичное имя (если нет UUID)"},
                "demand_days": {"type": "integer", "default": 90, "description": "За сколько дней историю отгрузок"},
            },
        },
    },
    {
        "name": "get_counterparty_report",
        "description": "Топ клиентов по выручке за период. Агрегирует из реальных отгрузок. Поддерживает точные даты (date_from/date_to в формате YYYY-MM-DD) или days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30, "description": "За последние N дней (если не указаны date_from/date_to)"},
                "date_from": {"type": "string", "description": "Начало периода YYYY-MM-DD (например 2026-03-01)"},
                "date_to": {"type": "string", "description": "Конец периода YYYY-MM-DD"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
]


async def tool_get_counterparties(search=None, tag=None, limit=30) -> str:
    params = {"limit": limit, "order": "name"}
    filters = []

    if search:
        filters.append(f"name~={search}")
    if tag == "customer":
        filters.append("companyType=legal")  # most customers are legal entities
    elif tag == "supplier":
        filters.append("companyType=legal")

    if filters:
        params["filter"] = ";".join(filters)

    # Use search param for fuzzy matching
    if search and not tag:
        params["search"] = search
        params.pop("filter", None)

    data = await ms_get("/entity/counterparty", params)
    rows = data.get("rows", [])

    result = []
    for r in rows:
        balance = 0
        accounts = r.get("accounts", {})
        if isinstance(accounts, dict):
            balance = accounts.get("sum", 0)

        result.append({
            "id": r.get("id", ""),
            "name": r.get("name", ""),
            "phone": r.get("phone", ""),
            "companyType": r.get("companyType", ""),
            "tags": [t.get("name", "") for t in r.get("tags", [])],
        })

    return json.dumps(result, ensure_ascii=False)


async def tool_get_counterparty_detail(id=None, name=None, demand_days=90) -> str:
    # Resolve UUID from name if needed
    cp_id = id
    if not cp_id and name:
        data = await ms_get("/entity/counterparty", {"search": name, "limit": 5})
        rows = data.get("rows", [])
        if not rows:
            return json.dumps({"error": f"Контрагент '{name}' не найден"}, ensure_ascii=False)
        cp_id = rows[0].get("id", "")

    if not cp_id:
        return json.dumps({"error": "Нужен id или name контрагента"}, ensure_ascii=False)

    # Fetch counterparty profile
    cp = await ms_get(f"/entity/counterparty/{cp_id}")

    # Fetch demand history
    dt_from = (datetime.now() - timedelta(days=demand_days)).strftime("%Y-%m-%d %H:%M:%S")
    agent_href = cp.get("meta", {}).get("href", "")
    demands = await ms_get("/entity/demand", {
        "filter": f"moment>{dt_from};agent={agent_href}",
        "order": "moment,desc",
        "limit": 50,
        "expand": "state",
    })

    demand_rows = demands.get("rows", [])
    total_sum = sum(r.get("sum", 0) for r in demand_rows) / 100

    result = {
        "id": cp.get("id", ""),
        "name": cp.get("name", ""),
        "phone": cp.get("phone", ""),
        "email": cp.get("email", ""),
        "companyType": cp.get("companyType", ""),
        "description": cp.get("description", ""),
        "demand_history": {
            "period_days": demand_days,
            "count": len(demand_rows),
            "total_uah": round(total_sum, 2),
            "items": [
                {
                    "date": r.get("moment", "")[:10],
                    "sum_uah": round(r.get("sum", 0) / 100, 2),
                    "status": r.get("state", {}).get("name", ""),
                }
                for r in demand_rows[:20]
            ],
        },
    }

    return json.dumps(result, ensure_ascii=False)


async def tool_get_counterparty_report(days=30, limit=20, date_from=None, date_to=None) -> str:
    """Топ клиентов по выручке. Агрегирует из отгрузок напрямую — надёжнее чем /report/counterparty."""
    if date_from:
        dt_from = f"{date_from} 00:00:00"
    else:
        dt_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    if date_to:
        dt_to = f"{date_to} 23:59:59"
    else:
        dt_to = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Fetch all demands for period (paginated)
    all_demands = []
    offset = 0
    while True:
        data = await ms_get("/entity/demand", {
            "filter": f"moment>{dt_from};moment<{dt_to}",
            "expand": "agent",
            "limit": 100,
            "offset": offset,
        })
        rows = data.get("rows", [])
        all_demands.extend(rows)
        if len(rows) < 100:
            break
        offset += 100
        if offset > 1000:
            break

    # Aggregate by counterparty
    by_agent: dict[str, dict] = {}
    for r in all_demands:
        agent_name = r.get("agent", {}).get("name", "?")
        if agent_name not in by_agent:
            by_agent[agent_name] = {"name": agent_name, "sum": 0, "count": 0}
        by_agent[agent_name]["sum"] += r.get("sum", 0)
        by_agent[agent_name]["count"] += 1

    # Sort by sum descending
    sorted_agents = sorted(by_agent.values(), key=lambda x: x["sum"], reverse=True)

    result = [
        {
            "name": a["name"],
            "demand_sum_uah": round(a["sum"] / 100, 2),
            "demand_count": a["count"],
        }
        for a in sorted_agents[:limit]
    ]

    total = sum(a["sum"] for a in sorted_agents) / 100

    return json.dumps({
        "period": f"{dt_from[:10]} — {dt_to[:10]}",
        "total_demands": len(all_demands),
        "total_uah": round(total, 2),
        "top_counterparties": result,
    }, ensure_ascii=False)


COUNTERPARTY_TOOL_MAP = {
    "get_counterparties": tool_get_counterparties,
    "get_counterparty_detail": tool_get_counterparty_detail,
    "get_counterparty_report": tool_get_counterparty_report,
}
