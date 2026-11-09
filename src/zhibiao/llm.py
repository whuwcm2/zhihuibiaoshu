from __future__ import annotations

import json
import re
import time

from langsmith.wrappers import wrap_openai
from openai import OpenAI

from .config import Settings


class LLMError(RuntimeError):
    pass


def _parse_json_text(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


class DeepSeekChat:
    def __init__(self, settings: Settings) -> None:
        if not settings.deepseek_api_key:
            raise LLMError("DEEPSEEK_API_KEY 未配置")
        self.client = wrap_openai(
            OpenAI(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                timeout=240,
            )
        )
        self.model = settings.deepseek_model

    def _create(
        self,
        system: str,
        user: str,
        max_tokens: int,
        json_mode: bool,
    ) -> str:
        kwargs: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.3,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.client.chat.completions.create(**kwargs)
                choice = response.choices[0]
                if choice.finish_reason == "length":
                    raise LLMError("LLM 输出被截断，请缩小章节或提高 max_tokens")
                content = (choice.message.content or "").strip()
                if not content:
                    raise LLMError("LLM 返回空内容")
                return content
            except LLMError:
                # 截断/空内容重试无意义，交给上层拆分批次
                raise
            except Exception as exc:  # noqa: BLE001 - SDK 异常类型较杂
                last_error = exc
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        raise LLMError(f"LLM 调用失败: {last_error}")

    def complete_text(self, system: str, user: str, max_tokens: int = 8000) -> str:
        content = self._create(system, user, max_tokens, json_mode=False)
        if content.startswith("```"):
            content = re.sub(r"^```(?:markdown|md)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        return content.strip()

    def complete_json(self, system: str, user: str, max_tokens: int = 4000) -> dict:
        current = user
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return _parse_json_text(
                    self._create(system, current, max_tokens, json_mode=True)
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                current = user + "\n\n上一次输出不是合法 JSON，请严格只输出一个 JSON 对象。"
        raise LLMError(f"LLM JSON 输出解析失败: {last_error}")
