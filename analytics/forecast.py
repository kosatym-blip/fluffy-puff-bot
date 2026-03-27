# -*- coding: utf-8 -*-
"""DemandForecaster — пересчёт паттернов спроса и клиентов.

Запускается еженедельно (пн 06:00). Результат сохраняется в кэш.
"""

import logging
from datetime import datetime, timedelta
from collections import defaultdict

from ms_client import ms_get
from config import WAREHOUSE_FG, WAREHOUSE_RAW, store_filter, classify_by_folder
from analytics.cache import write_cache

logger = logging.getLogger(__name__)

ANALYSIS_PERIOD_DAYS = 90


async def rebuild_analytics_cache():
    """Полный пересчёт аналитического кэша. ~3-5 мин, запускается cron-ом."""
    logger.info("=== Начинаю пересчёт аналитического кэша ===")

    dt_from = (datetime.now() - timedelta(days=ANALYSIS_PERIOD_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    dt_30d = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")

    # ─── 1. Загружаем все отгрузки за 90 дней с позициями ─────────────────
    logger.info("Загружаю отгрузки...")
    all_demands = []
    offset = 0
    while True:
        data = await ms_get("/entity/demand", {
            "filter": f"moment>{dt_from}",
            "order": "moment,asc",
            "limit": 100,
            "offset": offset,
            "expand": "agent",
        })
        rows = data.get("rows", [])
        all_demands.extend(rows)
        if len(rows) < 100:
            break
        offset += 100
        if offset > 1000:
            break

    logger.info(f"Загружено {len(all_demands)} отгрузок")

    # Загружаем позиции для каждой отгрузки
    demand_positions = []  # (moment, agent_name, agent_id, product_name, product_code, qty, sum)
    for i, demand in enumerate(all_demands):
        demand_id = demand.get("id", "")
        moment = demand.get("moment", "")
        agent_name = demand.get("agent", {}).get("name", "?")
        agent_id = demand.get("agent", {}).get("id", "")

        try:
            pos_data = await ms_get(f"/entity/demand/{demand_id}/positions", {
                "expand": "assortment",
                "limit": 100,
            })
            for pos in pos_data.get("rows", []):
                assortment = pos.get("assortment", {})
                folder = assortment.get("productFolder", {})
                folder_path = (
                    (folder.get("pathName", "") + "/" + folder.get("name", "")).strip("/")
                    if folder else ""
                )
                demand_positions.append({
                    "moment": moment,
                    "agent_name": agent_name,
                    "agent_id": agent_id,
                    "product_name": assortment.get("name", "?"),
                    "product_code": assortment.get("code", ""),
                    "product_type": classify_by_folder(folder_path),
                    "folder": folder_path,
                    "qty": pos.get("quantity", 0),
                    "sum": pos.get("price", 0) * pos.get("quantity", 0),
                })
        except Exception as e:
            logger.warning(f"Demand {demand_id} positions error: {e}")

        if (i + 1) % 50 == 0:
            logger.info(f"  обработано {i + 1}/{len(all_demands)} отгрузок")

    logger.info(f"Загружено {len(demand_positions)} позиций отгрузок")

    # ─── 2. Агрегация по SKU ─────────────────────────────────────────────
    sku_data = defaultdict(lambda: {
        "total_90d": 0, "total_30d": 0, "first_30d": 0,
        "name": "", "code": "", "product_type": "other", "folder": "",
    })

    for dp in demand_positions:
        key = dp["product_name"]
        sku_data[key]["name"] = dp["product_name"]
        sku_data[key]["code"] = dp["product_code"]
        sku_data[key]["product_type"] = dp.get("product_type", "other")
        sku_data[key]["folder"] = dp.get("folder", "")
        sku_data[key]["total_90d"] += dp["qty"]

        moment_date = dp["moment"][:10]
        if moment_date >= dt_30d[:10]:
            sku_data[key]["total_30d"] += dp["qty"]

        first_30d_end = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        if moment_date <= first_30d_end:
            sku_data[key]["first_30d"] += dp["qty"]

    sku_demand = {}
    for name, sd in sku_data.items():
        avg_daily = sd["total_90d"] / ANALYSIS_PERIOD_DAYS if sd["total_90d"] > 0 else 0
        # Тренд: сравниваем последние 30д vs первые 30д
        if sd["first_30d"] > 0:
            ratio = sd["total_30d"] / sd["first_30d"]
            if ratio > 1.2:
                trend = "growing"
            elif ratio < 0.8:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "new" if sd["total_30d"] > 0 else "stable"

        sku_demand[name] = {
            "name": name,
            "code": sd["code"],
            "product_type": sd["product_type"],
            "folder": sd["folder"],
            "avg_daily_demand": round(avg_daily, 2),
            "total_sold_90d": sd["total_90d"],
            "total_sold_30d": sd["total_30d"],
            "trend": trend,
        }

    # ─── 3. Агрегация по клиентам ────────────────────────────────────────
    client_orders = defaultdict(list)  # agent_id → list of {moment, sum, skus}

    for demand in all_demands:
        agent_id = demand.get("agent", {}).get("id", "")
        agent_name = demand.get("agent", {}).get("name", "?")
        moment = demand.get("moment", "")
        total_sum = demand.get("sum", 0)

        client_orders[agent_id].append({
            "name": agent_name,
            "moment": moment,
            "sum": total_sum,
        })

    # SKU по клиентам
    client_skus = defaultdict(lambda: defaultdict(int))  # agent_id → {sku: total_qty}
    for dp in demand_positions:
        client_skus[dp["agent_id"]][dp["product_name"]] += dp["qty"]

    client_patterns = {}
    for agent_id, orders in client_orders.items():
        if not orders:
            continue
        name = orders[0]["name"]
        orders_sorted = sorted(orders, key=lambda o: o["moment"])
        total_sum = sum(o["sum"] for o in orders) / 100

        # Средний интервал
        intervals = []
        for i in range(1, len(orders_sorted)):
            d1 = datetime.fromisoformat(orders_sorted[i - 1]["moment"].replace("Z", "+00:00").split("+")[0][:19])
            d2 = datetime.fromisoformat(orders_sorted[i]["moment"].replace("Z", "+00:00").split("+")[0][:19])
            intervals.append((d2 - d1).days)
        avg_interval = round(sum(intervals) / len(intervals), 1) if intervals else 0

        # Последний заказ и прогноз
        last_order = orders_sorted[-1]["moment"][:10]
        predicted_next = ""
        if avg_interval > 0:
            last_dt = datetime.strptime(last_order, "%Y-%m-%d")
            predicted_next = (last_dt + timedelta(days=avg_interval)).strftime("%Y-%m-%d")

        # Выручка за 30д vs предыдущие 30д
        revenue_30d = sum(o["sum"] for o in orders if o["moment"][:10] >= dt_30d[:10]) / 100
        prev_30d_start = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        revenue_prev_30d = sum(
            o["sum"] for o in orders
            if prev_30d_start <= o["moment"][:10] < dt_30d[:10]
        ) / 100

        if revenue_prev_30d > 0:
            rev_ratio = revenue_30d / revenue_prev_30d
            if rev_ratio > 1.2:
                rev_trend = "growing"
            elif rev_ratio < 0.8:
                rev_trend = "declining"
            else:
                rev_trend = "stable"
        else:
            rev_trend = "new" if revenue_30d > 0 else "inactive"

        # Топ SKU
        skus = client_skus.get(agent_id, {})
        top_skus = sorted(skus.items(), key=lambda x: x[1], reverse=True)[:10]

        # Статус активности
        days_since_last = (datetime.now() - datetime.strptime(last_order, "%Y-%m-%d")).days
        if days_since_last > avg_interval * 2 and avg_interval > 0:
            activity = "sleeping"
        elif days_since_last > 30:
            activity = "inactive"
        else:
            activity = "active"

        client_patterns[agent_id] = {
            "name": name,
            "order_count_90d": len(orders),
            "avg_order_value_uah": round(total_sum / len(orders), 2) if orders else 0,
            "avg_interval_days": avg_interval,
            "top_skus": [{"name": s[0], "qty": s[1]} for s in top_skus],
            "all_sku_names": list(skus.keys()),
            "last_order_date": last_order,
            "predicted_next_order": predicted_next,
            "revenue_30d_uah": round(revenue_30d, 2),
            "revenue_prev_30d_uah": round(revenue_prev_30d, 2),
            "revenue_trend": rev_trend,
            "activity": activity,
            "days_since_last_order": days_since_last,
        }

    # ─── 4. Текущие остатки ГП ───────────────────────────────────────────
    logger.info("Загружаю остатки ГП...")
    fg_stock = {}
    offset = 0
    while True:
        data = await ms_get("/report/stock/all", {
            "filter": store_filter(WAREHOUSE_FG),
            "limit": 100,
            "offset": offset,
        })
        for r in data.get("rows", []):
            fg_stock[r.get("name", "")] = r.get("stock", 0)
        if len(data.get("rows", [])) < 100:
            break
        offset += 100

    # Добавляем days_of_supply в sku_demand
    for name, sd in sku_demand.items():
        stock = fg_stock.get(name, 0)
        if sd["avg_daily_demand"] > 0:
            sd["current_stock"] = stock
            sd["days_of_supply"] = round(stock / sd["avg_daily_demand"], 1)
        else:
            sd["current_stock"] = stock
            sd["days_of_supply"] = 999 if stock > 0 else 0

    # ─── 5. Summary ──────────────────────────────────────────────────────
    active_clients = [c for c in client_patterns.values() if c["activity"] == "active"]
    sleeping_clients = [c for c in client_patterns.values() if c["activity"] == "sleeping"]
    declining_clients = [c for c in client_patterns.values() if c["revenue_trend"] == "declining"]
    low_stock_skus = [s for s in sku_demand.values() if s.get("days_of_supply", 999) < 14]

    total_revenue_30d = sum(c["revenue_30d_uah"] for c in client_patterns.values())

    summary = {
        "active_clients_30d": len(active_clients),
        "sleeping_clients": len(sleeping_clients),
        "declining_clients": len(declining_clients),
        "total_skus_sold_90d": len(sku_demand),
        "avg_daily_revenue_uah": round(total_revenue_30d / 30, 2),
        "fg_skus_below_14d": len(low_stock_skus),
    }

    # ─── 6. Сохраняем ────────────────────────────────────────────────────
    cache_data = {
        "period_analyzed_days": ANALYSIS_PERIOD_DAYS,
        "demands_analyzed": len(all_demands),
        "positions_analyzed": len(demand_positions),
        "sku_demand": sku_demand,
        "client_patterns": client_patterns,
        "summary": summary,
    }

    write_cache(cache_data)
    logger.info(f"=== Кэш пересчитан: {len(sku_demand)} SKU, {len(client_patterns)} клиентов ===")
    return cache_data
