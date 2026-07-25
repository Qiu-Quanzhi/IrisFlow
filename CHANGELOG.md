# Changelog

所有关于本项目的显著变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
并且本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## 1.0.0

### 变更

- **许可证迁移**：Apache 2.0 → [Ryoine 非商业公共许可证 1.0（RNCL-1.0）](./LICENSE.md)。源代码仅供个人非商业使用；商业用途、企业部署、二次分发须取得单独书面授权
- 署名统一为 **邱泉智 QIU Quanzhi（旅禾 Ryoine）**

## 0.0.11

### 变更

- **Bundle 体积优化**：主包 1,692 KB → 72 KB（减少 95%）
  - `highlight.js` 完整引入（~200 种语言）→ `lib/core` + 仅注册 22 种常用语言，未知语言回退到无高亮渲染
  - `katex` 改为动态 `import()` 导入，拆分为独立 chunk（258 KB）
  - `markdown-it` + hljs 语言通过 `markdown-lazy.ts` 懒加载（464 KB），仅在首条消息渲染时触发
  - 浮动组件（`WorkflowDetail`、`MediaPreview`、`SettingsPanel`、`ConversationList`）使用 `defineAsyncComponent` 按需加载
  - 创建 `media-utils.ts` — 零依赖轻量工具模块（`isExternalUrl`、`mediaKindFromUrl`、`IMG_EXTS`、`escapeHtml`），可被任意模块安全导入
  - 创建 `markdown-lazy.ts` — 懒加载包装器，`loadMd()` 异步创建 markdown-it 实例

### 修复

- **`useAgent.ts` TS2322 类型错误**：`rawResult` null 值通过 `?? undefined` 转换为 `string | undefined`
- **会话切换闪烁**：新增 `loadingHistory` 状态，`getConversation` 拉取期间不显示欢迎页
- **首条消息闪烁**：`App.vue` 启动时预热 `loadMd()`，首次渲染瞬间命中缓存，消除纯文本→富文本切换闪烁

## 0.0.10

### 修复

- **WorkflowLog 同轮拆分**：`flushGroup` 重构 — 连续 auto-tool 迭代（无正文 assistant）的 workflowLog 合并为连续流程，以"有正文的 assistant"为断点。消除同一轮 `_generate` 中 workflow 被错误拆分为多个独立 WorkflowLog 的问题
- **resumeStream 卡展开**：页面刷新重连时将非活跃 assistant 的 `streamDone` 置 `true`，防止已完成工具链的 WorkflowLog 永久卡在展开状态
- **双重 WorkflowLog 头**：WorkflowLog 渲染条件移除 `!!msg.content`，纯正文 assistant 不再渲染空的"已完成"WorkflowLog 头

## 0.0.9

### 添加

- **统一启动**：根目录 `pnpm dev` 一键启动前后端（concurrently + wait-on），`pnpm start` 构建前端后由后端 serve 单端口访问
- **动态端口分配**：`scripts/dev.js` / `scripts/start.js` 自动寻找空闲端口，写入 `.ports.json` 供 Vite 和前端读取
- **后端生产模式**：检测 `frontend/dist/` 存在时自动挂载静态文件 + SPA fallback，单端口部署
- **Vite 代理**：开发模式下 `/api`、`/version`、`/status` 统一代理到后端，前端同源请求

### 变更

- **前端 API 客户端同源化**：`getServerUrl()` 始终返回空字符串，不再需要手动配置后端地址
- **设置面板精简**：移除"服务器地址"输入框，改为纯状态刷新按钮
- **断联遮罩精简**：移除后端地址输入框，仅保留自动重连提示
- **启动脚本化**：根 `package.json` 脚本改为调用 `scripts/dev.js` / `scripts/start.js`，支持端口自动协商

### 修复

- **开发模式下 `/version`、`/status` 无法访问**：Vite 代理新增这两条根端点规则

## 0.0.8

### 变更

- **浮窗动画统一**：FloatingWindow 新增内层 `scale(0.97→1)` + `opacity` 组合入场动画（`cubic-bezier` 弹性曲线），关闭时延迟 180ms 等动画播完才通知父组件，避免 `v-if` 销毁截断退出动画
- **工具管理浮窗支持并行多开**：`activePanelGroup`（单一）→ `openGroupPanels`（数组），多个工具组可同时显示在独立浮窗中
- **工具重载后自动清理陈旧面板**：`watch(toolGroups)` 移除已不存在的组对应浮窗

### 修复

- **`saveTools`/`loadTools` 数组引用泄漏**：存储和返回时均使用 `[...tools]` 副本，避免 `handleToggleTool` 的 `.splice()`/`.push()` 变异回流到 `draftStore[DRAFT_NEW]`，导致跨会话工具偏好污染

## 0.0.7

### 修复

- **会话第二条消息 409 拒绝**：H1 双重点击防护过于严格，已完成但等待清理的状态（`finished=True`）误判为活跃。改为仅拒绝 `finished=False` 或 Agent 等待中的会话，且验证在消息修改之前执行，避免 503 拒绝后残留脏消息
- **旧清理任务误删新状态**：`_cleanup_generation_state` 仅凭 session_id 删除，300s 延迟后可能误删同 ID 的新轮次状态。改为对象身份比对（`is state`）后才清理
- **Agent 多次 tool_calls 时间戳不刷新**：`agent_continue` 产生新一轮 tool_calls 时未刷新 `_agent_sessions_ts`，可能被 TTL（600s）误杀
- **开发模式下设置面板"运行信息""关于"获取失败**：Vite 仅代理 `/api`，根端点 `/version`、`/status` 无法到达后端。新增代理规则
- **`pnpm dev` 启动初期大量 ECONNREFUSED**：concurrently 同时启动前后端，Vite 就绪时后端尚未监听端口。引入 `wait-on tcp:8000` 确保后端就绪后再启前端
- **首次打开设置面板直接显示"获取失败"**：ref 初始值为 `null`，API 返回前模板即渲染 `v-else` 分支。新增 `settingsLoading` 标志位统一管控加载态
- **设置面板 MCP 配置描述不准确**：更新 `UI_MCP_CONFIG_DESC` 为"JSON-RPC 2.0 + stdio/Streamable HTTP + diff 重连"；移除描述段落中语义不当的 `<a>` 标签页跳转链接
- **浮窗全面 standardized**：6 个浮窗组件中 ~30 处硬编码中文替换为 `UI_*` 常量，删除 2 个死导入、2 块死 CSS

### 变更

- **后端日志 Windows 中文乱码**：`sys.stdout.reconfigure(encoding="utf-8")` 强制 UTF-8 输出
- **刷新按钮提升为全局控件**：从服务器标签页内移入左侧导航栏底部，与保存按钮并列，统一为图标+文字样式（`.tab-nav-btn`），始终可点击
- **新增常量**：`UI_IMAGE_PREVIEW` / `UI_VIDEO_PREVIEW` / `UI_WEBPAGE_PREVIEW` / `UI_FILE_PREVIEW`

## 0.0.6

### 添加

- **生产模式**：后端启动时检测 `frontend/dist/` 构建产物，自动 serve 前端静态文件 + SPA fallback（Vue Router 客户端路由接管），后端统一在 `:8000` 提供 API + 前端页面
- **Vite 开发代理**：`/api` 请求通过 Vite 代理转发到后端 `localhost:8000`，SSE 长连接禁用缓冲以支持流式响应

### 变更

- **前端统一同源请求**：`getServerUrl()` 返回空字符串、`setServerUrl()` 标记废弃、移除连接断开遮罩的地址输入框、设置面板移除服务器地址行——统一启动后前后端同源，不再需要手动设置后端地址

### 修复

- **旧轮次清理任务竞态**：`_cleanup_generation_state` 增加对象身份（`is`）判断，防止旧轮次延迟清理误删同 `session_id` 的新轮次状态
- **409/503 拒绝后残留脏数据**：`send_message_stream` 验证逻辑前移到修改 `chat` 之前，确保先验证后修改，拒绝后 `chat.messages` 不留残留
- **Agent 续接 TTL 未刷新**：`agent_continue` 在仍有工具调用待处理时刷新时间戳，避免被 TTL 清理误杀
- **Windows 控制台中文乱码**：启动时 `sys.stdout.reconfigure(encoding="utf-8")` 强制 UTF-8 日志输出

## 0.0.5

### 变更

- **README 图片排版修缮**：hero 图居中显示；界面预览区从垂直散落改为 2×2 表格网格布局，图片宽度统一为 380px；修复 `startup.png` 无 `<img>` 标签的问题

## 0.0.4

### 修复

- **双重提交竞态导致孤立任务**：同一会话重复 POST 时第二次请求覆盖 `_active_generations`，第一次任务变为孤儿。现已添加 409 冲突检测
- **`_status_subscribers` 无锁保护**：并发读写时可能触发 `RuntimeError: list changed size during iteration`。新增 `_status_subscribers_lock` 保护所有访问
- **并发限制 TOCTOU 竞态**：计数检查与状态更新非原子，可能超过 `max_concurrent`。新增 `_active_generation_count` 原子计数器替代 store 查询
- **Agent 对象泄漏**：`abort_generation()` 和 `delete_conversation()` 未清理 `_agent_sessions`，Agent 永久驻留内存。两处均已补齐清理逻辑
- **Agent 会话无 TTL**：自定义工具暂停后长期未续接的 Agent 永不过期。新增 `AGENT_SESSION_TTL`（600s）+ `_cleanup_stale_agents()` 定时清理
- **SSE 事件缓冲区内存泄漏**：`state.events` 列表无限增长，仅 300s 清理延迟后释放。生成完成后立即 `clear()`
- **原始异常字符串泄露到 SSE**：`str(e)` 可能暴露内部实现细节。替换为用户友好的中文错误消息
- **`list.pop(0)` O(n) 性能**：替换为 `collections.deque` + `popleft()` O(1)
- **待调度队列无界**：LLM 长时间不可达时无限累积。新增 `MAX_PENDING_QUEUE=50`，超限返回 503
- **后端硬编码协议字符串**：`mcp.py` 中 9 处 `"jsonrpc":"2.0"`、`"tools/list"` 等替换为 `constants.py` 已有常量
- **MCP 协议版本过旧**：`2024-11-05` → `2025-11-25`（当前最新稳定版）
- **`BUILTIN_GROUP_NAME` 重复定义**：`router.py` 本地定义与 `MSG_BUILTIN_GROUP` 一致，替换为导入常量
- **`${VAR}` 静默透传**：未定义密钥变量现在记录 warning 日志，避免配置错误无声无息
- **前端常量缺失**：新增 `HTTP_NOT_FOUND`（替换 3 处硬编码 404）、`MSG_COMPLETED`（与后端对齐）
- **前端 `getToolDisplay()` 重复定义**：提取到 `toolMetadata.ts` 统一导出
- **CSS 硬编码样式重复**：新增 `.text-ellipsis`、`.flex-center`、`.flex-row`、`.transition-fast`、`.gap-*` 全局工具类
- **`.floating-toggle` 重复实现 32px 圆形按钮**：复用已有 `.circle-btn-lg` 全局类
- **README Vite 版本错误**：`Vite 6` → `Vite 8`（实际依赖 `^8.1.5`）
- **`uv.lock` 版本落后**：`0.0.2` → `0.0.4`（运行 `uv lock` 同步）

### 变更

- **TypeScript 升级**：`~5.8.3` → `^6.0.3`，新增 `src/env.d.ts` 声明 `*.css` 模块类型（TS 6 破坏性变更）
- **模板优化**：移除 `ChatPanel.vue` 内联箭头函数（→ `$event`），提取 `ChatInput.vue` 内联 textarea 自调函数
- **工具管理浮窗默认左下角弹出**：`position="bottom-left"` 与底部工具栏对齐

### 变更

- **README 全面完善**：重写功能亮点（聚焦用户交互而非技术实现），新增界面预览、本地部署指引、云端 API、MCP 与密钥配置章节，补充架构设计原则（后端唯一真值源、会话≠对话、FIFO 队列、插件式工具系统），新增 LM Studio / Node.js / Vue / TypeScript 技术栈徽章
- **会话状态灯颜色修正**：CLAUDE.md 与 README 中 pending 状态颜色从 🔵 修正为实际的 🔴（`#e45a3c`），补充 unknown 灰色状态，四色对齐 CSS 定义
- **SessionStore 设计描述修正**：CLAUDE.md 移除已过时的 "LRU（100）+ TTL（1h）"，与实际代码"会话仅由用户手动删除、不做自动过期驱逐"一致

### 修复

- **代码注释用语规范化**：`backend/` 下 9 处"优雅关闭"替换为"有序关闭"（main.py / constants.py / router.py），去除主观修饰
- **项目结构树补遗**：README 结构树补充 `backend/models.py`、`backend/llm/uploads.py`

## 0.0.2

### 修复

- **工具结果浮窗重复显示**：通用 JSON 格式的工具结果在"返回结果"区同时渲染字段列表和原始 JSON 文本，内容完全重复。现已通过 `resultDisplay` 回退逻辑去重
- **工具结果 JSON 解析与工具调用不一致**：`parseResult()` 对 JSON-RPC 信封字段（jsonrpc / id）和 MCP content 的非文本字段直接丢弃，导致工具结果与工具调用参数展示策略不统一。现已重构——信封字段、MCP 其余字段、顶层数组逐项展开均与 `parseFields()` 保持一致
- **`word-break: break-all` 破坏代码可读性**：`WorkflowDetail`、`MessageBubble`、`MediaPreview`、`SettingsPanel`、全局 `style.css` 共计 8 处使用 `word-break: break-all`，导致 JSON / 代码 / URL 在任意字符处断行。全部替换为 `overflow-wrap: break-word`
- **密钥设置页面输入框无样式**：密钥变量名与值输入框使用不存在的 `.input` CSS 类，无背景、边框、内边距等基础样式。改为 `.form-input`
- **密码可见性切换图标语义反转**：密钥值可见时显示闭眼图标、隐藏时显示睁眼图标，与用户直觉相反。已交换为可见→睁眼、隐藏→闭眼

## 0.0.1

### 修复

- **pyright strict 模式名不副实**：`pyrightconfig.json` 中 `reportUnknownVariableType`、`reportUnknownMemberType`、`reportUnknownParameterType`、`reportUnknownArgumentType` 四项被设为 `none`，导致 strict 形同虚设。现已移除，真正启用 Pylance strict 级别检查
- **127 个 strict 类型错误**：使用 `cast()` 在 JSON 反序列化边界处显式标注类型，覆盖 `config.py`、`client.py`、`sessions.py`、`mcp.py`、`router.py`、`agent.py`、`tools/`、`models.py` 共 8 个文件

### 变更

- `reportPrivateUsage` 规则不再单独设为 `error`（已包含在 strict 默认行为中）

## 0.0.0

### 添加

- **LLM 网关客户端**：OpenAI-compatible API 封装，支持流式 SSE 事件（reasoning / content / tool_calls），流式工具调用增量累积
- **Chat 类**：消息历史容器，支持流式/非流式对话
- **Agent 类**：继承 Chat，工具调用推理循环（think → act → observe），支持内置工具自动执行与自定义工具暂停等待
- **工具引擎**：ToolExecutor 单例注册表，内置 web_search（DuckDuckGo）、calculator（安全 eval）、open_url（trafilatura 智能抓取）三个工具
- **MCP 协议支持**：JSON-RPC 2.0 over stdio 子进程传输 + Streamable HTTP 远程传输，自动 initialize 握手 → tools/list 发现 → 注册到 ToolExecutor，支持配置文件监听热重载
- **会话持久化**：SessionStore 基于 SQLite，服务重启后自动恢复全部会话，asyncio.Lock 守护并发安全
- **统一 FIFO 队列**：所有会话入队调度，LLM 健康门控 + 并发控制，asyncio.shield() 保护状态落盘
- **会话状态实时推送**：GET /api/sessions/status-stream SSE 端点，客户端订阅后实时接收会话状态变更
- **Web 控制台**：Vite + Vue 3 + TypeScript SPA，深色主题 + CSS 变量设计令牌体系
- **流式聊天面板**：SSE 实时上屏，reasoning 思考过程展开/折叠，content 逐字渲染
- **工作流日志**：Agent 推理步骤时间线（思考 → 工具调用 → 结果），左列图标 + 竖线连接
- **浮窗框架**：FloatingWindow 通用组件，Teleport 渲染、可拖拽、置顶、视口约束、z-index 分层管理
- **Markdown 渲染**：markdown-it + KaTeX 数学公式 + highlight.js 代码高亮，链接卡片自动检测
- **文件上传**：90+ 文件类型，图片 base64 编码，文档 MarkItDown 自动转 Markdown
- **会话参数面板**：按会话独立配置系统提示词与 LLM 采样参数（temperature、max_tokens、top_p 等），内置预设胶囊
- **会话管理**：会话列表按日期分组，支持置顶/重命名/删除，SSE 实时状态灯（🟢 completed → 🟡 generating → 🔵 pending）
- **配置持久化**：LLM 配置、MCP 服务器配置、会话默认参数均通过 JSON 文件持久化，支持 ${VAR} 密钥引用
- **密钥管理**：设置面板密钥标签页，键值对变量存储于独立 secrets.json，配置字段中 ${变量名} 引用
- **生成流重连**：页面刷新后通过 GET /api/conversations/{id}/stream 续传 SSE 流，恢复实时上屏
- **生成终止**：POST /api/conversations/{id}/abort 取消后台 asyncio Task，立即中断 LLM 调用
- **启动门控与断连检测**：前端启动 ping 后端，运行时心跳检测，断连全屏遮罩
- **日志系统**：控制台 + 文件双输出，session ID 前缀 [sess:xxx] 全链路追踪
- **前后端常量共享**：constants.py / constants.ts 集中管理状态、角色、事件类型、UI 文案等全模块常量
- **CLAUDE.md 文档维护矩阵**：变更类型 → 需同步文档的映射表，四份文档职责边界明确（README = 项目门面、CLAUDE = AI 工作指令、CONTRIBUTING = 参与指南、CHANGELOG = 版本历史）
- **自动化文档同步**：version-bump、standardize 技能纳入 CONTRIBUTING.md 检查，防止文档在维护中遗漏
- **CONTRIBUTING.md 精简**：修复日志路径，删除冗余项目结构树（→ 指向 README），开发工作流增加类型检查命令与文档同步步骤
