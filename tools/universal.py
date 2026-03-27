# -*- coding: utf-8 -*-
"""Универсальный инструмент ms_query — fallback для любого эндпоинта."""

import json
import logging

import httpx

from config import MS_BASE, MS_HEADERS

logger = logging.getLogger(__name__)

# Поля МойСклад, которые НЕ нужны Claude (мусор)
_JUNK_KEYS = {
    "meta", "owner", "group", "accountId", "shared", "applicable",
    "vatEnabled", "vatIncluded", "payedSum", "shippedSum", "invoicedSum",
    "syncId", "externalCode", "printed", "published", "files",
    "created", "updated", "pathName", "effectiveVat", "effectiveVatEnabled",
    "organizationAccount", "agentAccount", "attributes", "organization",
    "contract", "project", "rate", "store", "positions",
}

# Поля, которые чистим рекурсивно у вложенных объектов
_NESTED_JUNK = {"meta", "owner", "group", "accountId", "shared", "externalCode"}


def _clean_row(obj):
    """Убирает мусорные поля из объекта API, оставляя полезные данные."""
    if not isinstance(obj, dict):
        return obj

    cleaned = {}
    for k, v in obj.items():
        if k in _JUNK_KEYS:
            continue
        if isinstance(v, dict):
            # Для вложенных объектов (agent, state и т.д.) — оставляем только имя и id
            if "meta" in v and "name" in v:
                cleaned[k] = {"name": v["name"]}
                if "id" in v:
                    cleaned[k]["id"] = v["id"]
            elif "meta" in v and "id" in v:
                cleaned[k] = {"id": v["id"]}
            else:
                # Чистим рекурсивно
                inner = {ik: iv for ik, iv in v.items() if ik not in _NESTED_JUNK}
                if inner:
                    cleaned[k] = inner
        elif isinstance(v, list):
            # Списки — чистим каждый элемент
            cleaned[k] = [_clean_row(item) if isinstance(item, dict) else item for item in v[:20]]
        else:
            cleaned[k] = v

    # Суммы в копейках → UAH
    if "sum" in cleaned and isinstance(cleaned["sum"], (int, float)):
        cleaned["sum_uah"] = round(cleaned.pop("sum") / 100, 2)

    return cleaned


UNIVERSAL_TOOLS = [
    {
        "name": "ms_query",
        "description": "Универсальный запрос к МойСклад API — любой эндпоинт, любые параметры. Используй если нет подходящего специализированного инструмента. Результат автоматически очищается от мусорных полей.",
        "input_schema": {
            "type": "object",
            "properties": {
                "endpoint": {"type": "string", "description": "Путь API, например /entity/product"},
                "params": {"type": "object", "description": "Query параметры"},
                "method": {"type": "string", "default": "GET"},
                "body": {"type": "object", "description": "JSON body для POST/PUT"},
            },
            "required": ["endpoint"],
        },
    },
]


async def tool_ms_query(endpoint: str, params: dict = None, method: str = "GET", body: dict = None) -> str:
    try:
        url = f"{MS_BASE}{endpoint}" if endpoint.startswith("/") else endpoint
        logger.info(f"ms_query {method} {endpoint} params={params}")
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.request(method.upper(), url, headers=MS_HEADERS, params=params or {}, json=body)
            r.raise_for_status()
            data = r.json()

        if isinstance(data, dict) and "rows" in data:
            rows = data["rows"]
            total = data.get("meta", {}).get("size", len(rows))

            # Лимит записей
            max_rows = 30
            truncated = len(rows) > max_rows
            rows = rows[:max_rows]

            # Чистим каждую строку от мусора
            cleaned_rows = [_clean_row(r) for r in rows]

            result = {"total": total, "showing": len(cleaned_rows), "rows": cleaned_rows}
            if truncated:
                result["warning"] = f"Показано {max_rows} из {total}. Используй offset/limit."
            return json.dumps(result, ensure_ascii=False, default=str)

        # Не-rows ответ (dashboard, единичный объект)
        if isinstance(data, dict):
            data = _clean_row(data)
        return json.dumps(data, ensure_ascii=False, default=str)

    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"HTTP {e.response.status_code}: {e.response.text[:500]}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


UNIVERSAL_TOOL_MAP = {
    "ms_query": tool_ms_query,
}
