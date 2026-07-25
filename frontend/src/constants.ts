/** IrisFlow 前端常量 —— 全模块共享的字符串、配置键、枚举值。

 *  所有非 UI 展示文本的硬编码字符串集中于此，方便维护与搜索。
 *  UI_* 前缀常量用于展示文案，未来 i18n 可直接替换为 $t() 调用。
 */

import type { SessionSettings, SessionSettingsPreset } from "./types/api";

// ── 会话 ──────────────────────────────────────────

export const DEFAULT_TITLE = "无标题";

// ── 会话状态 ──────────────────────────────────────

export const STATUS_IDLE = "idle" as const;
export const STATUS_GENERATING = "generating" as const;
export const STATUS_COMPLETED = "completed" as const;
export const STATUS_PENDING = "pending" as const;
export const STATUS_UNKNOWN = "unknown" as const;

// ── 消息状态（每轮 assistant 对话的终止状态，后端权威）─

export const MSG_QUEUED = "queued" as const;
export const MSG_GENERATING = "generating" as const;
export const MSG_COMPLETED = "completed" as const;
export const MSG_ABORTED = "aborted" as const;

// ── 消息角色 ──────────────────────────────────────

export const ROLE_USER = "user" as const;
export const ROLE_ASSISTANT = "assistant" as const;
export const ROLE_SYSTEM = "system" as const;
export const ROLE_TOOL = "tool" as const;

// ── 思考状态 ──────────────────────────────────────

export const THINK_NONE = "none" as const;
export const THINK_THINKING = "thinking" as const;
export const THINK_DONE = "done" as const;

// ── SSE 事件类型 ──────────────────────────────────

export const SSE_REASONING = "reasoning";
export const SSE_CONTENT = "content";
export const SSE_TOOL_CALLS = "tool_calls";
export const SSE_TOOL_CALL = "tool_call";
export const SSE_TOOL_RESULT = "tool_result";
export const SSE_SESSION = "session";
export const SSE_TITLE = "title";
export const SSE_ERROR = "error";
export const SSE_STATUS = "status";
export const SSE_DONE = "[DONE]";

// ── Workflow 条目类型 ─────────────────────────────

export const WF_THINK = "think";
export const WF_TOOL_CALL = "tool_call";
export const WF_TOOL_RESULT = "tool_result";

// ── 结束原因 ──────────────────────────────────────

export const FINISH_TOOL_CALLS = "tool_calls";

// ── 输入框草稿（无活跃会话时的 key） ──────────────

export const DRAFT_NEW = "__new__";

// ── 超时与间隔（client.ts / App.vue）────────────────

export const FETCH_TIMEOUT = 30_000;        // fetch 连接超时（ms）
export const SSE_READ_TIMEOUT = 720_000;    // SSE 流读取超时（ms）—— 须 ≥ 后端 TOOL_EXECUTION_TIMEOUT + LLM 响应余量
export const STATUS_READ_TIMEOUT = 300_000; // SSE 状态订阅读取超时（ms）
export const PING_TIMEOUT = 5000;           // 心跳 ping 超时（ms）
export const HEARTBEAT_INTERVAL = 3000;     // 心跳间隔（ms）
export const TOOL_REFRESH_INTERVAL = 30_000; // MCP 工具列表后台刷新间隔（ms）—— 覆盖健康检查自动重连等非手动触发场景

// ── SSE 重连（ConversationList.vue）────────────────

export const STATUS_RECONNECT_INIT = 1000;   // 初始重连延迟（ms）
export const STATUS_RECONNECT_MAX = 30000;   // 最大重连延迟（ms）

// ── HTTP 错误码（client.ts）─────────────────────

export const HTTP_NOT_FOUND = 404;
export const HTTP_BAD_GATEWAY = 502;
export const HTTP_SERVICE_UNAVAILABLE = 503;
export const HTTP_GATEWAY_TIMEOUT = 504;

// ── UI 动画（ConversationList.vue）────────────────

export const FLASH_DURATION = 800;            // 列表闪烁动画时长（ms）

// ── 滚动行为（ChatPanel.vue）─────────────────────

export const SCROLL_THRESHOLD = 48;           // 判定"在底部"的阈值（px）
export const SCROLL_DEFY_LIMIT = 2;           // 用户上滚违抗次数上限
export const FORCE_SCROLL_DELAY = 120;        // 强制滚动延迟（ms）
export const HISTORY_SCROLL_DELAY = 100;      // loadHistory 后滚动延迟（ms）

// ── 日期分组（ConversationList.vue）──────────────

export const DAY_MS = 86400000;               // 一天的毫秒数
export const GROUP_WEEK_DAYS = 7;             // "7天内" 分组天数
export const GROUP_MONTH_DAYS = 30;           // "30天内" 分组天数

// ── 默认启用的工具（ChatPanel.vue / ChatInput.vue）────
//   所有工具通过 GET /api/tools 动态发现，元数据由后端权威提供。
//   默认不启用任何工具，用户需在 ChatInput 工具栏手动开启。

export const DEFAULT_ENABLED_TOOLS: string[] = [];

// ── 设置默认值（ChatInput.vue / SettingsPanel.vue）

export const DEFAULT_MAX_CONCURRENT = 1;       // 默认最大并发数
export const MAX_CONCURRENT_UPPER = 20;        // 最大并发数上限
export const DEFAULT_MAX_SIZE_MB = 10;         // 默认上传大小（MB）

// ── 默认会话设定 ──────────────────────────────────

/** 前端工厂默认值 — "点击设置"的赋值来源 */
export const FACTORY_SESSION_DEFAULTS: SessionSettings = {
  system_prompt: "主动使用工具获取和验证信息，可以循环使用，直至确定为止。不要编造不确定的内容，引用信息时说明来源。",
  temperature: 0.7,
  max_tokens: 4096,
  top_p: 0.95,
  top_k: 64,
  presence_penalty: 0,
  frequency_penalty: 0,
  repeat_penalty: 1.1,
};

// ── 内置会话参数预设 ──────────────────────────────

export const SESSION_PRESETS: SessionSettingsPreset[] = [
  {
    id: "precise",
    icon: "fa-solid fa-bullseye",
    name: "精确",
    description: "低温、窄采样，适合代码与事实查询",
    settings: {
      system_prompt: null, temperature: 0.2, max_tokens: null,
      top_p: 0.15, top_k: null, presence_penalty: null,
      frequency_penalty: 0.3, repeat_penalty: null,
    },
  },
  {
    id: "casual",
    icon: "fa-solid fa-comments",
    name: "日常",
    description: "温和随机性，适合闲聊与陪伴",
    settings: {
      system_prompt: null, temperature: 0.8, max_tokens: null,
      top_p: 0.9, top_k: null, presence_penalty: 0.4,
      frequency_penalty: null, repeat_penalty: null,
    },
  },
  {
    id: "creative",
    icon: "fa-solid fa-feather",
    name: "创作",
    description: "高温、宽采样，适合创意写作与头脑风暴",
    settings: {
      system_prompt: null, temperature: 1.0, max_tokens: null,
      top_p: 0.95, top_k: null, presence_penalty: null,
      frequency_penalty: 0.2, repeat_penalty: 1.05,
    },
  },
];

// ── 会话设定 UI 文本 ──────────────────────────────

export const UI_SESSION_SETTINGS = "会话参数";
export const UI_PRESET = "预设";
export const UI_BASIC = "基础";
export const UI_ADVANCED = "高级";
export const UI_RESET_DEFAULT = "重置为默认值";
export const UI_SYSTEM_PROMPT = "系统提示词";
export const UI_TEMPERATURE = "温度";
export const UI_MAX_TOKENS = "最大输出 Token";
export const UI_TOP_P = "核采样 (Top-P)";
export const UI_TOP_K = "Top-K";
export const UI_PRESENCE_PENALTY = "存在惩罚";
export const UI_FREQUENCY_PENALTY = "频率惩罚";
export const UI_REPEAT_PENALTY = "重复惩罚";

// ── 复制反馈（MessageBubble.vue）────────────────

export const COPY_FEEDBACK_DURATION = 2000;    // 复制成功反馈显示时长（ms）

// ── SSE 解析（useAgent.ts / ConversationList.vue）─

export const SSE_DATA_PREFIX = "data: ";
export const SSE_DATA_PREFIX_LEN = 6;  // "data: ".length

// ── SSE 哨兵值 ─────────────────────────────────

export const STATUS_REPLACED = "replaced";

// ── UI 文案（未来 i18n 候选）──────────────────────
//   UI_* 常量用于展示文案，集中管理便于未来 i18n 迁移。

export const UI_STATUS_GENERATING = "生成中";
export const UI_STATUS_PENDING = "排队等待中";
export const UI_STATUS_UNKNOWN = "状态未知";
export const UI_STATUS_IDLE = "可发送";
export const UI_QUEUED_LABEL = "队列中";
export const UI_ABORTED_LABEL = "已终止";
export const UI_THINKING_LABEL = "思考中";
export const UI_PROCESSING_LABEL = "处理中";
export const UI_COMPLETED_LABEL = "已完成";
export const UI_THOUGHT_LABEL = "已思考";
export const UI_WELCOME_TITLE = "IrisFlow";
export const UI_WELCOME_SUBTITLE = "输入消息，开始对话";
export const UI_INPUT_PLACEHOLDER = "输入消息，开始对话";
export const UI_NEW_CHAT = "新建对话";
export const UI_NO_CONVERSATIONS = "暂无会话";
export const UI_LOADING = "加载中";
export const UI_JUMP_BOTTOM = "回到底部";
export const UI_COPY = "复制";
export const UI_COPIED = "已复制";
export const UI_STOP = "停止生成";
export const UI_THINK_MODE = "思考模式";
export const UI_FAST_MODE = "快速模式";
export const UI_PIN = "置顶";
export const UI_UNPIN = "取消置顶";
export const UI_RENAME = "重命名";
export const UI_DELETE = "删除";
export const UI_CLEAR_ALL = "清空";
export const UI_CLEAR_ALL_CONFIRM = "确认清空全部会话？";
export const UI_CLEAN_UP = "清理";
export const UI_CLEAN_UP_CONFIRM = "确认清理下方会话？";
export const UI_TODAY = "今天";
export const UI_YESTERDAY = "昨天";
export const UI_WITHIN_WEEK = "7天内";
export const UI_WITHIN_MONTH = "30天内";
export const UI_PINNED_GROUP = "置顶";

// ── 服务器状态展示文案（状态 ID → 中文）────────────

export const UI_HEALTH_HEALTHY = "健康";
export const UI_HEALTH_UNHEALTHY = "异常";
export const UI_HEALTH_NO_DEFAULT_MODEL = "无默认模型";
export const UI_HEALTH_UNREACHABLE = "不可达";
export const UI_HEALTH_UNKNOWN = "未知";

export const UI_MCP_RUNNING = "运行中";
export const UI_MCP_STOPPED = "已停止";
export const UI_MCP_ERROR = "异常";

/** LLM 健康状态 ID → 展示文案 */
export const HEALTH_STATUS_LABEL: Record<string, string> = {
  healthy: UI_HEALTH_HEALTHY,
  unhealthy: UI_HEALTH_UNHEALTHY,
  no_default_model: UI_HEALTH_NO_DEFAULT_MODEL,
  unreachable: UI_HEALTH_UNREACHABLE,
  unknown: UI_HEALTH_UNKNOWN,
};

// ── 通用操作 ─────────────────────────────────────

export const UI_CLEAR = "清除";
export const UI_CLOSE = "关闭";
export const UI_SAVE = "保存";
export const UI_SAVING = "保存中…";
export const UI_SAVE_FAILED = "保存失败";
export const UI_DEFAULT = "默认";
export const UI_MORE = "更多";
export const UI_ON = "开";
export const UI_OFF = "关";
export const UI_DOWNLOAD = "下载";
export const UI_OPEN_IN_NEW_TAB = "在新标签页打开";
export const UI_REFRESH = "刷新状态";

// ── 断联占屏 ─────────────────────────────────────

export const UI_CONNECTION_LOST = "与后端断开连接";
export const UI_AUTO_RECOVER = "重新连接后将自动恢复";
export const UI_MODIFY_SERVER_URL = "下方可修改后端地址";

// ── 设置面板标签 ──────────────────────────────────

export const UI_TAB_SERVER = "服务器";
export const UI_TAB_LLM = "LLM";
export const UI_TAB_MCP = "MCP";
export const UI_TAB_SECRETS = "密钥";
export const UI_TAB_DEFAULTS = "默认参数";
export const UI_TAB_ABOUT = "关于";

// ── 设置面板字段 ──────────────────────────────────

export const UI_SERVER_ADDRESS = "服务器地址";
export const UI_MCP_SERVERS = "MCP 服务器";
export const UI_LLM_GATEWAY = "LLM 网关";
export const UI_STATUS_LABEL = "状态";
export const UI_ADDRESS_LABEL = "地址";
export const UI_MODEL_LABEL = "模型";
export const UI_CONCURRENCY_LIMIT = "并发限制";
export const UI_RUNTIME_INFO = "运行信息";
export const UI_UNCONFIGURED = "未配置";
export const UI_FETCH_FAILED = "获取失败";
export const UI_NO_MCP_SERVERS = "未配置 MCP 服务器";
export const UI_MCP_CONFIG_DESC = "标准 MCP 协议（JSON-RPC 2.0），支持 stdio 子进程和 Streamable HTTP 远程连接。修改后自动 diff 重连，仅重启变更的服务器。";
export const UI_GATEWAY_URL = "网关地址";
export const UI_AUTH_TOKEN = "认证令牌";
export const UI_MAX_CONCURRENT_LABEL = "最大并发生成";
export const UI_SECRETS_VARS = "密钥变量";
export const UI_SECRETS_DESC = "在 LLM、MCP 配置中使用 ${VAR_NAME} 引用密钥，实际请求时自动替换为真实值。";
export const UI_ADD_VARIABLE = "添加变量";
export const UI_KEEP_UNCHANGED = "留空保持不变";
export const UI_ENTER_SECRET_VALUE = "输入密钥值";
export const UI_CLICK_TO_SET = "点击设置";
export const UI_APPLY_DEFAULTS = "应用会话默认设定";

// ── WorkflowDetail / MediaPreview ──────────────────

export const UI_TOOL_CALL = "工具调用";
export const UI_TOOL_RESULT = "工具结果";
export const UI_THOUGHT_PROCESS = "思考过程";
export const UI_TOOL_LABEL = "工具";
export const UI_THOUGHT_CONTENT = "思考内容";
export const UI_CALL_PARAMS = "调用参数";
export const UI_RETURN_RESULT = "返回结果";
export const UI_RAW_DATA = "原始数据";
export const UI_SEARCH_RESULTS = "搜索到 {n} 个网页";
export const UI_FILE_NAME = "文件名";
export const UI_CONTENT_PREVIEW = "内容预览";
export const UI_NO_TEXT_CONTENT = "无文本内容";
export const UI_IMAGE_PREVIEW = "图片预览";
export const UI_VIDEO_PREVIEW = "视频预览";
export const UI_WEBPAGE_PREVIEW = "网页预览";
export const UI_FILE_PREVIEW = "文件预览";

// ── 杂项 ─────────────────────────────────────────

export const UI_SESSION_LIST = "会话列表";
export const UI_SETTINGS = "设置";
export const UI_OPEN_TOOL_PANEL = "打开工具管理浮窗";

/** MCP 服务器状态 ID → 展示文案 */
export const MCP_STATUS_LABEL: Record<string, string> = {
  running: UI_MCP_RUNNING,
  stopped: UI_MCP_STOPPED,
  error: UI_MCP_ERROR,
};
