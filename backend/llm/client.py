"""LLM 网关客户端。

通过 OpenAI-compatible 协议与 LLM 网关通信。
支持非流式和流式两种调用模式。
"""

import json
import logging
from typing import AsyncIterator, cast

import httpx

from core.config import get_auth_token, get_base_url, get_default_model
from llm.constants import (
    API_CHAT_PATH,
    API_MODELS_PATH,
    CONTENT_TYPE_JSON,
    ERROR_DETAIL_TRUNCATE,
    ERROR_RESULT_TRUNCATE,
    HEALTH_CHECK_TIMEOUT,
    HEALTH_HEALTHY,
    HEALTH_NO_DEFAULT_MODEL,
    HEALTH_PING_MAX_TOKENS,
    HEALTH_PING_TEXT,
    HEALTH_UNHEALTHY,
    HEALTH_UNKNOWN,
    HEALTH_UNREACHABLE,
    LLM_PING_TIMEOUT,
    LLM_TIMEOUT,
    REASONING_EFFORT_NONE,
    ROLE_USER,
    SSE_CONTENT,
    SSE_DATA_PREFIX,
    SSE_DONE,
    SSE_REASONING,
    SSE_TOOL_CALLS,
    THINKING_ENABLED_TYPE,
)
from llm.models import ChatRequest, ChatResponse

_log = logging.getLogger(__name__)


class LLMClientError(Exception):
    """LLM 客户端通用异常。"""


# 内部字段：仅用于前后端状态同步，不应发送给 LLM API
_INTERNAL_FIELDS = frozenset({"message_status", "thinking", "is_error"})


def _build_payload(request: ChatRequest, *, stream: bool = False) -> dict[str, object]:
    """将 ChatRequest 转换为 API payload。"""
    payload: dict[str, object] = {
        "model": request.model,
        "messages": [
            {k: v for k, v in m.model_dump(exclude_none=True).items() if k not in _INTERNAL_FIELDS}
            for m in request.messages
        ],
        "stream": stream,
    }
    for key in ("temperature", "max_tokens", "top_p", "top_k",
                 "presence_penalty", "frequency_penalty", "repeat_penalty"):
        val = getattr(request, key, None)
        if val is not None:
            payload[key] = val
    if request.tools:
        payload["tools"] = [
            {"type": "function", "function": t.model_dump()} for t in request.tools
        ]
    if request.thinking:
        payload["thinking"] = {"type": THINKING_ENABLED_TYPE}
        if stream:
            payload["stream_options"] = {"include_reasoning": True}
    else:
        # 显式禁用推理，避免部分模型默认消耗 token 在 reasoning 上
        payload["reasoning_effort"] = REASONING_EFFORT_NONE
    return payload


def _headers() -> dict[str, str]:
    """构建鉴权请求头。"""
    token = get_auth_token()
    headers: dict[str, str] = {"Content-Type": CONTENT_TYPE_JSON}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _extract_tool_calls(choice: dict[str, object]) -> list[dict[str, object]] | None:
    """从 API 响应中提取工具调用，保持 API 原始格式。

    返回的每个元素包含 API 原始字段：id, type, function(name, arguments)。
    此格式可直接回传给 API，无需二次转换。
    """
    message = choice.get("message")
    if not isinstance(message, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
        return None
    message = cast(dict[str, object], message)
    raw_tool_calls = message.get("tool_calls")
    if not isinstance(raw_tool_calls, list):  # pyright: ignore[reportUnnecessaryIsInstance]
        return None
    raw_tool_calls = cast(list[dict[str, object]], raw_tool_calls)
    result: list[dict[str, object]] = []
    for tc_obj in raw_tool_calls:
        tc: dict[str, object] = tc_obj
        fn_obj = tc.get("function")
        if not isinstance(fn_obj, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
            continue
        fn: dict[str, object] = cast(dict[str, object], fn_obj)  # pyright: ignore[reportUnnecessaryTypeIgnore]
        # 保持 API 原始格式：{id, type, function: {name, arguments}}
        result.append({
            "id": str(tc.get("id", "")),
            "type": str(tc.get("type", "function")),
            "function": {
                "name": str(fn.get("name", "")),
                "arguments": fn.get("arguments", "{}"),
            },
        })
    return result if result else None


def parse_tool_call_for_display(tc: dict[str, object]) -> tuple[str, str, dict[str, object]]:
    """从 API 格式的 tool_call 中提取 (id, name, arguments) 三元组。

    arguments 会被解析为 dict（API 中是 JSON 字符串）。
    """
    tc_id = str(tc.get("id", ""))
    fn = tc.get("function")
    if isinstance(fn, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
        fn = cast(dict[str, object], fn)
        name = str(fn.get("name", ""))
        raw_args = fn.get("arguments", "{}")
    else:
        name = ""
        raw_args = "{}"
    if isinstance(raw_args, str):
        try:
            arguments: dict[str, object] = json.loads(raw_args)
        except (json.JSONDecodeError, TypeError):
            arguments = {}
    elif isinstance(raw_args, dict):
        arguments = raw_args  # pyright: ignore[reportUnknownVariableType]
    else:
        arguments = {}
    return tc_id, name, arguments


async def chat(request: ChatRequest) -> ChatResponse:
    """向 LLM 网关发送非流式聊天请求。

    Args:
        request: 包含 model、messages、temperature 等的请求。

    Returns:
        ChatResponse: 模型回复 + 用量统计。

    Raises:
        LLMClientError: API 调用失败或响应解析失败。
    """
    payload = _build_payload(request, stream=False)

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT, follow_redirects=True) as client:
        try:
            resp = await client.post(
                f"{get_base_url()}{API_CHAT_PATH}",
                headers=_headers(),
                json=payload,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:ERROR_DETAIL_TRUNCATE] if e.response else "无响应体"
            raise LLMClientError(
                f"LLM API 返回错误 {e.response.status_code}: {detail}"
            ) from e
        except httpx.RequestError as e:
            raise LLMClientError(f"无法连接到 LLM 服务: {e}") from e

    try:
        data = resp.json()
    except ValueError as e:
        raise LLMClientError(f"LLM 响应不是有效 JSON: {resp.text[:ERROR_DETAIL_TRUNCATE]}") from e

    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})
    _log.info("LLM chat 完成: model=%s, finish_reason=%s, usage=%s",
              request.model, choice.get("finish_reason"), data.get("usage", {}))
    return ChatResponse(
        model=request.model,
        content=message.get("content", "") or "",
        finish_reason=choice.get("finish_reason"),
        tool_calls=_extract_tool_calls(choice),
        reasoning_content=message.get("reasoning_content"),
        usage=data.get("usage", {}),
    )


async def chat_stream_events(
    request: ChatRequest,
    session_id: str = "",
) -> AsyncIterator[dict[str, object]]:
    """向 LLM 网关发送流式聊天请求，返回带类型标注的事件。

    每帧为 {"type": "reasoning"|"content", "content": "..."}。
    流结束时如有工具调用，yield {"type": "tool_calls", "tool_calls": [...]}。

    兼容 reasoning_content 字段（DeepSeek-R1、Gemma 等模型）。

    Args:
        request: 聊天请求。
        session_id: 可选的会话 ID，用于日志关联。

    Yields:
        dict: 类型事件。

    Raises:
        LLMClientError: API 调用失败。
    """
    prefix = f"[sess:{session_id}] " if session_id else ""
    _log.info("%sLLM 流式调用开始: model=%s, tools=%d, thinking=%s",
              prefix, request.model, len(request.tools) if request.tools else 0, request.thinking)
    payload = _build_payload(request, stream=True)

    # 流式工具调用累积（按 index 合并 delta）
    tc_by_index: dict[int, dict[str, object]] = {}

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT, follow_redirects=True) as client:
        try:
            async with client.stream(
                "POST",
                f"{get_base_url()}{API_CHAT_PATH}",
                headers=_headers(),
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith(SSE_DATA_PREFIX):
                        data_str = line[len(SSE_DATA_PREFIX):]
                        if data_str == SSE_DONE:
                            break
                        try:
                            chunk = cast(dict[str, object], json.loads(data_str))
                            choices_raw = chunk.get("choices", cast(list[dict[str, object]], [{}]))
                            choices_list = cast(list[dict[str, object]], choices_raw)
                            delta = cast(dict[str, object], choices_list[0].get("delta", {}))
                            content = delta.get("content", "")
                            reasoning = delta.get("reasoning_content", "")
                            if reasoning:
                                yield {"type": SSE_REASONING, "content": str(reasoning)}
                            if content:
                                yield {"type": SSE_CONTENT, "content": str(content)}
                            # 累积工具调用 delta
                            for tc_delta in cast(list[dict[str, object]], delta.get("tool_calls") or []):
                                idx = int(str(tc_delta.get("index", 0)))
                                if idx not in tc_by_index:
                                    tc_by_index[idx] = {}
                                cur = tc_by_index[idx]
                                if "id" in tc_delta:
                                    cur["id"] = tc_delta["id"]
                                if "type" in tc_delta:
                                    cur["type"] = tc_delta["type"]
                                fn_delta = tc_delta.get("function")
                                if isinstance(fn_delta, dict):
                                    fn_delta = cast(dict[str, object], fn_delta)
                                    cur_fn = cur.get("function")
                                    if not isinstance(cur_fn, dict):
                                        cur_fn = {}
                                        cur["function"] = cur_fn
                                    cur_fn = cast(dict[str, object], cur_fn)
                                    if "name" in fn_delta:
                                        cur_fn["name"] = fn_delta["name"]
                                    if "arguments" in fn_delta:
                                        cur_fn["arguments"] = str(cur_fn.get("arguments", "")) + str(fn_delta["arguments"])
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

                # 流结束后，如累积了工具调用，yield 出去
                if tc_by_index:
                    tool_calls_list: list[dict[str, object]] = []
                    for idx in sorted(tc_by_index):
                        tc = tc_by_index[idx]
                        if tc.get("id") and tc.get("function"):
                            tool_calls_list.append({
                                "id": str(tc.get("id", "")),
                                "type": str(tc.get("type", "function")),
                                "function": tc["function"],
                            })
                    if tool_calls_list:
                        yield {"type": SSE_TOOL_CALLS, "tool_calls": tool_calls_list}

        except httpx.HTTPStatusError as e:
            _log.warning("%sLLM API 返回错误 %d", prefix, e.response.status_code)
            raise LLMClientError(
                f"LLM API 返回错误 {e.response.status_code}"
            ) from e
        except httpx.RequestError as e:
            _log.warning("%sLLM API 连接失败: %s", prefix, e)
            raise LLMClientError(f"无法连接到 LLM 服务: {e}") from e


async def health_check() -> dict[str, object]:
    """检测 LLM 网关连通性。

    Returns:
        包含状态、地址、默认模型等信息的字典。
    """
    base_url = get_base_url()
    default_model = get_default_model()
    result: dict[str, object] = {
        "status": HEALTH_UNKNOWN,
        "base_url": base_url,
        "default_model": default_model,
    }

    if not default_model:
        result["status"] = HEALTH_NO_DEFAULT_MODEL
        return result

    async with httpx.AsyncClient(timeout=HEALTH_CHECK_TIMEOUT, follow_redirects=True) as client:
        try:
            resp = await client.post(
                f"{base_url}{API_CHAT_PATH}",
                headers=_headers(),
                json={
                    "model": default_model,
                    "messages": [{"role": ROLE_USER, "content": HEALTH_PING_TEXT}],
                    "max_tokens": HEALTH_PING_MAX_TOKENS,
                },
            )
            if resp.is_success:
                result["status"] = HEALTH_HEALTHY
            else:
                result["status"] = HEALTH_UNHEALTHY
                result["error"] = f"HTTP {resp.status_code}: {resp.text[:ERROR_RESULT_TRUNCATE]}"
        except httpx.RequestError as e:
            result["status"] = HEALTH_UNREACHABLE
            result["error"] = str(e)

    _log.info("健康检查: status=%s, base_url=%s", result.get("status"), base_url)
    return result


async def llm_ping() -> bool:
    """轻量 LLM 连通性检查（不消耗 token）。

    仅检查网关是否可达，用于出队时的健康门控。
    """
    base_url = get_base_url()
    if not base_url:
        _log.debug("llm_ping 跳过: base_url 为空")
        return False
    try:
        async with httpx.AsyncClient(timeout=LLM_PING_TIMEOUT) as client:
            resp = await client.get(f"{base_url}{API_MODELS_PATH}", headers=_headers())
            return resp.is_success
    except Exception as e:
        _log.debug("llm_ping 失败: %s", e)
        return False
