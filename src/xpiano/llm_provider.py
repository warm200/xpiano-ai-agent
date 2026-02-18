from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import anthropic


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, output_schema: dict | None = None) -> str:
        raise NotImplementedError

    @abstractmethod
    def stream(self, prompt: str, tools: list[dict] | None = None) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError


def _extract_text(content: Any) -> str:
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
    return "\n".join(parts).strip()


def _normalize_tools(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    normalized: list[dict] = []
    for tool in tools:
        if "input_schema" in tool:
            normalized.append(tool)
            continue
        if "parameters" in tool:
            normalized.append(
                {
                    "name": tool.get("name"),
                    "description": tool.get("description"),
                    "input_schema": tool.get("parameters"),
                }
            )
            continue
        normalized.append(tool)
    return normalized


class ClaudeProvider(LLMProvider):
    def __init__(
        self,
        model: str = "claude-sonnet-4-5-20250929",
        api_key: str | None = None,
        api_key_env: str = "ANTHROPIC_API_KEY",
        max_tokens: int = 1400,
        temperature: float = 0.2,
    ):
        resolved_key = api_key or os.getenv(api_key_env)
        if not resolved_key:
            raise ValueError(f"missing Claude API key; set {api_key_env}")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.client = anthropic.Anthropic(api_key=resolved_key)

    def generate(self, prompt: str, output_schema: dict | None = None) -> str:
        _ = output_schema
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _extract_text(response.content)
        if not text:
            raise ValueError("empty Claude response")
        return text

    async def stream(self, prompt: str, tools: list[dict] | None = None) -> AsyncIterator[dict[str, Any]]:
        stream_tools = _normalize_tools(tools)
        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
            tools=stream_tools if stream_tools else anthropic.NOT_GIVEN,
        ) as stream:
            for event in stream:
                event_type = getattr(event, "type", "")
                if event_type == "text":
                    yield {"type": "text_delta", "text": str(getattr(event, "text", ""))}
                elif event_type == "content_block_stop":
                    block = getattr(event, "content_block", None)
                    if getattr(block, "type", None) == "tool_use":
                        input_payload = dict(getattr(block, "input", {}) or {})
                        yield {
                            "type": "tool_use",
                            "name": getattr(block, "name", None),
                            "input": input_payload,
                        }


def create_provider(config_data: dict[str, Any]) -> LLMProvider:
    llm_cfg = config_data.get("llm", {})
    provider_name = llm_cfg.get("provider", "claude")
    if provider_name != "claude":
        raise ValueError(f"unsupported llm provider: {provider_name}")
    return ClaudeProvider(
        model=llm_cfg.get("model", "claude-sonnet-4-5-20250929"),
        api_key_env=llm_cfg.get("api_key_env", "ANTHROPIC_API_KEY"),
    )
