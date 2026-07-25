/** API 客户端 — fetch 封装，每个后端端点一个函数 */

import type {
  AgentContinueRequest,
  AgentResponse,
  ConversationCreateRequest,
  ConversationDetail,
  ConversationListResponse,
  ConversationResponse,
  ConversationUpdateRequest,
  HealthResult,
  LLMConfig,
  MCPConfig,
  MCPStatusResult,
  SessionSettings,
  RuntimeStatus,
  SecretsConfig,
  UploadConfig,
  VersionInfo,
} from "../types/api";
import {
  FETCH_TIMEOUT,
  HTTP_BAD_GATEWAY,
  HTTP_GATEWAY_TIMEOUT,
  HTTP_SERVICE_UNAVAILABLE,
  PING_TIMEOUT,
  SSE_READ_TIMEOUT,
  STATUS_READ_TIMEOUT,
} from "../constants";

export const BASE = "/api";

// ── API 路径常量 ────────────────────────────────────
// request() 内部拼接 BASE，因此以下路径不含 /api 前缀。
// 非 request() 场景（直接 fetch）需自行拼接 BASE + PATH。

export const PATH_AGENT_CONTINUE = "/agent/chat/continue";
export const PATH_CONVERSATIONS = "/conversations";
export const PATH_LLM_CONFIG = "/llm/config";
export const PATH_SESSION_SETTINGS_DEFAULT = "/session-settings/default";
export const PATH_HEALTH = "/health";
export const PATH_MCP_STATUS = "/mcp/status";
export const PATH_LLM_CONCURRENCY = "/llm/concurrency";
export const PATH_MCP_CONFIG = "/mcp/config";
export const PATH_SECRETS = "/secrets";
export const PATH_UPLOAD_CONFIG = "/upload/config";
export const PATH_SESSIONS_STATUS_STREAM = "/sessions/status-stream";

// 根端点（无 /api 前缀，用于 rootFetch）
export const PATH_VERSION = "/version";
export const PATH_STATUS = "/status";

// 以下路径供直接 fetch 时拼接 BASE 使用
export const PATH_PING = "/ping";
export const PATH_TOOLS = "/tools";
export const PATH_UPLOAD = "/upload";

/** 获取当前后端服务器地址。
 *  开发环境：Vite 将 /api 代理到后端，同源请求。
 *  生产环境：后端直接 serve 前端静态文件，同源请求。 */
export function getServerUrl(): string {
  return "";
}

/** @deprecated 统一启动后前后端同源，不再需要手动设置后端地址。 */
export function setServerUrl(_url: string): void {
  // 保留接口兼容性，不再持久化
}

/** 拼接 API 路径与服务器地址。 */
function apiUrl(path: string): string {
  return getServerUrl() + path;
}

// ── 超时工具 ──────────────────────────────────────

/** 组合用户 AbortSignal 与超时 AbortSignal。
 *  优先使用 AbortSignal.any()，不可用时降级为手动转发。 */
function combineSignal(signal: AbortSignal | undefined, timeoutMs: number): AbortSignal {
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  if (!signal) return timeoutSignal;
  if (typeof AbortSignal.any === "function") return AbortSignal.any([signal, timeoutSignal]);

  // 降级：手动组合
  const ctrl = new AbortController();
  const onAbort = () => { ctrl.abort(signal.reason); };
  signal.addEventListener("abort", onAbort, { once: true });
  timeoutSignal.addEventListener("abort", () => {
    signal.removeEventListener("abort", onAbort);
    ctrl.abort(timeoutSignal.reason);
  }, { once: true });
  if (signal.aborted) ctrl.abort(signal.reason);
  else if (timeoutSignal.aborted) ctrl.abort(timeoutSignal.reason);
  return ctrl.signal;
}

/** 带超时的 ReadableStream 读取。
 *  超时时取消 reader 并抛出 TimeoutError。
 *  返回 { done, value }，超时则抛 DOMException(name="TimeoutError")。 */
async function readWithTimeout(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  timeoutMs: number,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  let timer: ReturnType<typeof setTimeout> | undefined;

  try {
    const result = await Promise.race([
      reader.read(),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
          reader.cancel().catch(() => {}); // best-effort 取消流
          reject(new DOMException("SSE read timeout", "TimeoutError"));
        }, timeoutMs);
      }),
    ]);
    return result;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

// ── 请求封装 ──────────────────────────────────────

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const opts: RequestInit = {
    method,
    headers: { "Content-Type": "application/json" },
    signal: combineSignal(signal, FETCH_TIMEOUT),
  };
  if (body !== undefined) {
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(apiUrl(`${BASE}${path}`), opts);
  if (!resp.ok) {
    const text = await resp.text().catch(() => "Unknown error");
    const err = new Error(text) as Error & { status: number };
    (err as any).status = resp.status;
    throw err;
  }
  return resp.json();
}

/** fetch + 连接超时（Promise.race 只作用连接阶段，不污染 body reader）。
 *  与 combineSignal 的关键区别：AbortSignal.timeout() 挂到 fetch 上会持续到头，
 *  在 SSE 长连接中一旦超时就会 abort body reader → 流中断。 */
async function fetchWithConnTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const resp = await Promise.race([
      fetch(url, init),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new DOMException("Connection timeout", "TimeoutError")), timeoutMs);
      }),
    ]);
    return resp;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

// ── Agent ─────────────────────────────────────────

export function agentContinue(
  body: AgentContinueRequest,
): Promise<AgentResponse> {
  return request<AgentResponse>("POST", PATH_AGENT_CONTINUE, body);
}

// ── 会话管理 ──────────────────────────────────────

export function createConversation(
  body: ConversationCreateRequest,
): Promise<ConversationResponse> {
  return request<ConversationResponse>("POST", PATH_CONVERSATIONS, body);
}

export function getConversation(
  sessionId: string,
): Promise<ConversationDetail> {
  return request<ConversationDetail>(
    "GET",
    `${PATH_CONVERSATIONS}/${sessionId}`,
  );
}

export function listConversations(): Promise<ConversationListResponse> {
  return request<ConversationListResponse>("GET", PATH_CONVERSATIONS);
}

export function deleteConversation(
  sessionId: string,
): Promise<{ deleted: string }> {
  return request<{ deleted: string }>(
    "DELETE",
    `${PATH_CONVERSATIONS}/${sessionId}`,
  );
}

export function updateConversation(
  sessionId: string,
  body: ConversationUpdateRequest,
): Promise<{ session_id: string; title: string | null; pinned: boolean | null }> {
  return request<{ session_id: string; title: string | null; pinned: boolean | null }>(
    "PATCH",
    `${PATH_CONVERSATIONS}/${sessionId}`,
    body,
  );
}

// ── 配置与健康 ────────────────────────────────────

export function getLLMConfig(): Promise<LLMConfig> {
  return request<LLMConfig>("GET", PATH_LLM_CONFIG);
}

// ── 会话设定 ──────────────────────────────────────

export function getDefaultSessionSettings(): Promise<SessionSettings> {
  return request<SessionSettings>("GET", PATH_SESSION_SETTINGS_DEFAULT);
}

export function updateDefaultSessionSettings(
  body: Partial<SessionSettings>,
): Promise<SessionSettings> {
  return request<SessionSettings>("PUT", PATH_SESSION_SETTINGS_DEFAULT, body);
}

export function updateLLMConfig(body: {
  base_url?: string | null;
  auth_token?: string | null;
  model?: string | null;
  max_concurrent?: number | null;
}): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("PUT", PATH_LLM_CONFIG, body);
}

export function getHealth(): Promise<HealthResult> {
  return request<HealthResult>("GET", PATH_HEALTH);
}

/** 轻量心跳检查 — 5s 超时，仅确认服务可达。
 *  校验响应体 {ok:true}，防止 Vite 代理返回 SPA fallback / 代理错误 JSON 导致误判。 */
export async function ping(): Promise<{ ok: boolean }> {
  const resp = await fetch(apiUrl(`${BASE}${PATH_PING}`), {
    signal: AbortSignal.timeout(PING_TIMEOUT),
  });
  if (!resp.ok) throw new Error("ping failed");
  const data: unknown = await resp.json();
  if (data && typeof data === "object" && "ok" in data && (data as any).ok === true) {
    return data as { ok: boolean };
  }
  throw new Error("invalid ping response");
}

/** 获取终端点下的 API（不在 /api 下）。 */
async function rootFetch<T>(path: string): Promise<T> {
  const resp = await fetchWithConnTimeout(apiUrl(path), {
    signal: combineSignal(undefined, FETCH_TIMEOUT),
  }, FETCH_TIMEOUT);
  if (!resp.ok) throw new Error(`${path} fetch failed`);
  return resp.json();
}

/** 获取后端详细版本信息（GET /version）。 */
export function getVersionInfo(): Promise<VersionInfo> {
  return rootFetch<VersionInfo>(PATH_VERSION);
}

/** 获取服务器运行时状态（GET /status）：uptime、Python 版本、平台。 */
export function getRuntimeStatus(): Promise<RuntimeStatus> {
  return rootFetch<RuntimeStatus>(PATH_STATUS);
}

/** 获取 MCP 服务器连接状态（GET /api/mcp/status）。 */
export function getMCPStatus(): Promise<MCPStatusResult> {
  return request<MCPStatusResult>("GET", PATH_MCP_STATUS);
}

// ── 并发配置 ────────────────────────────────────

export function getConcurrencyConfig(): Promise<{ max_concurrent: number }> {
  return request<{ max_concurrent: number }>("GET", PATH_LLM_CONCURRENCY);
}

// ── MCP 配置 ──────────────────────────────────────

export function getMCPConfig(): Promise<MCPConfig> {
  return request<MCPConfig>("GET", PATH_MCP_CONFIG);
}

export function updateMCPConfig(config: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("PUT", PATH_MCP_CONFIG, { config });
}

// ── 密钥管理 ─────────────────────────────────────

export function getSecrets(): Promise<SecretsConfig> {
  return request<SecretsConfig>("GET", PATH_SECRETS);
}

export function updateSecrets(secrets: Record<string, string | null>): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("PUT", PATH_SECRETS, { secrets });
}

// ── 上传配置 ────────────────────────────────────

export function getUploadConfig(): Promise<UploadConfig> {
  return request<UploadConfig>("GET", PATH_UPLOAD_CONFIG);
}

// ── 生成流重连 ──────────────────────────────────────

/** 订阅正在进行的生成流（用于页面刷新后重连 SSE）。*/
export async function subscribeGenerationStream(
  sessionId: string,
  signal?: AbortSignal,
): Promise<ReadableStreamDefaultReader<Uint8Array>> {
  const resp = await fetchWithConnTimeout(apiUrl(`${BASE}${PATH_CONVERSATIONS}/${sessionId}/stream`), {
    signal,
  }, FETCH_TIMEOUT);
  if (!resp.ok) {
    const text = await resp.text().catch(() => "Unknown error");
    throw new Error(text);
  }
  if (!resp.body) throw new Error("Response body is null");
  return resp.body.getReader();
}

/** 订阅会话状态变更 SSE（替代轮询）。传入关注的会话 ID 列表。 */
export async function subscribeSessionStatus(
  sessionIds: string[],
  signal?: AbortSignal,
): Promise<ReadableStreamDefaultReader<Uint8Array>> {
  const ids = sessionIds.join(",");
  const resp = await fetchWithConnTimeout(apiUrl(`${BASE}${PATH_SESSIONS_STATUS_STREAM}?session_ids=${encodeURIComponent(ids)}`), {
    signal,
  }, FETCH_TIMEOUT);
  if (!resp.ok) {
    const text = await resp.text().catch(() => "Unknown error");
    throw new Error(text);
  }
  if (!resp.body) throw new Error("Response body is null");
  return resp.body.getReader();
}

/** 检查错误是否表示与后端的连接失败。
 *  原生 fetch 网络失败抛 TypeError；Vite 代理不可达返回 502/503/504；
 *  超时为 DOMException(name="TimeoutError")。 */
export function isConnectionError(e: unknown): boolean {
  if (e instanceof TypeError) return true;
  if (e instanceof DOMException && e.name === "TimeoutError") return true;
  const status = (e as any)?.status;
  if (typeof status === "number" && (status === HTTP_BAD_GATEWAY || status === HTTP_SERVICE_UNAVAILABLE || status === HTTP_GATEWAY_TIMEOUT)) return true;
  return false;
}

export { readWithTimeout };

/** 终止正在进行的生成（用户点击停止按钮时调用）。 */
export async function abortGeneration(
  sessionId: string,
): Promise<{ ok: boolean; session_id: string }> {
  return request<{ ok: boolean; session_id: string }>(
    "POST",
    `${PATH_CONVERSATIONS}/${sessionId}/abort`,
  );
}
