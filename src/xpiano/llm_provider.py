from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from typing import Any

import anthropic


class _ToolExecutionError(RuntimeError):
    pass


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, output_schema: dict | None = None) -> str:
        raise NotImplementedError

    @abstractmethod
    def stream(self, prompt: str, tools: list[dict] | None = None) -> AsyncIterator[dict[str, Any]]:
        raise NotImplementedError

    async def stream_with_tool_results(
        self,
        prompt: str,
        tools: list[dict] | None,
        on_tool_use: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        async for event in self.stream(prompt=prompt, tools=tools):
            if event.get("type") == "tool_use":
                on_tool_use(event)
            yield event


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
        max_tool_rounds: int = 8,
    ):
        if max_tool_rounds <= 0:
            raise ValueError("max_tool_rounds must be > 0")
        resolved_key = api_key or os.getenv(api_key_env)
        if not resolved_key:
            raise ValueError(f"missing Claude API key; set {api_key_env}")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_tool_rounds = max_tool_rounds
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
        try:
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
        except Exception:
            # Degrade gracefully to non-streamed text.
            try:
                fallback_text = self.generate(prompt)
            except Exception as exc:
                raise RuntimeError(
                    "Claude streaming and fallback generation both failed"
                ) from exc
            yield {"type": "text_delta", "text": fallback_text}

    async def stream_with_tool_results(
        self,
        prompt: str,
        tools: list[dict] | None,
        on_tool_use: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        stream_tools = _normalize_tools(tools)
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        rounds = 0
        try:
            while rounds < self.max_tool_rounds:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    messages=messages,
                    tools=stream_tools if stream_tools else anthropic.NOT_GIVEN,
                )
                assistant_content: list[dict[str, Any]] = []
                tool_results: list[dict[str, Any]] = []

                for block in response.content:
                    block_type = getattr(block, "type", None)
                    if block_type == "text":
                        text = str(getattr(block, "text", ""))
                        if text:
                            yield {"type": "text_delta", "text": text}
                        assistant_content.append({"type": "text", "text": text})
                        continue
                    if block_type == "tool_use":
                        tool_id = str(getattr(block, "id", ""))
                        if not tool_id:
                            raise ValueError("missing tool_use id in Claude response")
                        payload = dict(getattr(block, "input", {}) or {})
                        tool_event = {
                            "type": "tool_use",
                            "id": tool_id,
                            "name": getattr(block, "name", None),
                            "input": payload,
                        }
                        yield tool_event
                        assistant_content.append(
                            {
                                "type": "tool_use",
                                "id": tool_id,
                                "name": getattr(block, "name", None),
                                "input": payload,
                            }
                        )
                        try:
                            tool_output = on_tool_use(tool_event)
                        except Exception as exc:
                            raise _ToolExecutionError from exc
                        try:
                            serialized = json.dumps(
                                tool_output,
                                ensure_ascii=False,
                                allow_nan=False,
                            )
                        except (TypeError, ValueError) as exc:
                            raise _ToolExecutionError from exc
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": serialized,
                            }
                        )

                if assistant_content:
                    messages.append(
                        {"role": "assistant", "content": assistant_content})
                if not tool_results:
                    break
                messages.append({"role": "user", "content": tool_results})
                rounds += 1

            if rounds >= self.max_tool_rounds:
                yield {
                    "type": "text_delta",
                    "text": "\n[stream terminated: too many tool rounds]",
                }
        except _ToolExecutionError as exc:
            if exc.__cause__ is not None:
                raise exc.__cause__
            raise
        except Exception:
            try:
                async for event in super().stream_with_tool_results(
                    prompt=prompt,
                    tools=tools,
                    on_tool_use=on_tool_use,
                ):
                    yield event
            except Exception as exc:
                raise RuntimeError(
                    "Claude tool-result streaming and fallback both failed"
                ) from exc


def create_provider(config_data: dict[str, Any]) -> LLMProvider:
    llm_cfg = config_data.get("llm", {})
    provider_name = llm_cfg.get("provider", "claude")
    if provider_name != "claude":
        raise ValueError(f"unsupported llm provider: {provider_name}")
    raw_max_tool_rounds = llm_cfg.get("max_tool_rounds", 8)
    if isinstance(raw_max_tool_rounds, bool):
        raise ValueError("invalid llm.max_tool_rounds: must be integer > 0")
    if isinstance(raw_max_tool_rounds, float):
        raise ValueError("invalid llm.max_tool_rounds: must be integer > 0")
    try:
        max_tool_rounds = int(raw_max_tool_rounds)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "invalid llm.max_tool_rounds: must be integer > 0"
        ) from exc
    if max_tool_rounds <= 0:
        raise ValueError("invalid llm.max_tool_rounds: must be integer > 0")
    return ClaudeProvider(
        model=llm_cfg.get("model", "claude-sonnet-4-5-20250929"),
        api_key_env=llm_cfg.get("api_key_env", "ANTHROPIC_API_KEY"),
        max_tool_rounds=max_tool_rounds,
    )
