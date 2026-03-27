# -*- coding: utf-8 -*-
"""Менеджер кэша аналитики — чтение/запись JSON на диск."""

import json
import logging
import os
from datetime import datetime

from config import CACHE_DIR

logger = logging.getLogger(__name__)

# Попробуем основную директорию, fallback на /tmp
_cache_dir = CACHE_DIR
if not os.path.isdir(_cache_dir):
    _cache_dir = "/tmp/fluffypuff_cache"
    os.makedirs(_cache_dir, exist_ok=True)
    logger.warning(f"CACHE_DIR {CACHE_DIR} не найден, используем {_cache_dir}")

CACHE_FILE = os.path.join(_cache_dir, "analytics_cache.json")
CACHE_MAX_AGE_DAYS = 8  # обновляется еженедельно, 1 день grace


def read_cache() -> dict | None:
    """Читает кэш из файла. Возвращает None если нет или протух."""
    if not os.path.exists(CACHE_FILE):
        logger.info("Cache file not found")
        return None

    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        generated = data.get("generated_at", "")
        if generated:
            age = datetime.now() - datetime.fromisoformat(generated)
            if age.days > CACHE_MAX_AGE_DAYS:
                logger.warning(f"Cache stale: {age.days} days old")
                return None

        return data
    except Exception as e:
        logger.error(f"Failed to read cache: {e}")
        return None


def write_cache(data: dict):
    """Записывает кэш в файл."""
    data["generated_at"] = datetime.now().isoformat()
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"Cache written: {CACHE_FILE} ({os.path.getsize(CACHE_FILE)} bytes)")
    except Exception as e:
        logger.error(f"Failed to write cache: {e}")


def cache_exists() -> bool:
    return os.path.exists(CACHE_FILE)


def cache_age_hours() -> float | None:
    """Возвращает возраст кэша в часах, или None если нет."""
    cache = read_cache()
    if not cache:
        return None
    generated = cache.get("generated_at", "")
    if not generated:
        return None
    age = datetime.now() - datetime.fromisoformat(generated)
    return age.total_seconds() / 3600
