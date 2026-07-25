"""IRIS LLM — 统一 LLM 调用模块。

提供 Chat、Agent、会话管理，作为整个系统的 Agent 基础设施。

- Chat  — LLM 对话基类（消息历史 + 流式/非流式调用）
- Agent — 工具调用推理循环
- router — REST API 端点

用法::

    from llm import Chat, Agent

    chat = Chat(model="gemini-3.1-flash-lite", system_prompt="你是助手")
    response = await chat.send("你好")

    agent = Agent(model="...", tools=[...])
    response = await agent.run("搜索最新论文")
"""

from llm.agent import Agent  # noqa: F401
from llm.chat import Chat  # noqa: F401
from llm.router import router  # noqa: F401

__all__ = ["Chat", "Agent", "router"]
