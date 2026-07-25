"""LLM 模块常量 —— 全模块共享的字符串、枚举值、配置键。

所有硬编码字符串集中于此，方便维护与搜索。
"""

# ── 会话 ──────────────────────────────────────────────

DEFAULT_TITLE = "无标题"
MODE_CHAT = "chat"
MODE_AGENT = "agent"

# ── 会话状态 ──────────────────────────────────────────

STATUS_GENERATING = "generating"
STATUS_COMPLETED = "completed"
STATUS_PENDING = "pending"
STATUS_UNKNOWN = "unknown"
STATUS_REPLACED = "replaced"  # SSE 订阅替换哨兵

# ── 消息状态（每轮 assistant 对话的终止状态）─────────────

MSG_QUEUED = "queued"
MSG_GENERATING = "generating"
MSG_COMPLETED = "completed"
MSG_ABORTED = "aborted"

# ── 消息角色 ──────────────────────────────────────────

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
ROLE_TOOL = "tool"

# ── SSE 事件类型 ──────────────────────────────────────

SSE_REASONING = "reasoning"
SSE_CONTENT = "content"
SSE_TOOL_CALLS = "tool_calls"
SSE_TOOL_CALL = "tool_call"
SSE_TOOL_RESULT = "tool_result"
SSE_SESSION = "session"
SSE_TITLE = "title"
SSE_ERROR = "error"
SSE_STATUS = "status"
SSE_DONE = "[DONE]"

# ── 系统提示词 ──────────────────────────────────────────

SYSTEM_PROMPT = (
    "主动使用工具获取和验证信息，可以循环使用，直至确定为止。"
    "不要编造不确定的内容，引用信息时说明来源。"
)

# ── LLM 客户端（client.py）───────────────────────────────

LLM_TIMEOUT = 120.0           # 非流式 / 流式 API 调用超时（秒）
HEALTH_CHECK_TIMEOUT = 30.0   # 健康检查超时（秒）
LLM_PING_TIMEOUT = 5.0        # 轻量 ping 超时（秒）
SSE_DATA_PREFIX = "data: "    # SSE 行前缀
API_MODELS_PATH = "/models"
API_CHAT_PATH = "/chat/completions"
HEALTH_PING_TEXT = "ping"     # 健康检查测试消息
HEALTH_PING_MAX_TOKENS = 1    # 健康检查 token 限制
ERROR_DETAIL_TRUNCATE = 500   # HTTP 错误详情截断长度
ERROR_RESULT_TRUNCATE = 300   # 健康检查结果截断长度
REASONING_EFFORT_NONE = "none"
THINKING_ENABLED_TYPE = "enabled"

# ── 路由与调度（router.py）─────────────────────────────────

CLEANUP_DELAY = 300.0         # 生成状态清理延迟（秒，给页面刷新留重连窗口）
MAX_PENDING_QUEUE = 50        # 待调度队列最大长度（超过时拒绝新请求）
LLM_RECOVERY_POLL_INTERVAL = 5  # LLM 恢复轮询间隔（秒）
SHUTDOWN_TASK_WAIT = 3.0       # 有序关闭等待 Task 超时（秒）
AGENT_SESSION_TTL = 600.0     # Agent 会话空闲超时（秒）—— 自定义工具暂停后超时未续接即清理
TITLE_MAX_LENGTH = 40          # 自动标题最大字符数
TITLE_CHAR_WINDOW = 1200       # 标题生成对话截断窗口（字符）
TITLE_MESSAGE_WINDOW = 20      # 标题生成最近消息条数
TITLE_MODEL_TEMP = 0.2         # 标题生成模型温度
TITLE_MODEL_MAX_TOKENS = 200   # 标题生成最大 token
SSE_MEDIA_TYPE = "text/event-stream"  # SSE 响应 Content-Type
SSE_HEARTBEAT_INTERVAL = 15.0         # SSE 心跳间隔（秒）—— 工具执行期间无数据时发送注释保活
MCP_RELOAD_TIMEOUT = 30.0           # MCP 配置重载超时（秒）
MCP_HEALTH_CHECK_INTERVAL = 30.0     # MCP 进程健康检查间隔（秒）
MCP_FILE_WATCH_INTERVAL = 3.0       # MCP 配置文件变更检测间隔（秒，远小于健康检查周期）
MCP_SSE_TRUNCATE = 200               # MCP SSE 日志截断长度
MCP_STDERR_BUFFER = 50               # MCP stderr 缓冲区行数上限
SQLITE_BUSY_TIMEOUT = 2000           # SQLite 忙等待超时（ms）

# ── 默认会话设定 ────────────────────────────────────────

DEFAULT_SESSION_SETTINGS: dict[str, object] = {
    "system_prompt": None,
    "temperature": None,
    "max_tokens": None,
    "top_p": None,
    "top_k": None,
    "presence_penalty": None,
    "frequency_penalty": None,
    "repeat_penalty": None,
}

# ── 会话存储（sessions.py）────────────────────────────────

SESSION_ID_LENGTH = 12          # session_id 字符长度

# ── 工具（tools/ 包）──────────────────────────────────────

WEB_SEARCH_TIMEOUT = 8.0        # 网页搜索 HTTP 超时（秒）—— 网络请求 ≤10s
WEB_SEARCH_DEFAULT_COUNT = 5    # 默认搜索结果数
WEB_SEARCH_MAX_COUNT = 10       # 最大搜索结果数
WEB_SEARCH_HTML_FALLBACK = 3    # 回退到 HTML 搜索的阈值
WEB_SEARCH_RETRIES = 1          # 搜索失败重试次数
WEB_SEARCH_RETRY_DELAY = 0.5    # 搜索重试间隔（秒）
OPEN_URL_TIMEOUT = 8.0          # 打开网页 HTTP 超时（秒）—— 网络请求 ≤10s
OPEN_URL_RETRIES = 1            # 打开网页重试次数
OPEN_URL_RETRY_DELAY = 0.5      # 打开网页重试间隔（秒）
OPEN_URL_TRUNCATE = 4000        # 网页内容截断长度（字符）
TOOL_EXECUTION_TIMEOUT = 600.0  # 工具执行硬超时（秒）—— 图片/视频生成需要 3-10 分钟

# ── MCP（mcp.py）───────────────────────────────────────────

MCP_INIT_TIMEOUT = 60.0          # MCP 服务器初始化握手超时（秒）—— 首次 npx 下载可能需 20-30s
MCP_LIST_TOOLS_TIMEOUT = 8.0     # 工具发现超时（秒）
MCP_CALL_TOOL_TIMEOUT = 600.0    # 工具调用超时（秒）—— 图片/视频生成需要 3-10 分钟
MCP_SHUTDOWN_TIMEOUT = 5.0       # MCP 进程有序关闭等待超时（秒）
MCP_HTTP_TIMEOUT = 30.0           # MCP HTTP 请求超时（秒）
MCP_RETRY_INTERVAL = 120.0        # 健康检查自动重连冷却（秒）—— 避免对持续故障的服务器频繁重试

# LLM 健康检查状态 ID（health_check 返回值，前端映射为展示文案）
HEALTH_HEALTHY = "healthy"
HEALTH_NO_DEFAULT_MODEL = "no_default_model"
HEALTH_UNHEALTHY = "unhealthy"
HEALTH_UNREACHABLE = "unreachable"
HEALTH_UNKNOWN = "unknown"

# MCP 服务器连接状态 ID（get_status 返回值，前端映射为展示文案）
MCP_RUNNING = "running"
MCP_STOPPED = "stopped"
MCP_ERROR = "error"

# ── 文件上传（uploads.py）─────────────────────────────────

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 最大上传大小（10 MB）
MAX_TEXT_LENGTH = 80_000             # 提取文本最大长度（~20K tokens）
MB_BYTES = 1024 * 1024              # 兆字节换算

# ── CORS（main.py）─────────────────────────────────────────

CORS_ORIGIN = "*"  # 允许所有来源（局域网访问）

# ── LLM 配置持久化键（config.py / router.py）───────────────

CONFIG_BASE_URL = "base_url"
CONFIG_AUTH_TOKEN = "auth_token"
CONFIG_MODEL = "model"
CONFIG_MAX_CONCURRENT = "max_concurrent"
CONFIG_SYSTEM_PROMPT = "system_prompt"
CONFIG_TEMPERATURE = "temperature"
CONFIG_MAX_TOKENS = "max_tokens"
CONFIG_TOP_P = "top_p"
CONFIG_TOP_K = "top_k"
CONFIG_PRESENCE_PENALTY = "presence_penalty"
CONFIG_FREQUENCY_PENALTY = "frequency_penalty"
CONFIG_REPEAT_PENALTY = "repeat_penalty"

# ── MCP JSON 配置键（config.py / mcp.py）────────────────────

MCP_KEY_MCP_SERVERS = "mcpServers"
MCP_KEY_COMMAND = "command"
MCP_KEY_ARGS = "args"
MCP_KEY_ENV = "env"
MCP_KEY_TRANSPORT = "transport"
MCP_KEY_URL = "url"
MCP_KEY_DISABLED = "disabled"
MCP_KEY_HEADERS = "headers"
MCP_KEY_NAME = "name"
MCP_TRANSPORT_STDIO = "stdio"
MCP_TRANSPORT_HTTP = "http"

# ── JSON-RPC 协议字符串（mcp.py）─────────────────────────────

JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2025-11-25"
MCP_METHOD_INITIALIZE = "initialize"
MCP_METHOD_INITIALIZED = "notifications/initialized"
MCP_METHOD_TOOLS_LIST = "tools/list"
MCP_METHOD_TOOLS_CALL = "tools/call"

# ── MCP 结果字段（mcp.py）───────────────────────────────────

MCP_FIELD_TYPE = "type"
MCP_FIELD_TEXT = "text"
MCP_FIELD_RESOURCE = "resource"
MCP_FIELD_CONTENT = "content"
MCP_FIELD_IS_ERROR = "isError"
MCP_FIELD_INPUT_SCHEMA = "inputSchema"
MCP_FIELD_SERVER_INFO = "serverInfo"
MCP_FIELD_CLIENT_INFO = "clientInfo"
MCP_FIELD_RESULT = "result"
MCP_FIELD_ERROR = "error"

# ── MIME / Content-Type（client.py / mcp.py / uploads.py）────

CONTENT_TYPE_JSON = "application/json"
CONTENT_TYPE_EVENT_STREAM = "text/event-stream"
CONTENT_TYPE_OCTET_STREAM = "application/octet-stream"
CONTENT_TYPE_TEXT = "text/plain"
ACCEPT_HEADER_SSE = "application/json, text/event-stream"
DATA_URL_PREFIX = "data:{};base64,"

# ── 中文提示消息（sessions.py / router.py）───────────────────

MSG_SESSION_NOT_FOUND = "会话不存在"
MSG_AGENT_SESSION_NOT_FOUND = "Agent 会话不存在"
MSG_BUILTIN_GROUP = "内置"

# ── API 响应键（info.py / router.py）─────────────────────────

RESPONSE_KEY_OK = "ok"
SSE_KEY_SESSION_ID = "session_id"
SSE_KEY_LAST_ACCESS = "last_access"
SSE_KEY_TOOL_NAME = "name"
SSE_KEY_TOOL_ARGS = "arguments"
SSE_KEY_TOOL_RESULT = "result"
SSE_KEY_IS_ERROR = "is_error"
