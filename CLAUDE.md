# CLAUDE.md

IrisFlow v1.0.0 — LLM Chat + Agent 控制台。后端 FastAPI + OpenAI-compatible 网关，前端 Vite + Vue 3。

## 命令

```bash
# 统一启动（推荐）
pnpm dev                          # 一键启动前后端，动态端口分配
pnpm start                        # 生产模式：构建前端 + 后端 serve

# 后端
cd backend && uv sync
uv run uvicorn main:app --reload --timeout-graceful-shutdown 3
uv run pyright --project pyrightconfig.json   # 类型检查

# 前端
cd frontend && pnpm install
pnpm dev                          # http://localhost:3000
npx vue-tsc --noEmit             # 类型检查
```

## 核心概念

**会话 (Session)** vs **对话 (Message Round)**：会话是整个聊天记录容器，对话是会话内的单轮用户↔LLM 交互。

会话四色状态灯：🟢 可发送（idle/completed）→ 🟡 生成中（generating，脉冲）→ 🔴 排队中（pending）→ ⚫ 未知（unknown）。所有异常回到 completed。

后端是状态的唯一权威源。客户端订阅 `GET /api/sessions/status-stream` 获取实时状态推送，`GET /api/conversations` 获取列表元数据（不含状态）。

## 关键设计

- **config.py** — `AppConfig` 单例，配置从 `data/*.json` 加载，无 `.env`。`${VAR}` 密钥替换。
- **agent.py** — `Agent(Chat)`，工具调用推理循环。`run_stream()` 遇自定义工具暂停，内置工具自动执行。
- **llm/tools/** — `ToolExecutor` 单例，`Tool` 抽象基类 + 每工具独立模块。MCP 工具通过 `register()` 动态注入。
- **mcp.py** — `MCPManager` 单例，标准 MCP 协议（JSON-RPC 2.0 over stdio/HTTP），运行时增删 + 文件监听热重载。
- **client.py** — OpenAI-compatible API 封装，流式 SSE 事件（reasoning/content/tool_calls）。
- **sessions.py** — `SessionStore`：SQLite 持久化，会话仅由用户手动删除、不做自动过期驱逐，`asyncio.Lock` 守护。
- **router.py** — 统一 FIFO 队列 + LLM 健康门控 + 并发控制，`asyncio.shield()` 保护 cleanup。
- **main.py** — 生产模式下检测 `frontend/dist/` 自动 serve 静态文件 + SPA fallback，单端口访问。
- **scripts/** — `dev.js` / `start.js` 动态端口分配 + 进程编排，`.ports.json` 供 Vite 读取后端端口。
- **vite.config.ts** — 开发时 `/api`、`/version`、`/status` 全部代理到后端，前端始终同源请求。
- **constants.py / constants.ts** — 前后端共享常量，无硬编码字符串。

## 前端架构

- **API** — `api/client.ts`：fetch 封装 + SSE 流式解析，开发走 Vite 代理、生产同源请求。
- **useAgent** — 统一 chat/agent 状态管理，每会话独立状态 Map。
- **toolMetadata** — 工具元数据模块级单例，`discoverTools()` 从后端拉取。
- **FloatingWindow** — 通用浮窗框架：Teleport、拖拽、置顶、z-index 分层管理。
- **Markdown** — markdown-it + KaTeX + highlight.js。

## 文档维护

修改代码时，检查以下文档是否需要同步更新：

| 变更类型 | README | CONTRIBUTING | CHANGELOG |
|---------|:---:|:---:|:---:|
| 版本号 | ✅ 徽章 | — | — |
| 项目结构（增/删/移文件） | ✅ 结构树 | — | — |
| 关键设计 / 架构 | — | ✅ 关键设计 | — |
| 代码规范 | — | ✅ 代码规范 | — |
| 开发命令 / 环境要求 | ✅ 快速开始 | ✅ 环境搭建 | — |
| 功能变更 | — | — | ✅ 待发布 |

各文档职责：**README** = 项目门面（介绍、快速开始、结构、架构）→ **CONTRIBUTING** = 参与指南（规范、工作流、PR 前必读）→ **CHANGELOG** = 版本历史。
