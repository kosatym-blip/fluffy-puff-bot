# -*- coding: utf-8 -*-
"""Инструменты: остатки, товары."""

import json

from ms_client import ms_get
from config import WAREHOUSE_MAP, store_filter

STOCK_TOOLS = [
    {
        "name": "get_stock",
        "description": "Получить остатки товаров на складах Fluffy Puff. warehouse: 'raw'=сырьё, 'fg'=готовая продукция, 'all'=все склады. search — поиск по коду (цифры) или названию.",
        "input_schema": {
            "type": "object",
            "properties": {
                "warehouse": {"type": "string", "enum": ["raw", "fg", "wip", "all"], "default": "all"},
                "search": {"type": "string", "description": "Поиск по коду товара или названию"},
                "only_critical": {"type": "boolean", "description": "Только критические (нулевые и < 5 шт/500 мл)"},
            },
        },
    },
    {
        "name": "get_products",
        "description": "Каталог товаров. Поиск по коду (цифры) или названию.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Код товара или часть названия"},
                "limit": {"type": "integer", "default": 30},
            },
        },
    },
    {
        "name": "get_product_by_code",
        "description": "Детальная карточка товара по коду: название, UUID, цены, остатки по каждому складу.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Код товара (например '20001', '30099')"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "get_bundles",
        "description": "Наборы (бандлы) — 91 набор. Поиск по названию.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string"},
                "limit": {"type": "integer", "default": 30},
            },
        },
    },
]


async def tool_get_stock(warehouse="all", search=None, only_critical=False) -> str:
    params = {"limit": 500}

    if warehouse != "all" and warehouse in WAREHOUSE_MAP:
        params["filter"] = store_filter(WAREHOUSE_MAP[warehouse])

    # Если поиск по коду — находим имя
    name_filter = None
    if search and search.strip().isdigit():
        try:
            d = await ms_get("/entity/product", {"filter": f"code={search.strip()}"})
            if d.get("rows"):
                name_filter = d["rows"][0].get("name", "")
        except Exception:
            pass

    data = await ms_get("/report/stock/all", params)
    rows = data.get("rows", [])

    if name_filter:
        rows = [r for r in rows if name_filter.lower() in r.get("name", "").lower()]
    elif search and not search.strip().isdigit():
        rows = [r for r in rows if search.lower() in r.get("name", "").lower()]

    if only_critical:
        rows = [r for r in rows if r.get("stock", 0) <= 5]

    result = []
    for r in rows[:80]:
        result.append({
            "name": r.get("name", ""),
            "code": r.get("code", ""),
            "stock": r.get("stock", 0),
            "uom": r.get("uom", {}).get("name", ""),
            "folder": r.get("folder", {}).get("name", ""),
        })

    return json.dumps(result, ensure_ascii=False)


async def tool_get_products(search=None, limit=30) -> str:
    params = {"limit": limit}

    if search and search.strip().isdigit():
        params["filter"] = f"code={search.strip()}"
    elif search:
        params["search"] = search

    data = await ms_get("/entity/product", params)
    rows = data.get("rows", [])

    result = []
    for r in rows:
        sale_price = 0
        for p in r.get("salePrices", []):
            if p.get("priceType", {}).get("name", "") == "Цена продажи":
                sale_price = p.get("value", 0) / 100
                break

        result.append({
            "name": r.get("name", ""),
            "code": r.get("code", ""),
            "article": r.get("article", ""),
            "uom": r.get("uom", {}).get("name", "") if r.get("uom") else "",
            "sale_price_uah": round(sale_price, 2),
        })

    return json.dumps(result, ensure_ascii=False)


async def tool_get_product_by_code(code: str) -> str:
    # Find product by code
    data = await ms_get("/entity/product", {"filter": f"code={code.strip()}"})
    rows = data.get("rows", [])

    if not rows:
        return json.dumps({"error": f"Товар с кодом '{code}' не найден"}, ensure_ascii=False)

    product = rows[0]
    product_id = product.get("id", "")

    # Get stock by warehouse
    stock_data = await ms_get("/report/stock/all", {"limit": 100})
    stock_rows = stock_data.get("rows", [])
    product_name = product.get("name", "")

    stock_by_store = {}
    for r in stock_rows:
        if r.get("name", "") == product_name:
            store_name = r.get("store", {}).get("name", r.get("folder", {}).get("name", "?"))
            stock_by_store[store_name] = r.get("stock", 0)

    # If no stock found in report, try with product name filter
    if not stock_by_store:
        for wh_name, wh_id in WAREHOUSE_MAP.items():
            wh_stock = await ms_get("/report/stock/all", {
                "filter": store_filter(wh_id),
                "limit": 500,
            })
            for r in wh_stock.get("rows", []):
                if r.get("name", "") == product_name:
                    stock_by_store[wh_name] = r.get("stock", 0)

    # Extract prices
    prices = {}
    for p in product.get("salePrices", []):
        price_name = p.get("priceType", {}).get("name", "")
        prices[price_name] = round(p.get("value", 0) / 100, 2)

    buy_price = round(product.get("buyPrice", {}).get("value", 0) / 100, 2)

    result = {
        "id": product_id,
        "name": product_name,
        "code": product.get("code", ""),
        "article": product.get("article", ""),
        "uom": product.get("uom", {}).get("name", "") if product.get("uom") else "",
        "buy_price_uah": buy_price,
        "sale_prices": prices,
        "stock_by_warehouse": stock_by_store,
    }

    return json.dumps(result, ensure_ascii=False)


async def tool_get_bundles(search=None, limit=30) -> str:
    params = {"limit": limit}
    if search:
        params["search"] = search

    data = await ms_get("/entity/bundle", params)
    rows = data.get("rows", [])

    result = []
    for r in rows:
        components = []
        comp_data = r.get("components", {})
        if isinstance(comp_data, dict):
            for c in comp_data.get("rows", []):
                components.append({
                    "name": c.get("assortment", {}).get("name", "?"),
                    "quantity": c.get("quantity", 0),
                })

        sale_price = 0
        for p in r.get("salePrices", []):
            if p.get("priceType", {}).get("name", "") == "Цена продажи":
                sale_price = p.get("value", 0) / 100
                break

        result.append({
            "name": r.get("name", ""),
            "code": r.get("code", ""),
            "sale_price_uah": round(sale_price, 2),
            "components": components,
        })

    return json.dumps(result, ensure_ascii=False)


STOCK_TOOL_MAP = {
    "get_stock": tool_get_stock,
    "get_products": tool_get_products,
    "get_product_by_code": tool_get_product_by_code,
    "get_bundles": tool_get_bundles,
}
