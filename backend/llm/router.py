"""LLM 模块路由。

提供 Chat、Agent、会话管理、健康检查等全部 REST 端点。
"""

import asyncio
import json
import logging
import time as _time
from collections import deque
from typing import cast

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

_log = logging.getLogger("llm.router")

from llm.client import LLMClientError, chat as llm_chat, chat_stream_events, health_check, llm_ping, parse_tool_call_for_display
from llm.agent import Agent
from llm.chat import Chat
from llm.constants import (
    AGENT_SESSION_TTL,
    CLEANUP_DELAY,
    DEFAULT_TITLE,
    MAX_PENDING_QUEUE,
    LLM_RECOVERY_POLL_INTERVAL,
    MCP_KEY_MCP_SERVERS,
    MSG_QUEUED,
    MSG_GENERATING,
    MSG_BUILTIN_GROUP,
    MSG_COMPLETED,
    MSG_ABORTED,
    RESPONSE_KEY_OK,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
    ROLE_TOOL,
    SHUTDOWN_TASK_WAIT,
    SSE_CONTENT,
    SSE_DONE,
    SSE_ERROR,
    SSE_MEDIA_TYPE,
    SSE_HEARTBEAT_INTERVAL,
    SSE_REASONING,
    SSE_STATUS,
    SSE_TITLE,
    SSE_TOOL_CALL,
    SSE_TOOL_CALLS,
    SSE_TOOL_RESULT,
    STATUS_COMPLETED,
    STATUS_REPLACED,
    STATUS_UNKNOWN,
    TITLE_CHAR_WINDOW,
    TITLE_MAX_LENGTH,
    TITLE_MESSAGE_WINDOW,
    TITLE_MODEL_MAX_TOKENS,
    TITLE_MODEL_TEMP,
)
from llm.uploads import process_upload, get_upload_config, UploadConfigResponse
from llm.tools import tool_executor

from llm.models import (
    AgentContinueRequest,
    AgentResponse,
    ChatMessage,
    ChatRequest,
    ConversationCreateRequest,
    ConversationDetail,
    ConversationListItem,
    ConversationListResponse,
    ConversationMessageRequest,
    ConversationResponse,
    ConversationUpdateRequest,
    SessionSettings,
    SessionStatus,
    ToolDefinition,
)
from llm.sessions import session_store
from core.config import (
    apply_default_session_settings,
    apply_llm_overrides,
    apply_mcp_config_text,
    apply_secrets,
    get_base_url,
    get_default_model,
    get_default_session_settings,
    get_max_concurrent,
    get_mcp_config_text,
    get_raw_auth_token,
    get_secrets_keys,
)
from llm.mcp import mcp_manager
from llm.tools import tool_executor, BUILTIN_TOOLS

router = APIRouter(tags=["LLM"])


# ── 生成状态注册表 ────────────────────────────────────────
# 后台 Task 生成的事件存入此表，前端刷新后可订阅续传 SSE 流。

class _GenerationState:
    """一个会话的活跃生成状态。"""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []  # 完整事件历史
        self.condition = asyncio.Condition()       # 新事件通知
        self.finished = False                      # 生成是否已结束
        self.client_disconnected = False           # 主 SSE 客户端是否已断开（用户终止/刷新）
        self.session_deleted = False               # 会话是否已被删除（finally 块跳过 register）
        self.task: asyncio.Task[None] | None = None  # 后台生成 Task，用于取消


_active_generations: dict[str, _GenerationState] = {}

# ── 待调度队列 ─────────────────────────────────────────────
# 并发满时新请求入队排队，而非直接拒绝。
# 队列元素: (session_id, chat, request, state)

_pending_queue: deque[tuple[str, "Chat", "ConversationMessageRequest", _GenerationState]] = deque()
_queue_lock = asyncio.Lock()
_active_generation_count = 0  # 当前活跃生成数（由 _queue_lock 保护）

# ── 状态广播 ───────────────────────────────────────────────
# session_id → [subscriber queues]，每次状态变更推送给订阅者。

_status_subscribers: dict[str, list["asyncio.Queue[dict[str, object]]"]] = {}
_status_subscribers_lock = asyncio.Lock()  # 保护 _status_subscribers 的读写

# ── 有序关闭标志 ──────────────────────────────────────────
# 置位后禁止新任务启动，阻止 finally 块中的 _dequeue_and_start 启动新 task。

_shutting_down = False

# LLM 健康状态 — 连接错误时置 False，恢复后置 True
_llm_healthy = True
_recovery_task: "asyncio.Task[None] | None" = None

# 待取消的延迟清理任务（_cleanup_generation_state 创建的 asyncio.sleep 任务）
_delayed_cleanup_tasks: set[asyncio.Task[None]] = set()


async def _update_and_broadcast(session_id: str, status: str) -> None:
    """更新会话状态并推送所有 SSE 订阅者（含 last_access 以便前端重排）。"""
    last_access = await session_store.update_status(session_id, status)
    async with _status_subscribers_lock:
        # 拷贝队列引用后释放锁，避免在锁内 await put（可能阻塞）
        queues = list(_status_subscribers.get(session_id, []))
    if queues:
        payload: dict[str, object] = {
            "type": SSE_STATUS, "session_id": session_id, "status": status,
            "last_access": last_access,
        }
        for q in queues:
            await q.put(payload)


def _resolve_assistant_statuses(chat: Chat, from_statuses: frozenset[str | None], to_status: str) -> None:
    """将 chat 中所有处于 from_statuses 中任一状态的 assistant 消息标记为 to_status。

    重要：自动工具调用循环会产生多条 assistant 消息（首条含 tool_calls，
    末条含最终回复），必须全部标记，否则前端 loadHistory 会渲染出重复的
    WorkflowLog（前一条卡在 generating → streamDone=false → 额外 WorkflowLog）。
    """
    for msg in chat.messages:
        if msg.role == ROLE_ASSISTANT and msg.message_status in from_statuses:
            msg.message_status = to_status


async def _cleanup_stale_agents() -> None:
    """清理空闲超时的 Agent 会话（自定义工具暂停后长期未续接）。"""
    now = _time.time()
    stale = [
        sid for sid, ts in _agent_sessions_ts.items()
        if now - ts > AGENT_SESSION_TTL
    ]
    for sid in stale:
        _agent_sessions.pop(sid, None)
        _agent_sessions_ts.pop(sid, None)
        _log.info("[sess:%s] Agent 会话空闲超时，已清理", sid)


async def _dequeue_and_start() -> None:
    """从待调度队列取队首并启动生成。

    触发时机：_generate finally、LLM 恢复、新会话入队。
    """
    global _llm_healthy, _active_generation_count
    if _shutting_down:
        return
    # 周期性清理过期 Agent 会话
    await _cleanup_stale_agents()
    # LLM 不可达 → 不出队，启动恢复轮询。
    # 必须主动 ping，不能仅信任 _llm_healthy 标志（初始为 True，但 LLM 可能已断连）。
    if not _llm_healthy or not await llm_ping():
        if _llm_healthy:
            _llm_healthy = False  # 标记不可达，避免后续重复 ping
            _log.warning("LLM 不可达，暂停出队，启动恢复轮询")
        await _schedule_llm_recovery()
        return
    async with _queue_lock:
        if not _pending_queue:
            return
        if _active_generation_count >= get_max_concurrent():
            return  # 仍在并发上限
        sid, chat, req, state = _pending_queue.popleft()
        _active_generation_count += 1
    _log.info("[sess:%s] 出队调度: queue_size=%d, active=%d",
              sid, len(_pending_queue), _active_generation_count)
    # 更新状态 → generating；广播给侧栏 + 写入事件流供 SSE 消费
    # 更新 assistant 消息的 message_status：queued → generating
    _resolve_assistant_statuses(chat, frozenset({MSG_QUEUED}), MSG_GENERATING)
    await _update_and_broadcast(sid, SessionStatus.GENERATING.value)
    async with state.condition:
        state.events.append({"type": SSE_STATUS, "status": SessionStatus.GENERATING.value})
        state.condition.notify_all()
    state.task = asyncio.create_task(_generate(sid, chat, req, state))


async def _schedule_llm_recovery() -> None:
    """LLM 不可达时后台轮询恢复，成功后触发出队。"""
    global _llm_healthy, _recovery_task
    if _recovery_task and not _recovery_task.done():
        return  # 已有恢复任务在运行

    async def _poll() -> None:
        global _llm_healthy
        while not _llm_healthy:
            await asyncio.sleep(LLM_RECOVERY_POLL_INTERVAL)
            if await llm_ping():
                _llm_healthy = True
                _log.info("LLM 已恢复，触发出队")
                await _dequeue_and_start()

    _recovery_task = asyncio.create_task(_poll())


# ── 后台 LLM 生成（独立函数，供 send_message_stream 与队列共用）───


async def _generate(
    session_id: str,
    chat: Chat,
    request: ConversationMessageRequest,
    state: _GenerationState,
) -> None:
    """后台 LLM 生成 — 独立于 HTTP 连接生命周期。"""

    _log.info("[sess:%s] 生成开始: model=%s, thinking=%s, tools=%s",
              session_id, chat.model, request.thinking,
              len(request.tool_names) if request.tool_names else 0)

    async def _emit(event: dict[str, object]) -> None:
        """向事件列表追加事件并通知所有等待者。"""
        async with state.condition:
            state.events.append(event)
            state.condition.notify_all()

    pending_custom_tools = False  # True when custom tools yielded → don't set COMPLETED
    try:
        # send_message_stream 已创建 assistant 消息（含 message_status + thinking），
        # 首轮迭代复用该消息；后续自动工具调用轮次仍需创建新 assistant 消息。
        first_iteration = True
        while True:
            is_first = first_iteration
            if first_iteration:
                # 复用 send_message_stream 预创建的 assistant 消息
                assistant_msg = chat.messages[-1]
                if assistant_msg.role != ROLE_ASSISTANT:
                    # 防御：若最后一条不是 assistant（不应发生），退化为新建
                    assistant_msg = ChatMessage(
                        role=ROLE_ASSISTANT, content="",
                        message_status=MSG_GENERATING, thinking=request.thinking,
                    )
                    chat.messages.append(assistant_msg)
                first_iteration = False
            else:
                assistant_msg = ChatMessage(
                    role=ROLE_ASSISTANT, content="",
                    message_status=MSG_GENERATING, thinking=request.thinking,
                )
                chat.messages.append(assistant_msg)

            resolved_tools = tool_executor.get_definitions_by_names(request.tool_names or []) or None
            # 首轮迭代：排除 send_message_stream 预创建的空 assistant 占位消息，
            # 避免将 content="" 的 assistant 消息发送给 LLM API。
            api_messages = list(chat.messages[:-1]) if is_first else list(chat.messages)
            chat_request = ChatRequest(
                model=chat.model,
                messages=api_messages,
                temperature=chat.temperature,
                max_tokens=chat.max_tokens,
                top_p=chat.top_p,
                top_k=chat.top_k,
                presence_penalty=chat.presence_penalty,
                frequency_penalty=chat.frequency_penalty,
                repeat_penalty=chat.repeat_penalty,
                thinking=request.thinking,
                tools=resolved_tools,
            )

            got_auto_tools = False

            async for event in chat_stream_events(chat_request, session_id=session_id):
                if event["type"] == SSE_CONTENT:
                    await _emit(event)
                    assistant_msg.content = str(assistant_msg.content or "") + str(event.get("content", ""))  # type: ignore[assignment]
                elif event["type"] == SSE_REASONING:
                    await _emit(event)
                    assistant_msg.reasoning_content = (assistant_msg.reasoning_content or "") + str(event.get("content", ""))
                elif event["type"] == SSE_TOOL_CALLS and resolved_tools:
                    raw_tcs: list[dict[str, object]] = event["tool_calls"]  # type: ignore[assignment]
                    all_exec = True
                    for tc in raw_tcs:
                        _, name, _ = parse_tool_call_for_display(tc)
                        if not tool_executor.can_execute(name):
                            all_exec = False
                            break

                    if all_exec:
                        got_auto_tools = True
                        _log.info("[sess:%s] 自动工具调用: %d 个工具",
                                  session_id, len(raw_tcs))
                        assistant_msg.tool_calls = list(raw_tcs)  # type: ignore[assignment]
                        for tc in raw_tcs:
                            tc_id, name, args = parse_tool_call_for_display(tc)
                            _log.debug("[sess:%s] 执行工具: %s(%s)", session_id, name, args)
                            await _emit({"type": SSE_TOOL_CALL, "name": name, "arguments": args})
                            result_text, is_error = await tool_executor.execute(name, args)
                            await _emit({"type": SSE_TOOL_RESULT, "name": name, "result": result_text, "is_error": is_error})
                            chat.messages.append(ChatMessage(
                                role=ROLE_TOOL, content=result_text, tool_call_id=tc_id, is_error=is_error,
                            ))
                        break
                    else:
                        # 自定义工具 → 暂停等待手动执行
                        pending_custom_tools = True
                        _log.info("[sess:%s] 自定义工具暂停: %d 个工具待手动执行",
                                  session_id, len(raw_tcs))
                        assistant_msg.tool_calls = list(raw_tcs)  # type: ignore[assignment]
                        agent = Agent(
                            model=chat.model,
                            tools=resolved_tools or [],
                            temperature=chat.temperature,
                            max_tokens=chat.max_tokens,
                            top_p=chat.top_p,
                            top_k=chat.top_k,
                            presence_penalty=chat.presence_penalty,
                            frequency_penalty=chat.frequency_penalty,
                            repeat_penalty=chat.repeat_penalty,
                        )
                        agent.messages = list(chat.messages)
                        _agent_sessions[session_id] = agent
                        _agent_sessions_ts[session_id] = _time.time()
                        event = dict(event)
                        event["session_id"] = session_id
                        await _emit(event)
                else:
                    await _emit(event)  # 透传未知事件类型

            if got_auto_tools:
                continue

            break

        if not pending_custom_tools:
            # 自动生成标题（仅首次，title 为默认值时）
            current_title = await session_store.get_title(session_id)
            if current_title == DEFAULT_TITLE:
                new_title = await _auto_title(chat.model, chat.messages)
                if new_title and new_title != DEFAULT_TITLE:
                    await session_store.update(session_id, new_title)
                    await _emit({"type": SSE_TITLE, "title": new_title})

            _log.info("[sess:%s] 生成完成: messages=%d", session_id, len(chat.messages))
            await _update_and_broadcast(session_id, SessionStatus.COMPLETED.value)
            # 标记本轮所有 assistant 对话为正常完成（自动工具调用会产生多条 assistant）
            _resolve_assistant_statuses(chat, frozenset({MSG_GENERATING, MSG_QUEUED, None}), MSG_COMPLETED)
        # else: 自定义工具等待用户手动执行，保持 GENERATING 状态
    except asyncio.CancelledError:
        # 用户点击停止 → state.client_disconnected 已在 abort 端点设置
        # 不 emit 错误事件，静默退出；finally 块负责持久化
        _log.info("[sess:%s] 生成被用户取消", session_id)
        _resolve_assistant_statuses(chat, frozenset({MSG_GENERATING, MSG_QUEUED}), MSG_ABORTED)
        pass
    except Exception as e:
        _log.warning("[sess:%s] 生成异常: %s", session_id, e)
        # 连接错误 → LLM 可能不可达，触发恢复轮询
        if isinstance(e, LLMClientError) and "无法连接到" in str(e):
            global _llm_healthy
            _llm_healthy = False
            _log.warning("[sess:%s] LLM 不可达，启动恢复轮询", session_id)
            await _schedule_llm_recovery()
        # 标记本轮 assistant 消息为终止（不注入错误文本 — 消息是用户数据，不应被错误接管篡改）
        _resolve_assistant_statuses(chat, frozenset({MSG_GENERATING, MSG_QUEUED, None}), MSG_ABORTED)
        # SSE_ERROR 是实时通知，不持久化到消息历史
        # 避免泄露内部细节：仅发送错误类型，不含原始异常字符串
        error_content = "LLM 连接失败，请检查网关状态" if isinstance(e, LLMClientError) else "生成过程发生错误，请重试"
        await _emit({"type": SSE_ERROR, "content": error_content})
    finally:
        # 释放并发槽位（_active_generation_count 由 _queue_lock 保护）
        global _active_generation_count
        async with _queue_lock:
            _active_generation_count = max(0, _active_generation_count - 1)
        async with state.condition:
            state.finished = True
            # 释放事件缓冲区：新订阅者从 cursor=len(events) 开始，不需要历史事件
            state.events.clear()
            state.condition.notify_all()
        # shield() 保护持久化不被任务取消信号打断
        try:
            if not state.session_deleted:
                await asyncio.shield(session_store.register(session_id, chat))
                # 统一为 COMPLETED（不再区分错误原因、客户端断开等）
                if not pending_custom_tools:
                    await asyncio.shield(
                        _update_and_broadcast(session_id, SessionStatus.COMPLETED.value))
        except asyncio.CancelledError:
            pass  # 取消信号已在 asyncio.shield() 内部处理
        # 延迟清除注册表，给页面刷新留重连窗口
        if not _shutting_down:
            t = asyncio.create_task(_cleanup_generation_state(session_id, state))
            _delayed_cleanup_tasks.add(t)
            t.add_done_callback(_delayed_cleanup_tasks.discard)
        # 处理队列中下一个待调度会话
        await _dequeue_and_start()


async def _cleanup_generation_state(session_id: str, state: _GenerationState, delay: float = CLEANUP_DELAY) -> None:
    """延迟清除生成状态，给页面刷新留出重连窗口。

    通过对象身份（is）判断：仅当注册表中的状态仍是入参的同一对象时才清理。
    防止旧轮次清理任务误删同 session_id 的新轮次状态。
    """
    await asyncio.sleep(delay)
    if _active_generations.get(session_id) is state:
        _active_generations.pop(session_id, None)


async def _auto_title(model: str, messages: list[ChatMessage]) -> str:
    """调用 LLM 生成简短会话标题。

    参考 Qwen Code 的设计：过滤对话历史取尾部 1000 字符，
    用结构化输出（function calling）确保格式正确。
    """
    try:
        # 过滤：仅保留 user/assistant 有内容的文本消息
        filtered: list[ChatMessage] = []
        for m in messages:
            if m.role in (ROLE_USER, ROLE_ASSISTANT) and m.content:
                content = m.content if isinstance(m.content, str) else ""
                if content.strip():
                    filtered.append(ChatMessage(role=m.role, content=content))

        # 取最近的消息，截断到约 1000 字符
        dialog_lines: list[str] = []
        total = 0
        for m in reversed(filtered[-TITLE_MESSAGE_WINDOW:]):
            text = f"{'用户' if m.role == ROLE_USER else '助手'}: {m.content}"
            if total + len(text) > TITLE_CHAR_WINDOW:
                dialog_lines.insert(0, text[:TITLE_CHAR_WINDOW - total] + "…")
                break
            dialog_lines.insert(0, text)
            total += len(text)

        history_text = "\n".join(dialog_lines)
        if not history_text.strip():
            return DEFAULT_TITLE

        req = ChatRequest(
            model=model,
            messages=[
                ChatMessage(role=ROLE_SYSTEM, content="""你是一个会话标题生成器。为以下对话生成一个简洁的标题（3-7词，仅首字母和专有名词大写；中文约6-15字）。
要求：
- 描述用户的真实目标，不要泛泛而谈
- 无末尾标点、无引号、无 Markdown
- 与对话主要语言一致
好的例子：修复登录按钮样式、Add dark mode toggle、Debug Redis connection pool
坏的例子：代码修改、some changes、Add feature to the application.、关于XX的讨论"""),
                ChatMessage(role=ROLE_USER, content=history_text),
            ],
            tools=[
                ToolDefinition(
                    name="set_title",
                    description="设置会话标题",
                    parameters={
                        "type": "object",
                        "properties": {"title": {"type": "string", "description": "3-7词或6-15字的标题"}},
                        "required": ["title"],
                    },
                )
            ],
            temperature=TITLE_MODEL_TEMP, max_tokens=TITLE_MODEL_MAX_TOKENS, thinking=False,
        )
        resp = await llm_chat(req)
        if resp.tool_calls and len(resp.tool_calls) > 0:
            _, _, args = parse_tool_call_for_display(resp.tool_calls[0])
            title = str(args.get("title", "")).strip()[:TITLE_MAX_LENGTH]
            # 清理：去引号、去末尾标点
            title = title.strip("\"'「」\"\"''。.！!？?、,，")
            return title if title else DEFAULT_TITLE
        # 回退：从文本提取
        content = resp.content.strip()
        for line in content.split("\n"):
            line = line.strip("\"'「」\"\"''。.！!？?、,，-—")
            if line and len(line) >= 2:
                return line[:TITLE_MAX_LENGTH]
        return DEFAULT_TITLE
    except Exception:
        return DEFAULT_TITLE


# ── 健康检查 ─────────────────────────────────────────────


@router.get("/api/health")
async def llm_health() -> dict[str, object]:
    """LLM 网关连通性探活。"""
    return await health_check()


# ── 会话管理 ──────────────────────────────────────────────


@router.post("/api/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(request: ConversationCreateRequest) -> ConversationResponse:
    """创建新会话。"""
    try:
        # 构建 settings：请求提供 > 后端默认（None 表示由模型决定）
        if request.settings:
            settings = request.settings
        elif request.system_prompt:
            # 旧字段兼容：仅有 system_prompt 时构建最小 settings
            settings = SessionSettings(system_prompt=request.system_prompt)
        else:
            d = get_default_session_settings()
            settings = SessionSettings(
                system_prompt=d.get("system_prompt"),  # type: ignore[arg-type]
                temperature=d.get("temperature"),  # type: ignore[arg-type]
                max_tokens=d.get("max_tokens"),  # type: ignore[arg-type]
                top_p=d.get("top_p"),  # type: ignore[arg-type]
                top_k=d.get("top_k"),  # type: ignore[arg-type]
                presence_penalty=d.get("presence_penalty"),  # type: ignore[arg-type]
                frequency_penalty=d.get("frequency_penalty"),  # type: ignore[arg-type]
                repeat_penalty=d.get("repeat_penalty"),  # type: ignore[arg-type]
            )
        sid = await session_store.create(
            request.model, settings.system_prompt,
            title=request.title, mode=request.mode,
            settings=settings,
        )
        _log.info("[sess:%s] 会话创建: model=%s, mode=%s", sid, request.model, request.mode)
        return ConversationResponse(
            session_id=sid,
            model=request.model,
            content="",
            usage={},
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/conversations/{session_id}/messages/stream")
async def send_message_stream(session_id: str, request: ConversationMessageRequest) -> StreamingResponse:
    """在已有会话中发送消息（流式 SSE），自动拼接上下文。

    支持 thinking、工具自动执行。
    流式过程中消息实时写入会话历史，
    GET /api/conversations/{id} 可随时获取最新状态。
    """
    chat = await session_store.get_chat(session_id)
    if chat is None:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")

    # ── 先验证，后修改 ── 避免 409/503 拒绝后 chat.messages 残留脏数据
    # 防止重复提交：已完成（finished=True）且无等待中的 Agent 才允许覆盖
    existing = _active_generations.get(session_id)
    if existing is not None:
        if not existing.finished or session_id in _agent_sessions:
            raise HTTPException(status_code=409, detail=f"会话 {session_id} 已有活跃生成，请等待完成或中止后重试")
        # 旧状态已完全结束，清理 Agent 残留
        _agent_sessions.pop(session_id, None)
        _agent_sessions_ts.pop(session_id, None)

    # 队列上限检查（在修改 chat 之前）
    async with _queue_lock:
        if len(_pending_queue) >= MAX_PENDING_QUEUE:
            raise HTTPException(
                status_code=503,
                detail=f"队列已满（{MAX_PENDING_QUEUE}），请等待其他任务完成后重试",
            )

    # ── 验证通过，修改 chat ──
    # 应用本条消息的采样参数并持久化
    if request.settings:
        chat.apply_settings(request.settings)
        await session_store.update_settings(session_id, request.settings)
        # 系统提示词变更 → 在末尾追加新系统消息（而非替换开头的旧消息）
        new_sp = request.settings.system_prompt
        if new_sp is not None and new_sp != chat.system_prompt:
            chat.messages.append(ChatMessage(role=ROLE_SYSTEM, content=new_sp))
            chat.system_prompt = new_sp

    # 多模态消息存储文本部分，完整数组用于 API 调用
    if isinstance(request.content, list):
        chat.messages.append(ChatMessage(role=ROLE_USER, content=request.content))  # type: ignore[arg-type]
    else:
        chat.messages.append(ChatMessage(role=ROLE_USER, content=request.content))

    # 提前创建 assistant 消息，标记本轮对话状态，确保页面刷新后前端可同步
    # 统一入队：所有会话一律以 queued 状态入队，由 _dequeue_and_start 统一调度
    assistant_msg = ChatMessage(
        role=ROLE_ASSISTANT, content="",
        message_status=MSG_QUEUED,
        thinking=request.thinking,
    )
    chat.messages.append(assistant_msg)

    # 注册生成状态 — 当前客户端和刷新后的新客户端共用同一数据源
    state = _GenerationState()
    _active_generations[session_id] = state

    # 入队并立即触发出队（有空位则马上启动）
    async with _queue_lock:
        _pending_queue.append((session_id, chat, request, state))
        queue_size = len(_pending_queue)
    _log.info("[sess:%s] 消息入队: queue_size=%d, tools=%s",
              session_id, queue_size,
              request.tool_names if request.tool_names else [])
    await _update_and_broadcast(session_id, SessionStatus.PENDING.value)
    await _dequeue_and_start()

    async def _event_stream():
        """SSE 输出生成器：从生成状态读取事件并格式化输出。

        工具执行期间可能长时间无数据，每 SSE_HEARTBEAT_INTERVAL 秒
        发送 SSE 注释行（: heartbeat）保活，防止前端/代理超时断开。
        """
        cursor = 0
        try:
            # 若排队中，发 pending 状态事件告知前端
            if state.task is None:
                yield f"data: {json.dumps({'type': SSE_STATUS, 'status': SessionStatus.PENDING.value})}\n\n"

            while True:
                async with state.condition:
                    while cursor < len(state.events):
                        event = state.events[cursor]
                        cursor += 1
                        yield f"data: {json.dumps(event)}\n\n"
                    if state.finished:
                        break
                    try:
                        await asyncio.wait_for(
                            state.condition.wait(),
                            timeout=SSE_HEARTBEAT_INTERVAL,
                        )
                    except asyncio.TimeoutError:
                        pass  # 超时 → 退出 async with，发送心跳
                    else:
                        continue  # 收到通知 → 回到 while 循环处理新事件
                # 锁外：发送 SSE 注释心跳，重置 TCP / 代理 / 前端读超时
                yield ": heartbeat\n\n"
            yield f"data: {SSE_DONE}\n\n"
        except GeneratorExit:
            # 客户端断开（刷新、关标签页等）— _generate() 在后台继续运行，
            # 不标记为终止（只有显式 abort 端点会设置 client_disconnected）
            pass

    return StreamingResponse(_event_stream(), media_type=SSE_MEDIA_TYPE)


@router.get("/api/conversations/{session_id}/stream")
async def subscribe_generation_stream(session_id: str) -> StreamingResponse:
    """订阅正在进行的生成流（用于页面刷新后重连）。

    若该会话有活跃的后台生成 Task，返回 SSE 流：
    - 仅推送新事件（不回放历史 — 前端已从 GET /conversations/{id} 加载内容）
    - 实时推送直到生成结束

    无活跃生成时返回 404。
    """
    state = _active_generations.get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="该会话没有活跃的生成流")

    _log.info("[sess:%s] 客户端重连生成流 (cursor=%d)", session_id, len(state.events))

    async def _event_stream():
        # 从当前末尾开始 — 前端已通过 GET 拿到此刻的状态
        cursor = len(state.events)
        try:
            while True:
                async with state.condition:
                    while cursor < len(state.events):
                        event = state.events[cursor]
                        cursor += 1
                        yield f"data: {json.dumps(event)}\n\n"
                    if state.finished:
                        break
                    try:
                        await asyncio.wait_for(
                            state.condition.wait(),
                            timeout=SSE_HEARTBEAT_INTERVAL,
                        )
                    except asyncio.TimeoutError:
                        pass
                    else:
                        continue
                yield ": heartbeat\n\n"
            yield f"data: {SSE_DONE}\n\n"
        except GeneratorExit:
            pass  # 订阅端断开，不影响生成

    return StreamingResponse(_event_stream(), media_type=SSE_MEDIA_TYPE)


@router.get("/api/sessions/status-stream")
async def session_status_stream(session_ids: str = "") -> StreamingResponse:
    """订阅指定会话的状态变更（SSE），替代前端轮询。

    Query params:
        session_ids: 逗号分隔的会话 ID 列表

    连接后先发送每个会话的当前状态快照，之后实时推送变更。
    覆盖式订阅：新连接替换同一会话的旧订阅，非追加。
    """
    ids = [s.strip() for s in session_ids.split(",") if s.strip()]
    queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

    # 覆盖式订阅：新连接替换旧订阅（逐会话覆盖，非全局清空）
    for sid in ids:
        old_queues = _status_subscribers.pop(sid, [])
        # 唤醒旧 SSE 连接，让它们退出阻塞的 queue.get()
        for old_q in old_queues:
            try:
                old_q.put_nowait({"type": SSE_STATUS, "session_id": sid, "status": STATUS_REPLACED})
            except asyncio.QueueFull:
                pass
        _status_subscribers[sid] = [queue]

    async def _stream():
        try:
            # 发送当前状态快照
            for sid in ids:
                try:
                    detail = await session_store.get(sid)
                    st = detail.status.value
                except KeyError:
                    st = STATUS_UNKNOWN
                yield f"data: {json.dumps({'type': SSE_STATUS, 'session_id': sid, 'status': st})}\n\n"
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"

            # 持续推送变更
            while True:
                event = await queue.get()
                # 若收到 replaced 哨兵，退出（新连接已接管订阅）
                if event.get("status") == STATUS_REPLACED:
                    return
                yield f"data: {json.dumps(event)}\n\n"
        except GeneratorExit:
            pass
        finally:
            # 清理订阅（仅清理自己的 queue，不影响新连接的 queue）
            async with _status_subscribers_lock:
                for sid in ids:
                    subs = _status_subscribers.get(sid, [])
                    if queue in subs:
                        subs.remove(queue)
                        if not subs:
                            _status_subscribers.pop(sid, None)

    return StreamingResponse(_stream(), media_type=SSE_MEDIA_TYPE)


@router.post("/api/conversations/{session_id}/abort")
async def abort_generation(session_id: str) -> dict[str, object]:
    """终止正在进行的生成。

    前端用户点击停止按钮时调用。
    - 取消后台 asyncio Task → 立即停止 LLM 调用
    - 若在排队队列中 → 移除
    - 更新会话状态为 completed（侧栏实时感知）
    - 无活跃生成也返回 ok（幂等）
    """
    global _pending_queue
    state = _active_generations.get(session_id)
    had_running_task = False
    if state is not None:
        state.client_disconnected = True
        if state.task and not state.task.done():
            state.task.cancel()
            had_running_task = True

    # 从待调度队列中移除（无论 state 是否存在都检查）
    async with _queue_lock:
        filtered: deque[tuple[str, "Chat", "ConversationMessageRequest", _GenerationState]] = deque()
        for item in _pending_queue:
            if item[0] != session_id:
                filtered.append(item)
        _pending_queue = filtered

    # 排队中的会话：唤醒阻塞在 _event_stream 的 SSE 连接，避免挂起
    if state is not None and not had_running_task:
        async with state.condition:
            state.finished = True
            state.condition.notify_all()

    # 清理可能泄漏的 Agent 会话（自定义工具暂停时 abort）
    _agent_sessions.pop(session_id, None)
    _agent_sessions_ts.pop(session_id, None)

    # 取消了正在运行的任务 → 释放并发槽位，触发队列调度
    if had_running_task:
        _log.info("[sess:%s] 中止生成（Task cancel）", session_id)
        await _dequeue_and_start()

    # 立即更新会话状态，确保侧栏实时感知。
    try:
        chat = await session_store.get_chat(session_id)
        if chat is not None:
            # 标记最后一条 assistant 消息为已终止
            _resolve_assistant_statuses(chat, frozenset({MSG_GENERATING, MSG_QUEUED}), MSG_ABORTED)
            await session_store.register(session_id, chat)
        await _update_and_broadcast(session_id, SessionStatus.COMPLETED.value)
    except KeyError:
        pass  # 会话不存在，忽略
    return {RESPONSE_KEY_OK: True, "session_id": session_id}


@router.get(
    "/api/conversations/{session_id}",
    response_model=ConversationDetail,
)
async def get_conversation(session_id: str) -> ConversationDetail:
    """获取会话详情，包含完整消息历史（含流式进行中的消息）。"""
    try:
        return await session_store.get(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/api/conversations/{session_id}")
async def delete_conversation(session_id: str) -> dict[str, object]:
    """删除会话及其全部上下文。

    同时取消活跃生成、移出待调度队列、清理订阅者。
    """
    global _pending_queue
    # 1. 取消正在进行的生成 → 标记 session_deleted，防止 finally 块 re-register
    state = _active_generations.get(session_id)
    if state is not None:
        state.session_deleted = True
        state.client_disconnected = True
        if state.task and not state.task.done():
            state.task.cancel()
        _active_generations.pop(session_id, None)

    # 清理可能泄漏的 Agent 会话
    _agent_sessions.pop(session_id, None)
    _agent_sessions_ts.pop(session_id, None)

    # 2. 从待调度队列中移除
    async with _queue_lock:
        filtered: deque[tuple[str, "Chat", "ConversationMessageRequest", _GenerationState]] = deque()
        for item in _pending_queue:
            if item[0] != session_id:
                filtered.append(item)
        _pending_queue = filtered

    # 3. 通知状态订阅者并清理
    async with _status_subscribers_lock:
        queues = _status_subscribers.pop(session_id, [])
    for q in queues:
        try:
            await q.put({"type": SSE_STATUS, "session_id": session_id, "status": STATUS_UNKNOWN})
        except asyncio.CancelledError:
            pass

    # 4. 删除会话
    _log.info("[sess:%s] 删除会话", session_id)
    deleted = await session_store.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return {"deleted": session_id}


@router.patch("/api/conversations/{session_id}")
async def update_conversation(session_id: str, request: ConversationUpdateRequest) -> dict[str, object]:
    """更新会话（如修改标题、置顶/取消置顶）。"""
    try:
        await session_store.update(session_id, title=request.title, pinned=request.pinned)
        return {"session_id": session_id, "title": request.title, "pinned": request.pinned}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/conversations", response_model=ConversationListResponse)
async def list_conversations() -> ConversationListResponse:
    """列出所有活跃会话（不含状态 — 状态通过 SSE 订阅获取）。"""
    conversations = await session_store.list_all()
    items = [
        ConversationListItem(
            session_id=c.session_id,
            model=c.model,
            title=c.title,
            mode=c.mode,
            message_count=c.message_count,
            pinned=c.pinned,
            created_at=c.created_at,
            last_access=c.last_access,
        )
        for c in conversations
    ]
    return ConversationListResponse(conversations=items)


# ── Agent API ─────────────────────────────────────────────


_agent_sessions: dict[str, "Agent"] = {}
_agent_sessions_ts: dict[str, float] = {}


@router.post("/api/agent/chat/continue", response_model=AgentResponse)
async def agent_continue(request: AgentContinueRequest) -> AgentResponse:
    """回传工具执行结果，让 Agent 继续推理。"""
    agent = _agent_sessions.get(request.session_id)
    if agent is None:
        raise HTTPException(
            status_code=404, detail=f"Agent 会话不存在: {request.session_id}"
        )

    _log.info("[sess:%s] Agent 继续推理: tool_results=%d",
              request.session_id, len(request.tool_results))
    try:
        response = await agent.continue_with_results(request.tool_results)
        if response.finish_reason != "tool_calls":
            _agent_sessions.pop(request.session_id, None)
            _agent_sessions_ts.pop(request.session_id, None)
        else:
            # 仍有工具调用待处理 → 刷新时间戳，避免被 TTL 清理误杀
            _agent_sessions_ts[request.session_id] = _time.time()
            response.session_id = request.session_id
        return response
    except Exception as e:
        _agent_sessions.pop(request.session_id, None)
        _agent_sessions_ts.pop(request.session_id, None)
        await session_store.delete(request.session_id)
        if isinstance(e, KeyError):
            raise HTTPException(status_code=404, detail=str(e)) from e
        raise HTTPException(status_code=500, detail=str(e)) from e


# ── 文件上传 ──────────────────────────────────────────────


@router.post("/api/upload")
async def upload_file(file: UploadFile = File(...)) -> dict[str, object]:
    """上传文件，返回文件引用。支持的格式见 GET /api/upload/config。"""
    return await process_upload(file)


@router.get("/api/upload/config", response_model=UploadConfigResponse)
async def upload_config() -> UploadConfigResponse:
    """返回支持的上传文件类型与限制，前端据此设置 accept 与校验。"""
    return get_upload_config()


# ── 配置信息 ──────────────────────────────────────────────


class LLMConfigResponse(BaseModel):
    """LLM 配置信息。"""

    base_url: str = Field(description="LLM 网关地址")
    default_model: str = Field(description="默认模型 ID")
    auth_token: str = Field(description="认证令牌（可能含 ${VAR} 占位符，实际请求时自动替换）")


class LLMConfigUpdateRequest(BaseModel):
    """更新 LLM 配置的请求体。"""

    base_url: str | None = Field(default=None, description="LLM 网关地址")
    auth_token: str | None = Field(default=None, description="认证令牌")
    model: str | None = Field(default=None, description="默认模型 ID")
    max_concurrent: int | None = Field(default=None, description="最大并发生成数")


@router.get("/api/llm/config", response_model=LLMConfigResponse)
async def llm_config() -> LLMConfigResponse:
    """获取当前 LLM 配置信息。"""

    return LLMConfigResponse(
        base_url=get_base_url(),
        default_model=get_default_model(),
        auth_token=get_raw_auth_token(),
    )


@router.put("/api/llm/config")
async def llm_config_update(request: LLMConfigUpdateRequest) -> dict[str, object]:
    """更新 LLM 运行时配置（前端设置面板保存）。"""

    _log.info("LLM 配置更新: base_url=%s, model=%s, max_concurrent=%s",
              request.base_url, request.model, request.max_concurrent)
    apply_llm_overrides(
        base_url=request.base_url,
        auth_token=request.auth_token,
        model=request.model,
        max_concurrent=request.max_concurrent,
    )
    return {RESPONSE_KEY_OK: True}


class ConcurrencyConfigResponse(BaseModel):
    max_concurrent: int = Field(description="最大并发生成数")


@router.get("/api/llm/concurrency", response_model=ConcurrencyConfigResponse)
async def concurrency_config() -> ConcurrencyConfigResponse:
    return ConcurrencyConfigResponse(max_concurrent=get_max_concurrent())


# ── 会话默认设定 ────────────────────────────────────────


@router.get("/api/session-settings/default")
async def get_session_settings_default() -> dict[str, object]:
    return get_default_session_settings()


@router.put("/api/session-settings/default")
async def update_session_settings_default(body: dict[str, object]) -> dict[str, object]:
    apply_default_session_settings(body)
    return get_default_session_settings()


# ── 工具组常量 ──────────────────────────────────────────
# 使用 llm.constants 中定义的 MSG_BUILTIN_GROUP


@router.get("/api/tools")
async def list_available_tools() -> dict[str, object]:
    """返回所有已注册工具的完整元数据 + 工具组。

    前端根据此接口动态获取工具信息（图标、标签、排序、描述），
    不做任何硬编码。工具组将内置工具和每个 MCP 服务器统一展示为
    可整组开关的胶囊按钮。
    """

    builtin_names = sorted(t.name for t in BUILTIN_TOOLS)
    groups: dict[str, list[str]] = {}
    if builtin_names:
        groups[MSG_BUILTIN_GROUP] = builtin_names
    groups.update(mcp_manager.get_server_tools())

    return {
        "tools": tool_executor.get_tools_metadata(),
        "groups": groups,
    }


# ── MCP JSON 配置 ───────────────────────────────────────────


@router.get("/api/mcp/config")
async def mcp_config() -> dict[str, object]:
    """获取 MCP 服务器 JSON 配置原文。"""
    return {"config": get_mcp_config_text()}


@router.put("/api/mcp/config")
async def mcp_config_update(request: dict[str, object]) -> dict[str, object]:
    """保存 MCP JSON 配置并 diff-based 重连。

    仅重启变更的服务器，未变更的服务器保持连接不中断。
    返回当前重载状态供前端轮询。
    """

    text = str(request.get("config", ""))

    # 验证 JSON 语法与结构
    if text.strip():
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"JSON 语法错误: {e.msg} (位置 {e.pos})")

        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="配置必须是 JSON 对象（以 { 开头）")
        data = cast(dict[str, object], data)

        mcp_servers = data.get(MCP_KEY_MCP_SERVERS)
        if mcp_servers is not None and not isinstance(mcp_servers, dict):
            raise HTTPException(status_code=400, detail=f'"{MCP_KEY_MCP_SERVERS}" 必须是对象')

    apply_mcp_config_text(text)

    # 后台 diff-based 重连，不阻塞 API 响应
    # 但通过 asyncio.create_task + error callback 确保异常可追踪
    _log.info("MCP 配置更新，触发 diff 重连")

    async def _reload_safe() -> None:
        try:
            await mcp_manager.reload(text)
        except Exception:
            _log.exception("MCP 后台重载异常")

    asyncio.create_task(_reload_safe())

    return {RESPONSE_KEY_OK: True, "reloading": mcp_manager.is_reloading}


@router.get("/api/mcp/status")
async def mcp_server_status() -> dict[str, object]:
    """返回 MCP 服务器连接状态。

    Returns:
        {server_name: "running" | "stopped" | "error"}
    """
    return {"servers": mcp_manager.get_status()}


# ── 密钥管理 ───────────────────────────────────────────────


class SecretsResponse(BaseModel):
    keys: list[str] = Field(description="已存储的密钥名称列表")


class SecretsUpdateRequest(BaseModel):
    secrets: dict[str, str | None] = Field(description="完整的密钥键值映射。null/空值=删除，省略=保留不变")


@router.get("/api/secrets", response_model=SecretsResponse)
async def secrets_config() -> SecretsResponse:
    """获取已存储的密钥名称列表（值不返回）。"""

    return SecretsResponse(keys=get_secrets_keys())


@router.put("/api/secrets")
async def secrets_config_update(request: SecretsUpdateRequest) -> dict[str, object]:
    """更新密钥存储。

    密钥可在 LLM auth_token、MCP URL 等配置中以 ${VAR_NAME} 引用，
    实际请求时自动替换为真实值。
    """

    apply_secrets(request.secrets)
    return {RESPONSE_KEY_OK: True}


# ── 有序关闭 ──────────────────────────────────────────────


async def shutdown_generations() -> None:
    """有序关闭：终止所有生成中 / 排队中会话，通知订阅者，清理资源。

    在 FastAPI lifespan shutdown 阶段调用。
    关键顺序：
    1. 先置 shutting_down 标志 → 阻止 finally 块启动新任务
    2. 再清空队列 → 即使 finally 块仍调用 _dequeue_and_start，也找不到可调度项
    3. 推送 SSE 订阅者 → 尽早解阻塞 queue.get()，让 SSE 连接正常结束
    4. 取消后台 Task → finally 块中 shield 保护持久化
    5. 等待 Task 完成 → 超时 3s 强制继续
    """

    global _shutting_down
    _shutting_down = True
    _log.info("有序关闭: 清空 %d 排队, 取消 %d 活跃",
              len(_pending_queue), len(_active_generations))

    # ── 1. 清空待调度队列（先于取消 task，避免 finally 块竞态）──
    async with _queue_lock:
        _pending_queue.clear()

    # ── 2. 推送最终状态给 SSE 订阅者（尽早解阻塞 queue.get()）──
    async with _status_subscribers_lock:
        for sid, queues in list(_status_subscribers.items()):
            payload: dict[str, object] = {
                "type": SSE_STATUS, "session_id": sid, "status": STATUS_COMPLETED,
            }
            for q in queues:
                try:
                    q.put_nowait(payload)
                except (asyncio.QueueFull, Exception):
                    pass
        _status_subscribers.clear()

    # ── 3. 标记并取消所有活跃生成 Task ──
    for sid, state in list(_active_generations.items()):
        state.client_disconnected = True
        state.session_deleted = True  # 阻止 finally 块 re-register
        if state.task and not state.task.done():
            state.task.cancel()
        # 唤醒阻塞在 _event_stream / subscribe_generation_stream 的协程
        async with state.condition:
            state.finished = True
            state.condition.notify_all()

    # ── 4. 取消所有延迟清理任务（_cleanup_generation_state 的 300s sleep）──
    for t in list(_delayed_cleanup_tasks):
        if not t.done():
            t.cancel()
    _delayed_cleanup_tasks.clear()

    # ── 5. 持久化：generating / pending → completed ──
    try:
        all_sessions = await session_store.list_all()
        for s in all_sessions:
            if s.status in (SessionStatus.GENERATING, SessionStatus.PENDING):
                await session_store.update_status(s.session_id, SessionStatus.COMPLETED.value)
    except Exception:
        pass

    # ── 6. 等待取消的 Task 完成 finally 清理（shield 保护，可能需 3s）──
    tasks = [s.task for s in _active_generations.values() if s.task and not s.task.done()]
    if tasks:
        _, pending = await asyncio.wait(tasks, timeout=SHUTDOWN_TASK_WAIT)
        if pending:
            _log.info("%d 个生成 Task 未在 3s 内完成清理，强制继续关闭", len(pending))

    _active_generations.clear()
    _log.info("有序关闭完成")
