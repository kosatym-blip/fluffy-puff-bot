# -*- coding: utf-8 -*-
"""AlertChecker — проверки: дефициты ГП/сырья, спящие клиенты, задолженности."""

import logging
from datetime import datetime, timedelta

from ms_client import ms_get
from config import WAREHOUSE_FG, WAREHOUSE_RAW, store_filter
from analytics.cache import read_cache

logger = logging.getLogger(__name__)


async def check_fg_deficit() -> str | None:
    """Проверяет дефицит готовой продукции (< 14 дней запаса).
    Возвращает текст оповещения или None если всё ок.
    """
    cache = read_cache()
    if not cache:
        return None

    sku_demand = cache.get("sku_demand", {})
    low_stock = [
        s for s in sku_demand.values()
        if s.get("days_of_supply", 999) < 14 and s.get("avg_daily_demand", 0) > 0
    ]

    if not low_stock:
        return None

    low_stock.sort(key=lambda x: x.get("days_of_supply", 999))

    lines = ["⚠️ **Дефицит готовой продукции** (< 14 дней запаса)\n"]
    for s in low_stock[:15]:
        dos = s.get("days_of_supply", 0)
        emoji = "🔴" if dos < 3 else "🟡" if dos < 7 else "🟠"
        lines.append(
            f"{emoji} {s['name']}: **{s.get('current_stock', 0)}** шт "
            f"({dos} дн. запаса, avg {s['avg_daily_demand']}/день)"
        )

    if len(low_stock) > 15:
        lines.append(f"\n... и ещё {len(low_stock) - 15} позиций")

    return "\n".join(lines)


async def check_raw_deficit() -> str | None:
    """Проверяет остатки сырья с учётом сроков поставки из config.
    Возвращает текст оповещения или None если всё ок.
    """
    from config import get_lead_time, OUTSOURCE_NICOBUSTER_TRIGGER_DAYS, NICOBUSTER_OWN_DISCONTINUED

    stock_data = await ms_get("/report/stock/all", {
        "filter": store_filter(WAREHOUSE_RAW),
        "limit": 500,
    })
    rows = stock_data.get("rows", [])

    critical = []
    nicobuster_outsource = None

    for r in rows:
        code = r.get("code", "")
        name = r.get("name", "?")
        stock = r.get("stock", 0)
        uom = r.get("uom", {}).get("name", "")

        # Этикетки и коробки — простой порог по штукам
        if "этикетк" in name.lower() or "коробк" in name.lower():
            if 0 < stock < 200:
                critical.append({"name": name, "stock": stock, "uom": uom,
                                  "reason": "< 200 шт", "priority": "high"})
            continue

        # Никобустер аутсорс — отдельная логика
        if "аутсорс" in name.lower() or "outsource" in name.lower():
            nicobuster_outsource = {"name": name, "stock": stock, "uom": uom}
            continue

        # Собственные ампулы — выводятся из оборота, не алертим
        if NICOBUSTER_OWN_DISCONTINUED and "ампула" in name.lower():
            continue

        lt = get_lead_time(code, name)
        lead_days = lt["lead_time"]

        # Собственное производство (lead_time=0) — пропускаем
        if lead_days == 0:
            continue

        # Порог: для жидкостей ~2000 мл × lead_days × 0.3, для штук lead_days × 20
        if uom in ("Мл", "л", "мл"):
            threshold = max(lead_days * 2000 * 0.3, 500)
        else:
            threshold = max(lead_days * 20, 100)

        if 0 < stock < threshold:
            priority = "high" if stock < threshold * 0.3 else "medium"
            critical.append({"name": name, "stock": stock, "uom": uom,
                              "lead_time_days": lead_days,
                              "reason": f"< {threshold:.0f} {uom} (lead time {lead_days} дн.)",
                              "priority": priority})

    # Никобустер аутсорс
    if nicobuster_outsource and 0 < nicobuster_outsource["stock"] < OUTSOURCE_NICOBUSTER_TRIGGER_DAYS * 50:
        critical.append({**nicobuster_outsource, "lead_time_days": 7,
                          "reason": f"< {OUTSOURCE_NICOBUSTER_TRIGGER_DAYS} дней — заказать 30 л на фасовку",
                          "priority": "high"})

    if not critical:
        return None

    critical.sort(key=lambda x: (x["priority"] != "high", x["stock"]))
    lines = ["⚠️ **Критические остатки сырья**\n"]
    for r in critical[:15]:
        emoji = "🔴" if r.get("priority") == "high" else "🟡"
        lines.append(f"{emoji} {r['name']}: **{r['stock']}** {r['uom']} ({r['reason']})")
    if len(critical) > 15:
        lines.append(f"\n... и ещё {len(critical) - 15} позиций")

    return "\n".join(lines)


async def check_sleeping_clients() -> str | None:
    """Клиенты, которые 'опаздывают' с заказом > 7 дней от прогноза.
    Возвращает текст оповещения или None.
    """
    cache = read_cache()
    if not cache:
        return None

    clients = cache.get("client_patterns", {})
    today = datetime.now().strftime("%Y-%m-%d")

    sleeping = []
    for c in clients.values():
        predicted = c.get("predicted_next_order", "")
        if not predicted:
            continue
        if c.get("activity") != "sleeping":
            continue
        days_late = (datetime.now() - datetime.strptime(c["last_order_date"], "%Y-%m-%d")).days
        avg_interval = c.get("avg_interval_days", 0)
        if avg_interval > 0 and days_late > avg_interval + 7:
            sleeping.append({
                "name": c["name"],
                "last_order": c["last_order_date"],
                "days_late": days_late - avg_interval,
                "avg_interval": avg_interval,
                "revenue_30d": c.get("revenue_30d_uah", 0),
            })

    if not sleeping:
        return None

    sleeping.sort(key=lambda x: x["revenue_30d"], reverse=True)

    lines = ["😴 **Спящие клиенты** (опоздание > 7 дней)\n"]
    for s in sleeping[:10]:
        lines.append(
            f"• **{s['name']}**: последний заказ {s['last_order']}, "
            f"опоздание {s['days_late']} дн. (обычно каждые {s['avg_interval']} дн.)"
        )

    return "\n".join(lines)


async def check_declining_clients() -> str | None:
    """Клиенты с падением выручки > 20%.
    Возвращает текст оповещения или None.
    """
    cache = read_cache()
    if not cache:
        return None

    clients = cache.get("client_patterns", {})
    declining = [
        c for c in clients.values()
        if c.get("revenue_trend") == "declining" and c.get("revenue_prev_30d_uah", 0) > 1000
    ]

    if not declining:
        return None

    declining.sort(key=lambda x: x.get("revenue_prev_30d_uah", 0), reverse=True)

    lines = ["📉 **Негативная динамика клиентов** (падение выручки > 20%)\n"]
    for c in declining[:10]:
        prev = c["revenue_prev_30d_uah"]
        curr = c["revenue_30d_uah"]
        drop_pct = round((1 - curr / prev) * 100) if prev > 0 else 0
        lines.append(
            f"• **{c['name']}**: {prev:,.0f} → {curr:,.0f} ₴ (−{drop_pct}%)"
        )

    return "\n".join(lines)


async def get_production_digest() -> str:
    """Дайджест: что произвели за сегодня (по выполнениям этапов)."""
    today = datetime.now().strftime("%Y-%m-%d")
    dt_from = f"{today} 00:00:00"

    data = await ms_get("/entity/productionstagecompletion", {
        "filter": f"moment>{dt_from}",
        "expand": "processingOrder,products.assortment",
        "limit": 200,
    })
    rows = data.get("rows", [])

    if not rows:
        return f"📊 **Производство за {today}**\n\nВыполнений этапов не зафиксировано."

    # Aggregate by product name from output products
    totals: dict[str, float] = {}
    for r in rows:
        products = r.get("products", {}).get("rows", [])
        if products:
            for p in products:
                product_name = p.get("assortment", {}).get("name", "?")
                qty = p.get("quantity", 0)
                totals[product_name] = totals.get(product_name, 0) + qty
        else:
            # Fallback: top-level quantity + order name
            qty = r.get("quantity", 0)
            name = r.get("processingOrder", {}).get("name", "?")
            totals[name] = totals.get(name, 0) + qty

    lines = [f"📊 **Производство за {today}**\n"]
    total_units = 0
    for name, qty in sorted(totals.items(), key=lambda x: -x[1]):
        lines.append(f"• {name}: **{qty:.0f}** шт")
        total_units += qty

    lines.append(f"\nИтого: **{total_units:.0f}** шт, **{len(rows)}** выполнений")
    return "\n".join(lines)
