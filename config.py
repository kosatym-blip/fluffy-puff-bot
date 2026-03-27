# -*- coding: utf-8 -*-
"""Конфигурация Fluffy Puff Bot — env vars, константы, warehouse UUIDs."""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Tokens & API keys ──────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MOYSKLAD_TOKEN = os.getenv("MOYSKLAD_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

ALLOWED_USER_IDS = set(
    int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()
)

GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "")
ALERT_CHAT_ID = os.getenv("ALERT_CHAT_ID", "")
CACHE_DIR = os.getenv("CACHE_DIR", "/data")

# ─── МойСклад API ───────────────────────────────────────────────────────────
MS_BASE = "https://api.moysklad.ru/api/remap/1.2"
MS_HEADERS = {
    "Authorization": f"Bearer {MOYSKLAD_TOKEN}",
    "Accept-Encoding": "gzip",
    "Content-Type": "application/json",
}

# ─── Warehouse UUIDs ─────────────────────────────────────────────────────────
WAREHOUSE_RAW = "e931e894-16dc-11ee-0a80-044400023b0b"
WAREHOUSE_FG = "6bef019c-16eb-11ee-0a80-05460002d477"
WAREHOUSE_WIP = "65a5f7c5-16eb-11ee-0a80-09ad000284be"

WAREHOUSE_MAP = {
    "raw": WAREHOUSE_RAW,
    "fg": WAREHOUSE_FG,
    "wip": WAREHOUSE_WIP,
}


def store_filter(warehouse_id: str) -> str:
    """Возвращает фильтр для /report/stock/all в правильном формате href."""
    return f"store={MS_BASE}/entity/store/{warehouse_id}"

# ─── Claude agent settings ───────────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 4096
MAX_TOOL_ITERATIONS = 10
MAX_HISTORY_MESSAGES = 10  # only user+assistant text pairs, no tool iterations

# ─── Сроки поставки и минимальные запасы сырья ───────────────────────────────
# lead_time — дней от заказа до получения
# min_stock_days — минимальный запас в днях (при меньшем — оповещение)
# Если товар не найден в overrides — ищется по категории (по коду или группе)

LEAD_TIMES = {
    # Базовые жидкости
    "30147": {"lead_time": 5,  "min_stock_days": 20, "name": "Глицерин Фарм"},
    "30117": {"lead_time": 5,  "min_stock_days": 20, "name": "Пропиленгликоль Фарм"},

    # Никотин
    "31001": {"lead_time": 5,  "min_stock_days": 15, "name": "Никотин 500 мг"},
    "30098": {"lead_time": 5,  "min_stock_days": 15, "name": "Никотин 1000 мг"},
    "51516": {"lead_time": 0,  "min_stock_days": 15, "name": "Никотин 100 мг (собственное производство)"},
    "51061": {"lead_time": 5,  "min_stock_days": 15, "name": "Никотин гибрид 500 мг"},

    # Добавки
    "30124": {"lead_time": 5,  "min_stock_days": 15, "name": "WS-23 40%"},
    "51511": {"lead_time": 5,  "min_stock_days": 15, "name": "Neotame 20%"},
    "30099": {"lead_time": 5,  "min_stock_days": 30, "name": "Super Sweet (CAP)"},

    # Концентраты K (производство на стороне, длинный цикл)
    "ALL_K":  {"lead_time": 30, "min_stock_days": 45, "name": "Концентраты K"},

    # Флаконы
    "51286": {"lead_time": 15, "min_stock_days": 30, "name": "Флакон 15 мл прозрачный"},
    "51287": {"lead_time": 15, "min_stock_days": 30, "name": "Флакон 15 мл чёрный"},
    "00015": {"lead_time": 15, "min_stock_days": 30, "name": "Флакон 30 мл чёрный"},
    "00012": {"lead_time": 15, "min_stock_days": 30, "name": "Флакон 60 мл прозрачный"},
    "00013": {"lead_time": 15, "min_stock_days": 30, "name": "Флакон 60 мл чёрный"},
    "00045": {"lead_time": 15, "min_stock_days": 30, "name": "Флакон глицерин 30 мл (Глория)"},
    "00044": {"lead_time": 15, "min_stock_days": 30, "name": "Флакон глицерин 50 мл"},
    "51288": {"lead_time": 15, "min_stock_days": 30, "name": "Флакон глицерин 15 мл (Стелла)"},
    "00046": {"lead_time": 5,  "min_stock_days": 30, "name": "Флакон глицерин 1000 мл"},
    "51240": {"lead_time": 15, "min_stock_days": 30, "name": "Флакон 10 мл"},

    # Коробки (печать на заказ — длинный цикл)
    "BOX_18": {"lead_time": 30, "min_stock_days": 45, "name": "Коробки 18 мл"},
    "BOX_24": {"lead_time": 30, "min_stock_days": 45, "name": "Коробки 24 мл"},
    "BOX_12A":{"lead_time": 30, "min_stock_days": 45, "name": "Коробки 12 мл Alpha"},
    "51043":  {"lead_time": 10, "min_stock_days": 15, "name": "Коробка на 20 флаконов 30 мл"},
    "51044":  {"lead_time": 10, "min_stock_days": 15, "name": "Коробка на 30 флаконов 30 мл"},
    "51050":  {"lead_time": 5,  "min_stock_days": 15, "name": "ZIP-пакеты"},

    # Этикетки (печать на заказ, кроме этикеток на глицерин)
    "ALL_LABELS":       {"lead_time": 30, "min_stock_days": 45, "name": "Этикетки (стандарт)"},
    "LABELS_GLYCERIN":  {"lead_time": 15, "min_stock_days": 30, "name": "Этикетки на глицерин"},

    # Никобустер аутсорс (фасовка на стороне)
    "OUTSOURCE_NICOBUSTER": {"lead_time": 7, "min_stock_days": 30, "name": "Никобустер аутсорс"},
}

# Сроки по категориям ароматизаторов (если нет индивидуальной записи выше)
# SSA больше не используется — исключена
FLAVOR_BRAND_LEAD_TIMES = {
    "CAP": {"lead_time": 5, "min_stock_days": 30},
    "FA":  {"lead_time": 5, "min_stock_days": 30},
    "FVH": {"lead_time": 5, "min_stock_days": 30},
    "INW": {"lead_time": 5, "min_stock_days": 30},
    "TFA": {"lead_time": 5, "min_stock_days": 30},
    "XIA": {"lead_time": 5, "min_stock_days": 30},
}

# Бренды ароматизаторов, которые больше не используются (не учитываем в закупках)
DISCONTINUED_BRANDS = {"SSA"}

# Никобустеры собственного производства (ампулы) — выводятся из оборота,
# переводим клиентов на аутсорс. Не учитываем в расчёте новых закупок.
NICOBUSTER_OWN_DISCONTINUED = True

# Порог запуска аутсорс-фасовки никобустера:
# если остаток < OUTSOURCE_NICOBUSTER_TRIGGER_DAYS дней — заказать 30 л сырья
OUTSOURCE_NICOBUSTER_TRIGGER_DAYS = 21
OUTSOURCE_NICOBUSTER_ORDER_LITERS = 30


# ─── Классификация товаров по папке МойСклад ─────────────────────────────────
# Ключ — подстрока pathName, значение — тип производства
FOLDER_TYPE_MAP = {
    "Ароматизаторы 12мл/1. Alpha":          "aroma_12_active",
    "Ароматизаторы 12мл/2. SIGMA":          "aroma_12_active",
    "Ароматизаторы 12мл/3. FRUITS":         "aroma_12_legacy",   # допродажа
    "Ароматизаторы 12мл/4. ICE EDITIONS":   "aroma_12_legacy",   # допродажа
    "Ароматизаторы 12мл/5. SWEETS":         "aroma_12_legacy",   # допродажа
    "Ароматизаторы 18мл":                   "aroma_18",          # свой WIP
    "Ароматизаторы 24мл":                   "aroma_24",          # WIP от 12мл
    "Ароматизаторы 6мл":                    "aroma_6",           # WIP от 12мл
    "ГЛІЦЕРИН":                             "glycerin",
    "НІКОБУСТЕРИ АУТСОРС":                  "nicobuster_outsource",
    "НІКОБУСТЕРИ":                          "nicobuster",
    # НЗП — незавершённое производство (WIP)
    "Ароматизаторы 12мл НЗП":              "wip_12",
    "Ароматизаторы Alpha 12мл НЗП":        "wip_12",
    "Ароматизаторы 18мл НЗП":              "wip_18",
}

# Активные линейки (планируем производство)
ACTIVE_PRODUCT_TYPES = {"aroma_12_active", "aroma_18", "aroma_24", "aroma_6", "glycerin", "nicobuster", "nicobuster_outsource"}

# Неактивные линейки (допродажа, не планируем производство)
LEGACY_PRODUCT_TYPES = {"aroma_12_legacy"}


def classify_by_folder(path_name: str) -> str:
    """Определяет тип товара по полному пути папки МойСклад."""
    for key, ptype in FOLDER_TYPE_MAP.items():
        if key in path_name:
            return ptype
    return "other"


def get_lead_time(code: str, name: str = "") -> dict:
    """Вернуть {'lead_time': N, 'min_stock_days': N} для SKU."""
    if code in LEAD_TIMES:
        return LEAD_TIMES[code]
    # Определяем бренд по суффиксу в названии: "(CAP)", "(FA)" и т.д.
    for brand, data in FLAVOR_BRAND_LEAD_TIMES.items():
        if f"({brand})" in name:
            return data
    # Концентраты K по коду 5xxxx
    if code.startswith("5") and name.lower().endswith(" k"):
        return LEAD_TIMES["ALL_K"]
    # По умолчанию
    return {"lead_time": 7, "min_stock_days": 14}
