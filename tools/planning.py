# -*- coding: utf-8 -*-
"""Инструменты планирования: прогноз спроса, аналитика клиентов, план производства/закупок."""

import json
import logging

from analytics.cache import read_cache

logger = logging.getLogger(__name__)

PLANNING_TOOLS = [
    {
        "name": "get_demand_forecast",
        "description": "Прогноз спроса по SKU (из кэша, обновляется еженедельно): avg daily demand, trend, days of supply. Секции: sku (все SKU), low_stock (дефицитные < 14 дней), summary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string", "enum": ["sku", "low_stock", "summary", "all"], "default": "summary"},
                "search": {"type": "string", "description": "Фильтр по названию SKU"},
                "top_n": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "get_client_analytics",
        "description": "Аналитика клиентов (из кэша): паттерны заказов, тренды, спящие клиенты, upsell. Секции: active, sleeping, declining, debtors, upsell.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "enum": ["active", "sleeping", "declining", "top", "upsell", "all"],
                    "default": "top",
                    "description": "active=активные, sleeping=давно не заказывали, declining=падение выручки, top=топ по выручке, upsell=что предложить клиенту",
                },
                "client_name": {"type": "string", "description": "Поиск конкретного клиента по имени"},
                "top_n": {"type": "integer", "default": 15},
            },
        },
    },
    {
        "name": "get_production_plan",
        "description": "Рекомендуемый план производства на период. Считает: прогноз спроса × дней — текущий остаток = нужно произвести. Учитывает мощности.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 7, "description": "На сколько дней планировать"},
            },
        },
    },
    {
        "name": "rebuild_cache",
        "description": "Принудительно пересчитать кэш аналитики (обычно обновляется автоматически раз в неделю). Занимает 2-3 минуты.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _get_cache_or_error():
    """Читает кэш, возвращает (data, None) или (None, error_str)."""
    cache = read_cache()
    if not cache:
        return None, json.dumps({
            "error": "Кэш аналитики пуст или устарел. Вызови rebuild_cache для пересчёта (займёт 2-3 мин).",
        }, ensure_ascii=False)
    return cache, None


async def tool_get_demand_forecast(section="summary", search=None, top_n=20) -> str:
    cache, err = _get_cache_or_error()
    if err:
        return err

    sku_demand = cache.get("sku_demand", {})
    summary = cache.get("summary", {})
    generated = cache.get("generated_at", "?")

    if search:
        sku_demand = {k: v for k, v in sku_demand.items() if search.lower() in k.lower()}

    if section == "summary":
        return json.dumps({"generated_at": generated, "summary": summary}, ensure_ascii=False)

    if section == "low_stock":
        low = {k: v for k, v in sku_demand.items() if v.get("days_of_supply", 999) < 14}
        sorted_low = sorted(low.values(), key=lambda x: x.get("days_of_supply", 999))
        return json.dumps({
            "generated_at": generated,
            "low_stock_skus": sorted_low[:top_n],
            "total": len(sorted_low),
        }, ensure_ascii=False)

    if section == "sku":
        sorted_skus = sorted(sku_demand.values(), key=lambda x: x.get("total_sold_90d", 0), reverse=True)
        return json.dumps({
            "generated_at": generated,
            "skus": sorted_skus[:top_n],
            "total": len(sorted_skus),
        }, ensure_ascii=False)

    # all
    return json.dumps({
        "generated_at": generated,
        "summary": summary,
        "top_skus": sorted(sku_demand.values(), key=lambda x: x.get("total_sold_90d", 0), reverse=True)[:top_n],
        "low_stock": sorted(
            [v for v in sku_demand.values() if v.get("days_of_supply", 999) < 14],
            key=lambda x: x.get("days_of_supply", 999),
        )[:top_n],
    }, ensure_ascii=False)


async def tool_get_client_analytics(section="top", client_name=None, top_n=15) -> str:
    cache, err = _get_cache_or_error()
    if err:
        return err

    clients = cache.get("client_patterns", {})
    generated = cache.get("generated_at", "?")

    if client_name:
        matched = {k: v for k, v in clients.items() if client_name.lower() in v.get("name", "").lower()}
        return json.dumps({
            "generated_at": generated,
            "search": client_name,
            "clients": list(matched.values())[:top_n],
        }, ensure_ascii=False)

    if section == "sleeping":
        sleeping = [c for c in clients.values() if c.get("activity") == "sleeping"]
        sleeping.sort(key=lambda x: x.get("days_since_last_order", 0), reverse=True)
        return json.dumps({
            "generated_at": generated,
            "sleeping_clients": sleeping[:top_n],
            "total": len(sleeping),
        }, ensure_ascii=False)

    if section == "declining":
        declining = [c for c in clients.values() if c.get("revenue_trend") == "declining"]
        declining.sort(key=lambda x: x.get("revenue_prev_30d_uah", 0), reverse=True)
        return json.dumps({
            "generated_at": generated,
            "declining_clients": declining[:top_n],
            "total": len(declining),
        }, ensure_ascii=False)

    if section == "active":
        active = [c for c in clients.values() if c.get("activity") == "active"]
        active.sort(key=lambda x: x.get("revenue_30d_uah", 0), reverse=True)
        return json.dumps({
            "generated_at": generated,
            "active_clients": active[:top_n],
            "total": len(active),
        }, ensure_ascii=False)

    if section == "upsell":
        # Upsell: для конкретного клиента — что он НЕ покупает из ассортимента
        if not client_name:
            return json.dumps({"error": "Для upsell нужно указать client_name"}, ensure_ascii=False)

        matched = [c for c in clients.values() if client_name.lower() in c.get("name", "").lower()]
        if not matched:
            return json.dumps({"error": f"Клиент '{client_name}' не найден"}, ensure_ascii=False)

        client = matched[0]
        client_skus = set(client.get("all_sku_names", []))

        # Все SKU из кэша, которые продаются (avg > 0)
        sku_demand = cache.get("sku_demand", {})
        popular_skus = {
            name: s for name, s in sku_demand.items()
            if s.get("avg_daily_demand", 0) > 0.5  # минимум 0.5 шт/день
        }

        # Определяем линейки клиента
        client_lines = set()
        for sku_name in client_skus:
            upper = sku_name.upper()
            if "EXTRA" in upper or "SIGMA" in upper:
                client_lines.add("Alpha/Sigma 12ml")
            elif any(x in upper for x in ["ORGANIC", "30 МЛ", "18 МЛ"]):
                client_lines.add("Organic 18ml")
            if "ГЛИЦЕРИН" in upper or "ГЛІЦЕРИН" in upper:
                client_lines.add("Глицерин")
            if "ДОБАВКА" in upper or "НІКОТИН" in upper:
                client_lines.add("Никобустер")

        # SKU которые клиент НЕ покупает
        missing = []
        for name, s in popular_skus.items():
            if name not in client_skus:
                missing.append({
                    "name": name,
                    "avg_daily": s["avg_daily_demand"],
                    "total_sold_90d": s["total_sold_90d"],
                })

        missing.sort(key=lambda x: x["total_sold_90d"], reverse=True)

        return json.dumps({
            "generated_at": generated,
            "client": client["name"],
            "client_sku_count": len(client_skus),
            "client_lines": list(client_lines),
            "recommended_to_offer": missing[:15],
        }, ensure_ascii=False)

    # top — по выручке за 30д
    top = sorted(clients.values(), key=lambda x: x.get("revenue_30d_uah", 0), reverse=True)
    return json.dumps({
        "generated_at": generated,
        "top_clients": top[:top_n],
        "total": len(top),
    }, ensure_ascii=False)


async def tool_get_production_plan(days=7) -> str:
    """
    Формирует план производства с учётом бизнес-правил:
    - Мощности: ~1200 ароматизаторов/день, ~1000 глицерина/день, ~1500 добавок/день
    - Ароматизаторы 12мл: кратно 100, мин 200, макс 600 одного вида за день
    - Ароматизаторы 24мл и 6мл: можно делать в меньших партиях, из того же WIP что и 12мл
    - Ice и не-Ice одного вкуса — производить парами
    - Двухэтапное производство: WIP (замес) → ГП (разлив и фасовка)
    """
    cache, err = _get_cache_or_error()
    if err:
        return err

    from ms_client import ms_get
    from config import WAREHOUSE_WIP, store_filter

    sku_demand = cache.get("sku_demand", {})
    generated = cache.get("generated_at", "?")

    # ─── 1. Остатки ГП — из кэша (обновляется еженедельно, достаточно точно)
    # WIP загружаем свежие — нужны актуальные данные о замешанных полуфабрикатах
    fg_stock = {name: sd.get("current_stock", 0) for name, sd in sku_demand.items()}

    wip_stock = {}
    offset = 0
    while offset <= 300:
        data = await ms_get("/report/stock/all", {
            "filter": store_filter(WAREHOUSE_WIP),
            "limit": 100,
            "offset": offset,
        })
        for r in data.get("rows", []):
            wip_stock[r.get("name", "")] = r.get("stock", 0)
        if len(data.get("rows", [])) < 100:
            break
        offset += 100

    # ─── 2. Дефицит по SKU ───────────────────────────────────────────────
    deficits = []
    for name, sd in sku_demand.items():
        avg_daily = sd.get("avg_daily_demand", 0)
        if avg_daily <= 0:
            continue

        needed = avg_daily * days
        current = fg_stock.get(name, 0)
        deficit = needed - current

        if deficit > 0:
            deficits.append({
                "product": name,
                "code": sd.get("code", ""),
                "avg_daily_demand": avg_daily,
                "demand_for_period": round(needed),
                "current_stock": max(current, 0),
                "deficit": round(deficit),
                "days_of_supply": round(current / avg_daily, 1) if avg_daily > 0 else 0,
            })

    deficits.sort(key=lambda x: x["days_of_supply"])

    # ─── 3. Тип каждого дефицитного SKU — из кэша (папка МойСклад) ──────
    # Добавляем product_type из кэша в каждый дефицит
    for item in deficits:
        item["product_type"] = sku_demand.get(item["product"], {}).get("product_type", "other")

    # ─── 4. Группировка ароматизаторов Ice/не-Ice парами ─────────────────
    import re

    def base_flavor(name: str) -> str:
        """Базовый вкус без ICE, суффиксов объёма и линейки."""
        n = re.sub(r"\b(ICE\*?)\b", "", name, flags=re.IGNORECASE)
        n = re.sub(r"\b(\d+\s?ML|EXTRA|SIGMA|ALPHA|BOX)\b", "", n, flags=re.IGNORECASE)
        n = re.sub(r"\b(24|18|12|6)\s?МЛ\b", "", n, flags=re.IGNORECASE)
        return n.strip().upper()

    AROMA_TYPES = {"aroma_12_active", "aroma_12_legacy", "aroma_18", "aroma_24", "aroma_6"}

    from collections import defaultdict
    flavor_groups = defaultdict(list)
    for item in deficits:
        if item["product_type"] in AROMA_TYPES:
            flavor_groups[base_flavor(item["product"])].append(item)

    # ─── 5. Применяем мощностные ограничения ─────────────────────────────
    DAILY_CAPACITY = {
        "aroma_12_active": 1200,  # 12мл Alpha + Sigma
        "aroma_18":        600,   # 18мл (свой WIP)
        "aroma_24":        400,   # из WIP 12мл
        "aroma_6":         300,   # из WIP 12мл
        "glycerin":        1000,
        "nicobuster":      1500,
        "nicobuster_outsource": 0,  # аутсорс — не планируем своё производство
    }
    AROMA_12_MIN_BATCH = 200
    AROMA_12_MAX_BATCH = 600

    plan_items = []
    day_load = {k: 0 for k in DAILY_CAPACITY}

    processed_aroma = set()
    for flavor, items in sorted(flavor_groups.items(), key=lambda x: min(i["days_of_supply"] for i in x[1])):
        for item in items:
            ptype = item["product_type"]
            if item["product"] in processed_aroma:
                continue

            # Не планируем производство устаревших линеек
            if ptype == "aroma_12_legacy":
                plan_items.append({
                    **item, "to_produce": 0, "type": ptype,
                    "fits_today": False, "wip_available": 0,
                    "note": "линейка выведена — допродажа остатков",
                })
                processed_aroma.add(item["product"])
                continue

            qty = item["deficit"]
            if ptype == "aroma_12_active":
                qty = max(AROMA_12_MIN_BATCH, round(qty / 100) * 100)
                qty = min(qty, AROMA_12_MAX_BATCH)
            elif ptype in ("aroma_24", "aroma_6", "aroma_18"):
                qty = max(50, round(qty / 50) * 50)

            cap = DAILY_CAPACITY.get(ptype, 9999)
            remaining_capacity = cap - day_load.get(ptype, 0)
            if remaining_capacity <= 0:
                plan_items.append({**item, "to_produce": qty, "type": ptype,
                                   "fits_today": False, "wip_available": 0,
                                   "note": "превышена дневная мощность"})
                processed_aroma.add(item["product"])
                continue

            to_produce = min(qty, remaining_capacity)
            day_load[ptype] = day_load.get(ptype, 0) + to_produce

            wip_available = wip_stock.get(item["product"], 0)
            plan_items.append({
                **item,
                "to_produce": to_produce,
                "type": ptype,
                "fits_today": True,
                "wip_available": wip_available,
                "note": (
                    "из WIP (замес уже есть)" if wip_available >= to_produce
                    else "нужен замес + разлив" if wip_available == 0
                    else f"частично из WIP ({wip_available:.0f} шт), замес {to_produce - wip_available:.0f} шт"
                ),
            })
            processed_aroma.add(item["product"])

    # Глицерин и добавки
    for item in deficits:
        ptype = item["product_type"]
        if ptype not in ("glycerin", "nicobuster"):
            continue

        qty = item["deficit"]
        remaining = DAILY_CAPACITY[ptype] - day_load.get(ptype, 0)
        to_produce = min(qty, remaining)
        day_load[ptype] += to_produce

        plan_items.append({
            **item,
            "to_produce": to_produce,
            "type": ptype,
            "fits_today": remaining > 0,
            "wip_available": 0,
            "note": "" if remaining > 0 else "превышена дневная мощность",
        })

    plan_items.sort(key=lambda x: (not x["fits_today"], x["days_of_supply"]))

    # ─── 6. Сводка по нагрузке ───────────────────────────────────────────
    capacity_summary = {
        cat: {"used": day_load.get(cat, 0), "capacity": cap, "pct": round(day_load.get(cat, 0) / cap * 100)}
        for cat, cap in DAILY_CAPACITY.items()
        if day_load.get(cat, 0) > 0
    }

    return json.dumps({
        "forecast_date": generated,
        "plan_days": days,
        "items_to_produce": len(plan_items),
        "capacity_summary": capacity_summary,
        "plan": plan_items[:35],
        "note": (
            "Двухэтапное производство ароматизаторов: "
            "1) замес (WIP) → 2) разлив и фасовка (ГП). "
            "24мл и 6мл используют тот же WIP что и 12мл."
        ),
    }, ensure_ascii=False)


async def tool_rebuild_cache() -> str:
    from analytics.forecast import rebuild_analytics_cache
    try:
        data = await rebuild_analytics_cache()
        return json.dumps({
            "status": "ok",
            "skus_analyzed": len(data.get("sku_demand", {})),
            "clients_analyzed": len(data.get("client_patterns", {})),
            "demands_analyzed": data.get("demands_analyzed", 0),
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Cache rebuild failed: {e}")
        return json.dumps({"error": str(e)})


PLANNING_TOOL_MAP = {
    "get_demand_forecast": tool_get_demand_forecast,
    "get_client_analytics": tool_get_client_analytics,
    "get_production_plan": tool_get_production_plan,
    "rebuild_cache": tool_rebuild_cache,
}
