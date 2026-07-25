"""Agent 类 — 工具调用推理循环。

继承 Chat，增加工具定义与推理循环。
工具由调用方注入并执行，Agent 只负责与 LLM 的交互循环。
"""

from __future__ import annotations

import logging

from typing import cast

from llm.chat import Chat
from llm.client import chat as client_chat
from llm.client import parse_tool_call_for_display
from llm.constants import ROLE_ASSISTANT, ROLE_TOOL
from llm.models import (
    AgentResponse,
    ChatMessage,
    ChatRequest,
    ToolCallRecord,
    ToolDefinition,
    ToolResult,
)

_log = logging.getLogger(__name__)


class Agent(Chat):
    """LLM Agent — 具备工具调用能力的聊天实例。

    继承 Chat，增加工具定义注入与多轮工具推理循环。
    支持自定义工具（前端手动执行）的暂停-继续流程。

    用法::

        agent = Agent(
            model="gemini-3.1-flash-lite",
            system_prompt="你是研究助手",
            tools=[ToolDefinition(name="search", ...)],
        )
        # ... 发送消息后收到 tool_calls ...
        response = await agent.continue_with_results(results)
    """

    def __init__(
        self,
        model: str,
        system_prompt: str | None = None,
        tools: list[ToolDefinition] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_iterations: int = 10,
        top_p: float | None = None,
        top_k: int | None = None,
        presence_penalty: float | None = None,
        frequency_penalty: float | None = None,
        repeat_penalty: float | None = None,
    ) -> None:
        super().__init__(model, system_prompt, temperature, max_tokens,
                         top_p, top_k, presence_penalty, frequency_penalty,
                         repeat_penalty)
        self.tools = tools or []
        self.max_iterations = max_iterations

    # ── 继续推理（携带工具结果） ────────────────────────

    async def continue_with_results(
        self, tool_results: list[ToolResult]
    ) -> AgentResponse:
        """将工具执行结果回传给模型，继续推理。

        Args:
            tool_results: 工具执行的结果列表。

        Returns:
            AgentResponse: 模型的下一个回复。
        """
        # 添加 tool result 消息
        for tr in tool_results:
            self.messages.append(ChatMessage(
                role=ROLE_TOOL,
                content=tr.result,
                tool_call_id=tr.id,
            ))

        tool_calls_history: list[ToolCallRecord] = []
        total_usage: dict[str, object] = {}
        iterations = 0

        for _ in range(self.max_iterations):
            iterations += 1
            _log.info("Agent 迭代 %d/%d: model=%s, tools=%d",
                      iterations, self.max_iterations, self.model, len(self.tools))
            request = ChatRequest(
                model=self.model,
                messages=list(self.messages),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                tools=self.tools if self.tools else None,
            )
            response = await client_chat(request)
            total_usage = _merge_usage(total_usage, response.usage)

            if response.tool_calls:
                for tc in response.tool_calls:
                    tool_calls_history.append(_make_tool_record(tc))

                _log.info("Agent 收到 %d 个工具调用: %s",
                          len(response.tool_calls),
                          [_tc_name(tc) for tc in response.tool_calls])
                self.messages.append(ChatMessage(
                    role=ROLE_ASSISTANT,
                    content=response.content or "",
                    tool_calls=response.tool_calls,
                ))
                return AgentResponse(
                    model=self.model,
                    content=response.content or "",
                    tool_calls=tool_calls_history,
                    iterations=iterations,
                    finish_reason="tool_calls",
                    usage=total_usage,
                )

            self.messages.append(ChatMessage(role=ROLE_ASSISTANT, content=response.content))
            _log.info("Agent 完成: finish_reason=%s, iterations=%d",
                      response.finish_reason or "stop", iterations)
            return AgentResponse(
                model=self.model,
                content=response.content,
                tool_calls=tool_calls_history,
                iterations=iterations,
                finish_reason=response.finish_reason or "stop",
                usage=total_usage,
            )

        _log.warning("Agent 达到最大迭代次数 (%d) 未完成", self.max_iterations)
        return AgentResponse(
            model=self.model,
            content="",
            tool_calls=tool_calls_history,
            iterations=iterations,
            finish_reason="max_iterations",
            usage=total_usage,
        )


# ── 辅助函数 ──────────────────────────────────────────────



def _tc_name(tc: dict[str, object]) -> str:
    """从 tool call dict 提取工具名，用于日志。"""
    fn = tc.get("function")
    if isinstance(fn, dict):
        fn = cast(dict[str, object], fn)
        return str(fn.get("name", "?"))
    return "?"


def _make_tool_record(tc: dict[str, object]) -> ToolCallRecord:
    """从 API 格式的 tool call dict 构造 ToolCallRecord。"""
    tc_id, name, arguments = parse_tool_call_for_display(tc)
    return ToolCallRecord(
        id=tc_id,
        name=name,
        arguments=arguments,
    )


def _merge_usage(
    a: dict[str, object], b: dict[str, object]
) -> dict[str, object]:
    """合并两次 API 调用的 usage 统计（简单累加）。"""
    if not a:
        return dict(b)
    if not b:
        return dict(a)
    result = dict(a)
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if key in b:
            result[key] = int(str(result.get(key, 0))) + int(str(b.get(key, 0)))
    return result
