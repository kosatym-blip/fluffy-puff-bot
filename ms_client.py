# -*- coding: utf-8 -*-
"""HTTP-клиент для МойСклад API с retry и error handling."""

import asyncio
import logging

import httpx

from config import MS_BASE, MS_HEADERS

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30, headers=MS_HEADERS)
    return _client


async def ms_get(path: str, params: dict = None, retries: int = 2) -> dict:
    """GET-запрос к МойСклад API с retry при 429/5xx."""
    client = await _get_client()
    url = f"{MS_BASE}{path}"

    for attempt in range(retries + 1):
        try:
            r = await client.get(url, params=params or {})
            if r.status_code == 429 and attempt < retries:
                logger.warning(f"Rate limit 429 on {path}, retry {attempt + 1}")
                await asyncio.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()
        except httpx.TimeoutException:
            if attempt < retries:
                logger.warning(f"Timeout on {path}, retry {attempt + 1}")
                await asyncio.sleep(1)
                continue
            raise

    return {}


async def ms_request(method: str, path: str, params: dict = None, body: dict = None) -> dict:
    """Универсальный запрос к МойСклад API (GET/POST/PUT/DELETE)."""
    client = await _get_client()
    url = f"{MS_BASE}{path}" if path.startswith("/") else path
    r = await client.request(method.upper(), url, params=params or {}, json=body)
    r.raise_for_status()
    return r.json()


async def close_client():
    global _client
    if _client:
        await _client.aclose()
        _client = None
