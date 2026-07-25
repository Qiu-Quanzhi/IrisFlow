"""Chat 类 — Agent 的基础设施。

封装消息历史管理。Agent 和会话管理均构建于此基类之上。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from llm.constants import ROLE_SYSTEM
from llm.models import ChatMessage

if TYPE_CHECKING:
    from llm.models import SessionSettings

_log = logging.getLogger(__name__)


class Chat:
    """LLM 聊天实例 — 消息历史容器。

    用法::

        chat = Chat(model="gemini-3.1-flash-lite", system_prompt="你是助手")
        chat.messages.append(ChatMessage(role="user", content="你好"))
    """

    def __init__(
        self,
        model: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        presence_penalty: float | None = None,
        frequency_penalty: float | None = None,
        repeat_penalty: float | None = None,
    ) -> None:
        self.model = model
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.top_k = top_k
        self.presence_penalty = presence_penalty
        self.frequency_penalty = frequency_penalty
        self.repeat_penalty = repeat_penalty
        self.messages: list[ChatMessage] = []
        if system_prompt is not None:
            self.messages.append(ChatMessage(role=ROLE_SYSTEM, content=system_prompt))
        _log.debug("Chat 创建: model=%s", model)

    def apply_settings(self, settings: "SessionSettings") -> None:
        """从 SessionSettings 同步所有采样参数。

        None = 不设该参数，由模型自行决定默认值。
        系统提示词的追加由调用方（router）负责。
        """
        for key in ("temperature", "max_tokens", "top_p", "top_k",
                     "presence_penalty", "frequency_penalty", "repeat_penalty"):
            setattr(self, key, getattr(settings, key))
