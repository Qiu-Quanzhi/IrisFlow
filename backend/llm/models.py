"""LLM 模块数据模型。

定义 Chat、Agent、会话相关的所有 Pydantic 模型。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from llm.constants import DEFAULT_TITLE, MODE_CHAT, STATUS_COMPLETED, STATUS_GENERATING, STATUS_PENDING


class SessionStatus(str, Enum):
    """会话生命周期状态（后端维护）。
    - generating: 正在生成
    - completed: 已完成，可继续发送（含用户主动终止、LLM 错误）
    - pending: 排队等待调度（入队后等待出队）
    """
    GENERATING = STATUS_GENERATING
    COMPLETED = STATUS_COMPLETED
    PENDING = STATUS_PENDING


# ── 会话设定（采样参数 + 系统提示词） ────────────────────


class SessionSettings(BaseModel):
    """会话 LLM 参数设定，可随每条消息更新并持久化到会话中。

    None = 未设置，API 调用时不传该参数，由模型自行决定默认值。
    """

    system_prompt: str | None = Field(default=None, description="系统提示词（None = 使用后端默认）")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0, description="采样温度（None = 模型默认）")
    max_tokens: int | None = Field(default=None, ge=1, le=32768, description="最大输出 token 数（None = 模型默认）")
    top_p: float | None = Field(default=None, ge=0.0, le=1.0, description="核采样")
    top_k: int | None = Field(default=None, ge=1, le=200, description="Top-K 采样")
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0, description="存在惩罚")
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0, description="频率惩罚")
    repeat_penalty: float | None = Field(default=None, ge=0.0, le=2.0, description="重复惩罚")


# ── 聊天消息 ──────────────────────────────────────────────


class ChatMessage(BaseModel):
    """聊天消息。"""

    role: str = Field(description="角色：developer / user / assistant / tool")
    content: str | list[dict[str, object]] = Field(description="消息内容（文本或多模态数组）")  # pyright: ignore[reportMissingTypeArgument]
    tool_call_id: str | None = Field(default=None, description="工具调用 ID（role=tool 时使用）")
    tool_calls: list[dict[str, object]] | None = Field(  # pyright: ignore[reportMissingTypeArgument]
        default=None,
        description="工具调用列表（role=assistant 时使用）",
    )
    reasoning_content: str | None = Field(
        default=None,
        description="模型思考过程内容（role=assistant 时使用）",
    )
    message_status: str | None = Field(
        default=None,
        description="本轮对话状态（role=assistant 时使用）：queued / generating / completed / aborted",
    )
    thinking: bool = Field(
        default=False,
        description="本轮对话是否启用了思考模式（role=assistant 时使用）",
    )
    is_error: bool = Field(
        default=False,
        description="该工具结果是否为错误（role=tool 时使用，后端权威）",
    )


# ── 工具定义 ──────────────────────────────────────────────


class ToolDefinition(BaseModel):
    """工具（函数）定义。

    对应 OpenAI function calling 的 tool schema。
    """

    name: str = Field(description="函数名")
    description: str = Field(description="函数描述，供模型判断何时调用")
    parameters: dict[str, object] = Field(  # pyright: ignore[reportMissingTypeArgument]
        description="函数参数的 JSON Schema",
    )


# ── 聊天请求 / 响应 ──────────────────────────────────────


class ChatRequest(BaseModel):
    """无状态聊天请求。"""

    model: str = Field(description="模型 ID")
    messages: list[ChatMessage] = Field(description="对话消息列表")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0, description="采样温度")
    max_tokens: int | None = Field(default=None, ge=1, le=32768, description="最大输出 token 数")
    top_p: float | None = Field(default=None, ge=0.0, le=1.0, description="核采样")
    top_k: int | None = Field(default=None, ge=1, le=200, description="Top-K 采样")
    presence_penalty: float | None = Field(default=None, ge=-2.0, le=2.0, description="存在惩罚")
    frequency_penalty: float | None = Field(default=None, ge=-2.0, le=2.0, description="频率惩罚")
    repeat_penalty: float | None = Field(default=None, ge=0.0, le=2.0, description="重复惩罚")
    tools: list[ToolDefinition] | None = Field(
        default=None,
        description="可用的工具列表（Agent 模式）",
    )
    thinking: bool = Field(
        default=False,
        description="是否启用模型思考过程（reasoning_content）",
    )


class ChatResponse(BaseModel):
    """聊天响应。"""

    model: str = Field(description="实际使用的模型")
    content: str = Field(description="模型回复内容")
    finish_reason: str | None = Field(
        default=None,
        description="结束原因：stop / length / tool_calls",
    )
    tool_calls: list[dict[str, object]] | None = Field(  # pyright: ignore[reportMissingTypeArgument]
        default=None,
        description="模型请求调用的工具列表",
    )
    reasoning_content: str | None = Field(
        default=None,
        description="模型思考过程内容（启用 thinking 时返回）",
    )
    usage: dict[str, object] = Field(  # pyright: ignore[reportMissingTypeArgument,reportUnknownVariableType]
        default_factory=dict,
        description="token 用量统计",
    )


# ── Agent 请求 / 响应 ─────────────────────────────────────


class ToolCallRecord(BaseModel):
    """单次工具调用记录。"""

    id: str = Field(description="工具调用 ID")
    name: str = Field(description="工具名")
    arguments: dict[str, object] = Field(  # pyright: ignore[reportMissingTypeArgument]
        description="模型生成的参数"
    )
    result: str | None = Field(default=None, description="工具执行结果（客户端回传）")


class AgentResponse(BaseModel):
    """Agent 对话响应。"""

    model: str = Field(description="使用的模型")
    content: str = Field(description="最终回复内容")
    session_id: str | None = Field(
        default=None,
        description="Agent 会话 ID（需要继续推理时返回）",
    )
    tool_calls: list[ToolCallRecord] = Field(  # pyright: ignore[reportUnknownVariableType]
        default_factory=list,
        description="工具调用历史",
    )
    iterations: int = Field(description="实际推理迭代次数")
    finish_reason: str | None = Field(default=None, description="结束原因")
    usage: dict[str, object] = Field(  # pyright: ignore[reportMissingTypeArgument,reportUnknownVariableType]
        default_factory=dict,
        description="token 用量统计",
    )


# ── 工具结果回传（多轮 Agent 交互） ──────────────────────


class ToolResult(BaseModel):
    """工具执行结果。"""

    id: str = Field(description="对应的工具调用 ID")
    name: str = Field(description="工具名")
    result: str = Field(description="工具执行返回的文本结果")


class AgentContinueRequest(BaseModel):
    """Agent 继续对话请求（携带工具执行结果）。"""

    session_id: str = Field(description="Agent 会话 ID")
    model: str = Field(description="模型 ID")
    tool_results: list[ToolResult] = Field(description="工具执行结果列表")


# ── 会话模型 ──────────────────────────────────────────────


class ConversationCreateRequest(BaseModel):
    """创建会话请求。"""

    model: str = Field(description="模型 ID")
    system_prompt: str | None = Field(default=None, description="可选的系统提示词")
    title: str = Field(default=DEFAULT_TITLE, description="会话标题")
    mode: str = Field(default=MODE_CHAT, description="会话模式：chat / agent")
    settings: SessionSettings | None = Field(default=None, description="会话 LLM 参数设定")


class ConversationMessageRequest(BaseModel):
    """向已有会话发送消息的请求。"""

    content: str | list[dict[str, object]] = Field(description="消息内容（文本或多模态数组）")  # pyright: ignore[reportMissingTypeArgument]
    thinking: bool = Field(default=False, description="是否启用模型思考过程")
    tool_names: list[str] | None = Field(
        default=None, description="启用的工具名称列表（仅限后端已注册的工具）"
    )
    settings: SessionSettings | None = Field(default=None, description="会话 LLM 参数设定（覆盖会话存储值）")


class ConversationUpdateRequest(BaseModel):
    """更新会话的请求（如修改标题、置顶）。"""

    title: str | None = Field(default=None, description="新的会话标题")
    pinned: bool | None = Field(default=None, description="是否置顶")


class ConversationResponse(BaseModel):
    """会话回复。"""

    session_id: str = Field(description="会话 ID")
    model: str = Field(description="使用的模型")
    content: str = Field(description="模型回复内容")
    usage: dict[str, object] = Field(  # pyright: ignore[reportMissingTypeArgument,reportUnknownVariableType]
        default_factory=dict,
        description="token 用量统计",
    )


class ConversationInfo(BaseModel):
    """会话摘要信息（内部使用，含状态）。"""

    session_id: str = Field(description="会话 ID")
    model: str = Field(description="使用的模型")
    title: str = Field(default=DEFAULT_TITLE, description="会话标题")
    mode: str = Field(default=MODE_CHAT, description="会话模式：chat / agent")
    message_count: int = Field(description="消息轮数（不含 system prompt）")
    status: SessionStatus = Field(default=SessionStatus.COMPLETED, description="会话状态")
    pinned: bool = Field(default=False, description="是否置顶")
    created_at: str = Field(description="创建时间 ISO 格式")
    last_access: str = Field(default="", description="最近活动时间 ISO 格式")


class ConversationListItem(BaseModel):
    """会话列表项（不含状态 — 状态通过 SSE 订阅获取）。"""

    session_id: str = Field(description="会话 ID")
    model: str = Field(description="使用的模型")
    title: str = Field(default=DEFAULT_TITLE, description="会话标题")
    mode: str = Field(default=MODE_CHAT, description="会话模式：chat / agent")
    message_count: int = Field(description="消息轮数（不含 system prompt）")
    pinned: bool = Field(default=False, description="是否置顶")
    created_at: str = Field(description="创建时间 ISO 格式")
    last_access: str = Field(default="", description="最近活动时间 ISO 格式")


class ConversationDetail(BaseModel):
    """会话详情（含完整消息历史）。"""

    session_id: str = Field(description="会话 ID")
    model: str = Field(description="使用的模型")
    messages: list[ChatMessage] = Field(description="完整消息历史")
    status: SessionStatus = Field(default=SessionStatus.COMPLETED, description="会话状态")
    created_at: str = Field(description="创建时间 ISO 格式")
    settings: SessionSettings | None = Field(default=None, description="会话 LLM 参数设定")


class ConversationListResponse(BaseModel):
    """会话列表（不含状态 — 状态通过 SSE 订阅获取）。"""

    conversations: list[ConversationListItem] = Field(description="活跃会话列表")
