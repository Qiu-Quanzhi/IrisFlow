/** Agent 状态管理 — 流式推理 + 工具调用循环 + 多会话并行 */

import { ref, watch, type Ref } from "vue";
import { agentContinue, createConversation, subscribeGenerationStream, abortGeneration, readWithTimeout, getServerUrl, isConnectionError, getDefaultSessionSettings, BASE, PATH_CONVERSATIONS } from "../api/client";
import { getToolLabel } from "./toolMetadata";
import { draftStore } from "./drafts";
import {
  DEFAULT_TITLE,
  FETCH_TIMEOUT,
  STATUS_IDLE,
  STATUS_GENERATING,
  STATUS_COMPLETED,
  STATUS_PENDING,
  STATUS_UNKNOWN,
  ROLE_USER,
  ROLE_ASSISTANT,
  ROLE_TOOL,
  THINK_NONE,
  THINK_THINKING,
  THINK_DONE,
  SSE_REASONING,
  SSE_CONTENT,
  SSE_TOOL_CALLS,
  SSE_TOOL_CALL,
  SSE_TOOL_RESULT,
  SSE_SESSION,
  SSE_TITLE,
  SSE_ERROR,
  SSE_STATUS,
  SSE_DONE,
  SSE_DATA_PREFIX,
  SSE_DATA_PREFIX_LEN,
  SSE_READ_TIMEOUT,
  WF_THINK,
  WF_TOOL_CALL,
  WF_TOOL_RESULT,
  FINISH_TOOL_CALLS,
  HTTP_NOT_FOUND,
  MSG_QUEUED,
  MSG_GENERATING,
  MSG_COMPLETED,
  MSG_ABORTED,
} from "../constants";
import type {
  AgentResponse,
  FileAttachment,
  SessionSettings,
  SessionStatus,
  ThinkState,
  ToolCallRaw,
  ToolCallRecord,
  ToolResult,
  UIMessage,
  WorkflowEntry,
} from "../types/api";

// ── 会话状态 ──────────────────────────────────────────

interface SessionState {
  messages: UIMessage[];
  pendingToolCalls: ToolCallRecord[];
  agentSessionId: string | null;
  loading: boolean;
  error: string | null;
  status: SessionStatus;
  abortController: AbortController | null;
  nextId: number;
  settings: SessionSettings | null;
}

function createSessionState(): SessionState {
  return {
    messages: [],
    pendingToolCalls: [],
    agentSessionId: null,
    loading: false,
    error: null,
    status: STATUS_IDLE as SessionStatus,
    abortController: null,
    nextId: 1,
    settings: null,
  };
}

// ── 工具函数 ──────────────────────────────────────────

function parseToolCall(tc: ToolCallRaw): ToolCallRecord {
  let args: Record<string, unknown> = {};
  try {
    args = JSON.parse(tc.function.arguments);
  } catch { /* keep empty args */ }
  return { id: tc.id, name: tc.function.name, arguments: args };
}

// ── 工具调用/结果展示文本（泛用，后端权威提供元数据） ────

function formatToolCall(name: string, args: Record<string, unknown>): string {
  const label = getToolLabel(name);
  const keys = Object.keys(args);
  if (keys.length === 0) return `调用 ${label}`;
  const firstVal = String(args[keys[0]] ?? "");
  const short = firstVal.length > 60 ? firstVal.slice(0, 60) + "…" : firstVal;
  return `调用 ${label}：${short}`;
}

function formatToolResult(name: string, isError: boolean): string {
  return isError ? `${getToolLabel(name)} 执行失败` : `${getToolLabel(name)} 执行完成`;
}

// ── useAgent ──────────────────────────────────────────

export function useAgent(config: {
  model: Ref<string>;
  activeSessionId: Ref<string | null>;
  onSessionCreated?: (sessionId: string) => void;
  onTitleGenerated?: (title: string) => void;
  onConnectionLost?: () => void;
  onSessionNotFound?: () => void;
}) {
  // ── 活跃会话的响应式状态（模板直接绑定） ──────────
  const messages = ref<UIMessage[]>([]);
  const pendingToolCalls = ref<ToolCallRecord[]>([]);
  const agentSessionId = ref<string | null>(null);
  const loading = ref(false);
  const streamingSessionId = ref<string | null>(null);
  const error = ref<string | null>(null);

  // ── 当前会话设定 ─────────────────────────────────
  const currentSettings = ref<SessionSettings>({
    system_prompt: null, temperature: null, max_tokens: null,
    top_p: null, top_k: null, presence_penalty: null,
    frequency_penalty: null, repeat_penalty: null,
  });
  const defaultSettings = ref<SessionSettings>({ ...currentSettings.value });

  // ── 每会话状态 Map ─────────────────────────────────
  const _states = new Map<string, SessionState>();

  function _ensure(sid: string): SessionState {
    let s = _states.get(sid);
    if (!s) {
      s = createSessionState();
      _states.set(sid, s);
    }
    return s;
  }

  function _activate(sid: string | null) {
    if (sid && _states.has(sid)) {
      const s = _states.get(sid)!;
      messages.value = s.messages;
      s.messages = messages.value as any;
      pendingToolCalls.value = s.pendingToolCalls;
      agentSessionId.value = s.agentSessionId;
      loading.value = s.loading;
      error.value = s.error;
      // 恢复会话设定（已有会话使用存储值，新会话用默认值）
      currentSettings.value = s.settings ?? { ...defaultSettings.value };
    } else {
      messages.value = [];
      pendingToolCalls.value = [];
      agentSessionId.value = null;
      loading.value = false;
      error.value = null;
      // 新会话：使用后端默认设定
      currentSettings.value = { ...defaultSettings.value };
    }
  }

  function _deactivate(sid: string | null | undefined) {
    if (!sid) return;
    const s = _states.get(sid);
    if (!s) return;
    s.messages = messages.value;
    s.pendingToolCalls = pendingToolCalls.value;
    s.agentSessionId = agentSessionId.value;
    s.loading = loading.value;
    s.error = error.value;
    s.settings = { ...currentSettings.value };
  }

  /** 仅当 sid 是当前活跃会话时才应更新模块级 ref。 */
  function _isActive(sid: string): boolean {
    return sid === config.activeSessionId.value;
  }

  /** 将 currentSettings 同步到指定会话的持久化状态。
   *  供 ChatPanel 在从后端恢复设定后调用，确保 _activate 下次切回时读到正确值。 */
  function syncSessionSettings(sid: string) {
    const s = _states.get(sid);
    if (s) s.settings = { ...currentSettings.value };
  }

  // ── 自动保存/恢复 ──────────────────────────────────
  watch(config.activeSessionId, (newSid, oldSid) => {
    _deactivate(oldSid);
    _activate(newSid);
  });

  // ── addMessage（会话感知） ──────────────────────────
  function addMessage(role: UIMessage["role"], content: string, sid?: string): UIMessage {
    const id = sid ?? config.activeSessionId.value;
    if (!id) throw new Error("addMessage: no session id");
    const s = _ensure(id);
    const msg: UIMessage = {
      id: `msg-${s.nextId++}`,
      role,
      content,
      timestamp: Date.now(),
    };
    s.messages.push(msg);
    if (_isActive(id)) {
      messages.value = s.messages;
      s.messages = messages.value as any; // rebind 到响应式代理
    }
    return s.messages[s.messages.length - 1];
  }

  // ── SSE 事件处理共享逻辑 ──────────────────────────

  interface SSEHandlerContext {
    msg: UIMessage;
    sid: string;
    s: SessionState;
    thinkStateRef: { v: ThinkState };
    liveThinkIdxRef: { v: number };
  }

  function processSSELines(
    lines: string[],
    ctx: SSEHandlerContext,
    onTitle?: (title: string) => void,
  ): 'continue' | 'return' {
    function _updateThinkLog(text: string) {
      if (ctx.liveThinkIdxRef.v < 0) {
        ctx.liveThinkIdxRef.v = ctx.msg.workflowLog!.length;
        ctx.msg.workflowLog!.push({ type: WF_THINK, text });
      } else {
        ctx.msg.workflowLog!.splice(ctx.liveThinkIdxRef.v, 1, { type: WF_THINK, text });
      }
    }
    function _endThinkPhase() {
      if (ctx.thinkStateRef.v === THINK_THINKING) {
        ctx.thinkStateRef.v = THINK_DONE;
        ctx.msg.thinkComplete = true;
      }
      ctx.liveThinkIdxRef.v = -1;
    }

    for (const line of lines) {
      if (!line.startsWith(SSE_DATA_PREFIX)) continue;
      const payload = line.slice(SSE_DATA_PREFIX_LEN);
      if (payload === SSE_DONE) continue;
      try {
        const event = JSON.parse(payload);

        if (event.type === SSE_REASONING) {
          ctx.thinkStateRef.v = THINK_THINKING;
          ctx.msg.thinkComplete = false;
          ctx.msg.thinkContent = (ctx.msg.thinkContent || "") + event.content;
          _updateThinkLog(ctx.msg.thinkContent);
        } else if (event.type === SSE_CONTENT) {
          _endThinkPhase();
          ctx.msg.content += event.content;
        } else if (event.type === SSE_TOOL_CALLS) {
          _endThinkPhase();
          const records: ToolCallRecord[] = (event.tool_calls as ToolCallRaw[]).map(parseToolCall);
          for (const r of records) {
            ctx.msg.workflowLog!.push({
              type: WF_TOOL_CALL, toolName: r.name, rawArgs: r.arguments,
              text: formatToolCall(r.name, r.arguments),
            });
          }
          ctx.s.pendingToolCalls = records;
          if (_isActive(ctx.sid)) pendingToolCalls.value = records;

          if (event.session_id) {
            ctx.s.agentSessionId = event.session_id as string;
            if (_isActive(ctx.sid)) agentSessionId.value = event.session_id as string;
          }

          const toolMsg = addMessage(ROLE_TOOL, "", ctx.sid);
          toolMsg.toolCalls = records;
          ctx.s.loading = false;
          if (_isActive(ctx.sid)) loading.value = false;
          return 'return';
        } else if (event.type === SSE_TOOL_CALL) {
          _endThinkPhase();
          const tcName = event.name as string;
          const tcArgs = event.arguments as Record<string, unknown>;
          ctx.msg.workflowLog!.push({
            type: WF_TOOL_CALL, toolName: tcName, rawArgs: tcArgs,
            text: formatToolCall(tcName, tcArgs),
          });
          addMessage(ROLE_TOOL, "…", ctx.sid);
        } else if (event.type === SSE_TOOL_RESULT) {
          const toolName = event.name as string;
          const resultText = event.result as string;
          const isError = event.is_error === true;
          ctx.msg.workflowLog!.push({
            type: WF_TOOL_RESULT, toolName, rawResult: resultText, isError,
            text: formatToolResult(toolName, isError),
          });
        } else if (event.type === SSE_SESSION) {
          if (event.session_id) {
            ctx.s.agentSessionId = event.session_id as string;
            if (_isActive(ctx.sid)) agentSessionId.value = event.session_id as string;
          }
        } else if (event.type === SSE_TITLE) {
          if (event.title) onTitle?.(event.title as string);
        } else if (event.type === SSE_STATUS) {
          const st = event.status as string;
          if (st === STATUS_PENDING) {
            ctx.s.status = STATUS_PENDING;
            ctx.msg.queued = true;
          } else if (st === STATUS_GENERATING && ctx.s.status === STATUS_PENDING) {
            ctx.s.status = STATUS_GENERATING;
            ctx.msg.queued = false;
          }
          if (_isActive(ctx.sid)) {
            loading.value = ctx.s.status === STATUS_GENERATING || ctx.s.status === STATUS_PENDING;
          }
        } else if (event.type === SSE_ERROR) {
          ctx.s.error = event.content;
          ctx.msg.streamDone = true;
        }
      } catch { /* 非 JSON 行 */ }
    }
    return 'continue';
  }

  // ── run（流式 SSE） ─────────────────────────────────
  async function run(userMessage: string, toolNames: string[], files?: FileAttachment[], thinking = true) {
    let sid = config.activeSessionId.value;

    // 新建会话：先创建拿到真实 ID，再流式——消除 "__new__" 替身
    if (!sid) {
      try {
        const resp = await createConversation({
          model: config.model.value,
          title: DEFAULT_TITLE,
          mode: toolNames.length > 0 ? "agent" : "chat",
          settings: currentSettings.value,
        });
        sid = resp.session_id;
        // 预先初始化状态，再做 onSessionCreated（触发会话列表刷新 + watch 激活）。
        // 统一入队：初始为 pending，等待后端 SSE 推送权威状态变更。
        const s = _ensure(sid);
        s.status = STATUS_PENDING;
        s.settings = { ...currentSettings.value };  // 保存用户设定的会话设定，防止 _activate 覆盖
        config.onSessionCreated?.(sid);
        // 等 Vue 响应式 flush：activeSessionId 已更新，watch 已触发 _activate
        await new Promise(r => setTimeout(r, 0));
      } catch (e) {
        if (isConnectionError(e)) config.onConnectionLost?.();
        return;
      }
    }

    const s = _ensure(sid);
    s.loading = true;
    // 统一入队：初始为 pending，等待后端 SSE 推送权威状态变更
    s.status = STATUS_PENDING;
    s.error = null;
    streamingSessionId.value = sid;
    loading.value = true;

    // 分离图片与文本
    const imageFiles = files?.filter(f => f.data_url) ?? [];
    const textFiles = files?.filter(f => f.text_content) ?? [];

    let fullMessage = userMessage;
    if (textFiles.length > 0) {
      const fileTexts = textFiles.map(f =>
        `[文件: ${f.filename}]\n\n${f.text_content}`
      ).join("\n\n---\n\n");
      fullMessage = fileTexts + (userMessage ? "\n\n---\n\n" + userMessage : "");
    }

    const body: Record<string, unknown> = {
      thinking,
      tool_names: toolNames.length > 0 ? toolNames : undefined,
      settings: currentSettings.value,
      content: imageFiles.length
        ? [{ type: "text", text: fullMessage }, ...imageFiles.map(f => ({ type: "image_url", image_url: { url: f.data_url! } }))]
        : fullMessage,
    };

    const userMsg = addMessage(ROLE_USER, fullMessage, sid);
    userMsg.content = userMessage || (textFiles.length ? "" : userMessage);
    if (textFiles.length) userMsg.files = textFiles;
    if (imageFiles.length) userMsg.images = imageFiles.map(f => f.data_url!);

    const assistantMsg = addMessage(ROLE_ASSISTANT, "", sid);
    assistantMsg.thinking = thinking;
    assistantMsg.thinkContent = "";
    assistantMsg.thinkComplete = false;
    assistantMsg.workflowLog = [];
    // 默认排队中 — 后端统一入队，等待 SSE 推送权威状态变更
    assistantMsg.queued = true;

    const thinkStateRef: { v: ThinkState } = { v: THINK_NONE };
    const _liveThinkIdxRef: { v: number } = { v: -1 };

    const endpoint = `${getServerUrl()}${BASE}${PATH_CONVERSATIONS}/${sid}/messages/stream`;

    try {
      s.abortController = new AbortController();

      // 仅连接超时：Promise.race 不污染 fetch signal，避免 30s 后 abort body reader 导致流中断
      const resp = await Promise.race([
        fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: s.abortController.signal,
        }),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new DOMException("Connection timeout", "TimeoutError")), FETCH_TIMEOUT)
        ),
      ]);

      if (!resp.ok) {
        const text = await resp.text().catch(() => "Unknown error");
        const err = new Error(text) as Error & { status?: number };
        (err as any).status = resp.status;
        throw err;
      }
      if (!resp.body) throw new Error("Response body is null");

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await readWithTimeout(reader, SSE_READ_TIMEOUT);
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        if (processSSELines(lines, {
          msg: assistantMsg,
          sid,
          s,
          thinkStateRef,
          liveThinkIdxRef: _liveThinkIdxRef,
        }, config.onTitleGenerated) === 'return') return;
      }

      if (thinkStateRef.v === THINK_THINKING) {
        assistantMsg.thinkComplete = true;
      }
      assistantMsg.streamDone = true;
      // 用 as 防止 TS 窄化（processSSELines 内的赋值让 TS 认为 s.status 缩窄到 'pending'）
      if ((s.status as SessionStatus) === STATUS_GENERATING || (s.status as SessionStatus) === STATUS_PENDING) {
        s.status = STATUS_COMPLETED;
      }
    } catch (e: any) {
      if (e?.name === "AbortError") {
        // 用户手动终止 → abort() 已设置 aborted 标记 + COMPLETED。
        if (assistantMsg.content) assistantMsg.streamDone = true;
        s.status = STATUS_COMPLETED;
      } else if (e?.name === "TimeoutError") {
        s.status = STATUS_UNKNOWN;
        assistantMsg.streamDone = true;
        config.onConnectionLost?.();
      } else {
        s.status = STATUS_UNKNOWN;
        assistantMsg.streamDone = true;
        if (e?.status === HTTP_NOT_FOUND) {
          config.onSessionNotFound?.();
        } else if (isConnectionError(e)) {
          config.onConnectionLost?.();
        }
      }
    } finally {
      s.loading = false;
      s.abortController = null;
      streamingSessionId.value = null;
      // Only update active refs if this session is still the one being viewed.
      // If the user switched away mid-stream, the wrong-session update would
      // corrupt the visible messages & loading state.
      if (_isActive(sid)) {
        loading.value = false;
        messages.value = s.messages;
      }
    }
  }

  function abort() {
    const sid = config.activeSessionId.value;
    if (!sid) return;
    const s = _ensure(sid);
    for (let i = s.messages.length - 1; i >= 0; i--) {
      if (s.messages[i].role === ROLE_ASSISTANT) {
        s.messages[i].aborted = true;
        s.messages[i].queued = false;
        // 无正式输出时 streamDone 保持 false → WorkflowLog isWorkDone=false → 保持展开以展示思考过程
        if (s.messages[i].content) s.messages[i].streamDone = true;
        break;
      }
    }
    s.abortController?.abort();
    s.status = STATUS_COMPLETED;
    if (_isActive(sid)) messages.value = s.messages;
    // 通知后端标记终止（fire-and-forget，不阻塞 UI）
    abortGeneration(sid).catch(() => {});
  }

  // ── continueWithResults ─────────────────────────────
  async function continueWithResults(toolResults: ToolResult[]) {
    if (!agentSessionId.value) return;
    const sid = config.activeSessionId.value;
    if (!sid) return;  // 没有活跃会话，无法继续
    const s = _ensure(sid);

    s.error = null;
    s.loading = true;
    s.pendingToolCalls = [];
    if (_isActive(sid)) { loading.value = true; pendingToolCalls.value = []; }

    const lastToolMsg = [...s.messages].reverse().find(m => m.role === ROLE_TOOL && m.toolCalls);
    if (lastToolMsg?.toolCalls) {
      for (const tr of toolResults) {
        const tc = lastToolMsg.toolCalls.find(t => t.id === tr.id);
        if (tc) tc.result = tr.result;
      }
    }

    try {
      let resp: AgentResponse = await agentContinue({
        session_id: agentSessionId.value,
        model: config.model.value,
        tool_results: toolResults,
      });

      while (resp.finish_reason === FINISH_TOOL_CALLS && resp.session_id) {
        s.agentSessionId = resp.session_id;
        if (_isActive(sid)) agentSessionId.value = resp.session_id;
        const toolMsg = addMessage(ROLE_TOOL, "", sid);
        toolMsg.toolCalls = resp.tool_calls;
        s.pendingToolCalls = resp.tool_calls;
        if (_isActive(sid)) pendingToolCalls.value = resp.tool_calls;
        s.loading = false;
        if (_isActive(sid)) loading.value = false;
        return;
      }

      if (resp.content) addMessage(ROLE_ASSISTANT, resp.content, sid);
      s.agentSessionId = null;
      if (_isActive(sid)) agentSessionId.value = null;
    } catch (e: any) {
      if (isConnectionError(e)) {
        config.onConnectionLost?.();
      } else if (e?.status === HTTP_NOT_FOUND) {
        config.onSessionNotFound?.();
      }
    } finally {
      s.loading = false;
      if (_isActive(sid)) loading.value = false;
    }
  }

  // ── 会话生命周期 ────────────────────────────────────
  function clearMessages() {
    const sid = config.activeSessionId.value;
    const s = sid ? _states.get(sid) : null;
    if (s) { s.messages = []; s.pendingToolCalls = []; s.agentSessionId = null; s.error = null; s.status = STATUS_IDLE; }
    messages.value = [];
    pendingToolCalls.value = [];
    agentSessionId.value = null;
  }

  /** 从本地缓存中移除会话状态（例如删除会话后调用，防止显示陈旧数据）。 */
  function removeSession(sid: string) {
    _states.delete(sid);
    delete draftStore[sid];  // 清理内存草稿
    // 若被删除的是当前活跃会话，清空视图
    if (_isActive(sid)) {
      messages.value = [];
      pendingToolCalls.value = [];
      agentSessionId.value = null;
      error.value = null;
    }
  }

  function loadHistory(
    msgs: { role: UIMessage["role"]; content: string; reasoning_content?: string | null;
      tool_calls?: ToolCallRaw[] | null; tool_call_id?: string | null;
      message_status?: string | null; thinking?: boolean;
      is_error?: boolean | null;
      images?: string[]; files?: FileAttachment[]; }[],
    status?: SessionStatus,
  ) {
    const result: UIMessage[] = [];
    let currentGroup: UIMessage[] = [];
    // 跟踪每轮 assistant 消息的后端权威状态，供后续应用
    const _assistantStatuses: (string | null | undefined)[] = [];
    function flushGroup() {
      if (currentGroup.length === 0) return;
      // 连续的无正文 assistant（auto-tool 迭代）合并为一个连续 workflow；
      // 有正文的 assistant 作为断点，获得在此之前累积的 workflowLog，然后清空。
      let pendingLog: WorkflowEntry[] = [];

      for (const um of currentGroup) {
        if (um.role !== ROLE_ASSISTANT) continue;
        const idx = currentGroup.indexOf(um);

        // 收集本条 assistant 的 workflow 条目
        if (um.thinkContent) {
          pendingLog.push({ type: WF_THINK, text: um.thinkContent });
        }
        if (um.toolCalls?.length) {
          for (const tc of um.toolCalls) {
            if (tc.name) {
              pendingLog.push({
                type: WF_TOOL_CALL, toolName: tc.name, rawArgs: tc.arguments,
                text: formatToolCall(tc.name, tc.arguments),
              });
            }
            // 在后继 tool 消息中按 tool_call_id 正向匹配结果
            for (let j = idx + 1; j < currentGroup.length; j++) {
              const tm = currentGroup[j];
              if (tm.role !== ROLE_TOOL || !tm.toolCalls?.length) continue;
              const matched = tm.toolCalls.find(
                t => t.id === tc.id && t.result !== undefined && t.result !== null,
              );
              if (matched) {
                pendingLog.push({
                  type: WF_TOOL_RESULT, toolName: tc.name || "unknown",
                  rawResult: matched.result ?? undefined, isError: matched.isError ?? false,
                  text: formatToolResult(tc.name || "unknown", matched.isError ?? false),
                });
                break;
              }
            }
          }
        }

        // 有正文 → 断点：把累积的 workflowLog 赋给本条 assistant，然后清空
        if (um.content) {
          if (pendingLog.length) um.workflowLog = pendingLog;
          pendingLog = [];
        }
      }

      // 尾部残留（最后的 assistant 无正文，例如生成中被 abort 或排队中）
      if (pendingLog.length) {
        const last = [...currentGroup].reverse().find(m => m.role === ROLE_ASSISTANT);
        if (last && !last.workflowLog) last.workflowLog = pendingLog;
      }

      result.push(...currentGroup);
      currentGroup = [];
    }

    for (const m of msgs) {
      if (m.role === ROLE_USER && currentGroup.length > 0) flushGroup();
      const msg: UIMessage = {
        id: `msg-${result.length + currentGroup.length + 1}`,
        role: m.role,
        content: m.content,
        thinkContent: m.reasoning_content ?? undefined,
        thinkComplete: !!m.reasoning_content,
        thinking: (m as any).thinking ?? undefined,
        streamDone: true,
        images: (m as any).images,
        files: (m as any).files,
        timestamp: Date.now(),
      };
      if (m.tool_calls?.length) msg.toolCalls = m.tool_calls.map((tc: ToolCallRaw) => parseToolCall(tc));
      if (m.tool_call_id && m.role === ROLE_TOOL) {
        let toolName = "";
        for (let j = currentGroup.length - 1; j >= 0; j--) {
          const prev = currentGroup[j];
          if (prev.role === ROLE_ASSISTANT && prev.toolCalls) {
            const matched = prev.toolCalls.find(tc => tc.id === m.tool_call_id);
            if (matched) { toolName = matched.name; break; }
          }
        }
        msg.toolCalls = [{ id: m.tool_call_id, name: toolName || "unknown", arguments: {}, result: m.content || undefined, isError: m.is_error ?? undefined }];
      }
      // 记录后端权威的 per-message 状态（仅 assistant）
      if (m.role === ROLE_ASSISTANT) {
        _assistantStatuses.push(m.message_status);
      }
      currentGroup.push(msg);
    }
    flushGroup();

    // 将后端权威的 per-message 状态应用到结果中的 assistant 消息
    let statusIdx = 0;
    for (const r of result) {
      if (r.role === ROLE_ASSISTANT) {
        const mStatus = _assistantStatuses[statusIdx++];
        r.streamDone = true;  // 默认已完成
        if (mStatus === MSG_QUEUED) {
          r.queued = true;
          r.streamDone = false;
        } else if (mStatus === MSG_GENERATING) {
          r.streamDone = false;
        } else if (mStatus === MSG_ABORTED) {
          r.aborted = true;
          r.streamDone = !!r.content;
        }
        // MSG_COMPLETED / null → 默认状态（已完成）
      }
    }

    const sid = config.activeSessionId.value;
    if (sid) {
      const s = _ensure(sid);
      s.messages = result;
      if (status) s.status = status;
    }
    messages.value = result;
    // rebind 到 Vue 响应式代理，确保 resumeStream 等后续操作
    // 通过 s.messages 获取的对象能被 Vue 追踪变更（实时上屏）
    if (sid) {
      const s = _ensure(sid);
      s.messages = messages.value as any;
    }
  }

  function initSession(sid: string, st: SessionStatus) {
    const s = _ensure(sid);
    s.status = st;
  }

  function getSessionStatus(sid: string | null): SessionStatus {
    if (!sid) return STATUS_IDLE;
    return _states.get(sid)?.status ?? STATUS_COMPLETED;
  }

  function hasMessages(): boolean {
    return messages.value.length > 0;
  }

  // ── resumeStream（页面刷新后重连生成流）────────────────
  async function resumeStream(sessionId: string) {
    const s = _ensure(sessionId);

    // 找到最后一条 assistant 消息（loadHistory 已填充部分内容）
    const lastAssistant = [...s.messages].reverse().find(
      (m) => m.role === ROLE_ASSISTANT,
    );
    if (!lastAssistant) return;

    // 其他 assistant 已完成，不会再收到 SSE 事件，折叠它们的 WorkflowLog
    for (const m of s.messages) {
      if (m.role === ROLE_ASSISTANT && m !== lastAssistant && !m.streamDone) {
        m.streamDone = true;
      }
    }

    // 标记为进行中以继续上屏
    lastAssistant.streamDone = false;
    lastAssistant.thinkComplete = false;  // 思考可能在重连期间继续
    if (!lastAssistant.workflowLog) lastAssistant.workflowLog = [];

    // 恢复 workflowLog 中 think 条目的锚点
    const _liveThinkIdxRef: { v: number } = { v: -1 };
    for (let i = lastAssistant.workflowLog.length - 1; i >= 0; i--) {
      if (lastAssistant.workflowLog[i].type === WF_THINK) {
        _liveThinkIdxRef.v = i;
        break;
      }
    }
    const thinkStateRef: { v: ThinkState } = { v: lastAssistant.thinkContent
      ? THINK_THINKING
      : THINK_NONE };

    s.loading = true;
    // 保留排队 / 未知状态，不被重连覆盖。
    // 若前端无法确定状态为 unknown，重连流会立即结束（state.finished），不应把状态改回 generating。
    const wasPending = s.status === STATUS_PENDING;
    if (s.status !== STATUS_PENDING && s.status !== STATUS_UNKNOWN) {
      s.status = STATUS_GENERATING;
    }
    if (wasPending) {
      lastAssistant.queued = true;
      lastAssistant.streamDone = false;
    }
    s.error = null;
    streamingSessionId.value = sessionId;
    if (_isActive(sessionId)) {
      loading.value = true;
      messages.value = s.messages;
    }

    try {
      s.abortController = new AbortController();
      const reader = await subscribeGenerationStream(sessionId, s.abortController.signal);

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await readWithTimeout(reader, SSE_READ_TIMEOUT);
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        if (processSSELines(lines, {
          msg: lastAssistant,
          sid: sessionId,
          s,
          thinkStateRef,
          liveThinkIdxRef: _liveThinkIdxRef,
        }, config.onTitleGenerated) === 'return') return;
      }

      if (thinkStateRef.v === THINK_THINKING) {
        lastAssistant.thinkComplete = true;
      }
      lastAssistant.streamDone = true;
      if (!lastAssistant.aborted && !lastAssistant.queued) {
        s.status = STATUS_COMPLETED;
      }
    } catch (e: any) {
      if (e?.name === "AbortError") {
        // abort() 已处理 streamDone（有内容才设），此处仅确保 aborted 标记
        lastAssistant.aborted = true;
      } else if (e?.name === "TimeoutError") {
        lastAssistant.streamDone = true;
        s.status = STATUS_UNKNOWN;
        config.onConnectionLost?.();
      } else {
        lastAssistant.streamDone = true;
        if (e?.status === HTTP_NOT_FOUND) {
          config.onSessionNotFound?.();
        } else if (isConnectionError(e)) {
          config.onConnectionLost?.();
        }
        if (s.status !== STATUS_PENDING) {
          s.status = STATUS_COMPLETED;
        }
      }
    } finally {
      s.loading = false;
      s.abortController = null;
      streamingSessionId.value = null;
      if (_isActive(sessionId)) {
        loading.value = false;
        messages.value = s.messages;
      }
    }
  }

  // ── 初始化默认设定（后端为唯一权威源）───────────
  // defaultSettings 初始 all-null，refreshDefaultSettings 异步加载后更新。
  // currentSettings 新建会话时从 defaultSettings 复制，已有会话从后端恢复。
  async function refreshDefaultSettings() {
    try {
      const s = await getDefaultSessionSettings();
      if (s) defaultSettings.value = s;
    } catch { /* ignore */ }
  }
  refreshDefaultSettings();  // 初始加载

  return {
    messages, pendingToolCalls, agentSessionId, loading, streamingSessionId, error,
    currentSettings, defaultSettings, refreshDefaultSettings,
    addMessage, run, abort, continueWithResults, clearMessages, removeSession,
    loadHistory, initSession, getSessionStatus, hasMessages, resumeStream,
    syncSessionSettings,
  };
}
