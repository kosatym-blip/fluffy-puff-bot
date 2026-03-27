# -*- coding: utf-8 -*-
"""Claude agent loop — tool_use цикл с историей диалогов."""

import asyncio
import json
import logging

from anthropic import AsyncAnthropic, RateLimitError

from config import ANTHROPIC_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS, MAX_TOOL_ITERATIONS, MAX_HISTORY_MESSAGES
from system_prompt import get_system_prompt
from tools import TOOLS, TOOL_MAP

logger = logging.getLogger(__name__)

anthropic = AsyncAnthropic(api_key=ANTHROPIC_KEY)

# История диалогов на пользователя (в памяти)
user_histories: dict[int, list] = {}

# Лимит символов на один tool result (чтоб не раздувать контекст)
MAX_TOOL_RESULT_CHARS = 25000

# Лимит символов на ответ ассистента в истории
MAX_HISTORY_ANSWER_CHARS = 2000


def _get_cached_system():
    """Системный промпт с cache_control для prompt caching."""
    return [
        {
            "type": "text",
            "text": get_system_prompt(),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _get_cached_tools():
    """Тулы с cache_control на последнем для кэширования всего блока."""
    if not TOOLS:
        return TOOLS
    cached = list(TOOLS)
    # Добавляем cache_control на последний тул — кэшируется весь блок
    last = dict(cached[-1])
    last["cache_control"] = {"type": "ephemeral"}
    cached[-1] = last
    return cached


async def _call_claude(messages: list, retries: int = 2) -> object:
    """Вызов Claude API с retry при 429 и prompt caching."""
    for attempt in range(retries + 1):
        try:
            return await anthropic.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=CLAUDE_MAX_TOKENS,
                system=_get_cached_system(),
                tools=_get_cached_tools(),
                messages=messages,
            )
        except RateLimitError:
            if attempt < retries:
                wait = 15 * (attempt + 1)  # 15s, 30s
                logger.warning(f"Rate limit 429, waiting {wait}s (attempt {attempt + 1})")
                await asyncio.sleep(wait)
            else:
                raise


async def run_claude_agent(user_id: int, user_message: str) -> str:
    """Запускает Claude с инструментами, возвращает финальный ответ.

    В историю сохраняем ТОЛЬКО user message + final text answer.
    Tool iterations (assistant tool_use + tool_result) живут только в рамках
    текущего запроса и не накапливаются между сообщениями.
    """
    history = user_histories.setdefault(user_id, [])
    history.append({"role": "user", "content": user_message})

    # Ограничиваем историю
    if len(history) > MAX_HISTORY_MESSAGES:
        history = history[-MAX_HISTORY_MESSAGES:]
        user_histories[user_id] = history

    # messages = история (user+assistant text only) + текущий запрос
    messages = list(history)
    iterations = 0

    try:
        while iterations < MAX_TOOL_ITERATIONS:
            iterations += 1
            response = await _call_claude(messages)

            # Логируем токены
            logger.info(
                f"Claude: in={response.usage.input_tokens} out={response.usage.output_tokens} "
                f"stop={response.stop_reason} iter={iterations}"
            )

            # Если Claude хочет вызвать инструменты
            if response.stop_reason == "tool_use":
                # Tool iterations добавляем в messages для текущего цикла,
                # но НЕ в history (они не переживут текущий запрос)
                messages.append({"role": "assistant", "content": response.content})

                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        logger.info(f"Tool call: {block.name}({block.input})")
                        try:
                            fn = TOOL_MAP.get(block.name)
                            if fn:
                                result = await fn(**block.input)
                            else:
                                result = json.dumps({"error": f"Unknown tool: {block.name}"})
                        except Exception as e:
                            logger.error(f"Tool error {block.name}: {e}")
                            result = json.dumps({"error": str(e)})

                        # Обрезаем слишком длинные результаты
                        if len(result) > MAX_TOOL_RESULT_CHARS:
                            logger.warning(f"Tool result truncated: {block.name} ({len(result)} chars)")
                            result = result[:MAX_TOOL_RESULT_CHARS] + '\n... (обрезано)'

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                messages.append({"role": "user", "content": tool_results})
            else:
                # Финальный текстовый ответ — ТОЛЬКО его сохраняем в историю
                final_text = next(
                    (b.text for b in response.content if hasattr(b, "text")),
                    "Не могу ответить на этот вопрос.",
                )
                # В историю сохраняем обрезанную версию для экономии токенов
                history_text = final_text
                if len(history_text) > MAX_HISTORY_ANSWER_CHARS:
                    history_text = history_text[:MAX_HISTORY_ANSWER_CHARS] + "\n... (ответ обрезан в истории)"
                history.append({"role": "assistant", "content": history_text})
                # Пользователю возвращаем полный ответ
                return final_text

        return "Превышен лимит итераций. Попробуй упростить запрос."

    except RateLimitError:
        logger.error(f"Rate limit exceeded for user {user_id} after retries")
        return "⚠️ Превышен лимит запросов к API. Подожди минуту и попробуй снова."


def clear_history(user_id: int):
    """Очистить историю диалога пользователя."""
    user_histories.pop(user_id, None)
