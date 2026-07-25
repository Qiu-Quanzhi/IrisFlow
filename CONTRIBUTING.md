# 为 IrisFlow 贡献

感谢你对 **IrisFlow** 的关注！我们欢迎所有形式的贡献——无论是代码、文档、Bug 报告还是创意提案。

## 参与方式

### 🐛 报告 Bug

- 描述清楚复现步骤、预期行为与实际行为。
- 附上日志片段、环境信息（操作系统、Python 版本、浏览器等）。
- 后端日志位于 `logs/backend.log`，前端错误可在浏览器控制台查看。

### 💡 提议新功能

- 先检查已有的 Issue，避免重复。
- 说明使用场景和价值，最好能给出接口草图。
- 涉及 Agent 推理循环、MCP 协议、工具执行等核心模块的改动，请注明可能的影响。

### ✨ 认领任务

- 寻找标记为 `good first issue` 或 `help wanted` 的 Issue 作为起点。
- 尤其是对 Agent 与工具链相关模块的改进——这是本项目的核心能力。

---

## 开发环境搭建

### 前置要求

| 工具 | 版本 | 用途 |
|------|------|------|
| [Python](https://www.python.org/downloads/) | **3.14** | 后端运行时 |
| [uv](https://docs.astral.sh/uv/) | 最新版 | Python 包管理 |
| [Node.js](https://nodejs.org/) | **24** | 前端运行时 |
| [pnpm](https://pnpm.io/installation) | 最新版 | Node 包管理 |
| [Git](https://git-scm.com/) | 最新版 | 版本控制 |

### 获取代码

```bash
git clone 
cd IrisFlow
```

### 统一启动（推荐）

```bash
pnpm install        # 安装根目录依赖
pnpm dev            # 一键启动前后端，自动分配端口
```

前端 `http://localhost:3000`，Vite 代理 `/api` 到后端，同源请求。

### 分别启动后端

```bash
cd backend
uv sync
uv run uvicorn main:app --reload --timeout-graceful-shutdown 3
```

后端运行在 `http://localhost:8000`，API 文档在 `http://localhost:8000/docs`。

### 分别启动前端

```bash
cd frontend
pnpm install
pnpm dev
```

打开 `http://localhost:3000`。

---

## 代码规范

### 后端

- **类型检查**：提交前运行 `uv run pyright --project pyrightconfig.json`，确保零错误。
- **导入顺序**：标准库 → 第三方 → 本地模块。
- **配置**：所有配置从 `data/*.json` 加载，禁止 `.env` 文件。密钥使用 `${VAR}` 占位符。
- **常量**：字符串字面量、魔法数字统一提取到 `constants.py`。

### 前端

- **类型检查**：提交前运行 `npx vue-tsc --noEmit`，确保零错误。
- **常量**：与后端共享的字符串提取到 `constants.ts`。
- **样式**：颜色值使用 CSS 变量，组件 scoped 样式中的可复用模式提取到 `style.css`。
- **图标**：使用 Font Awesome 矢量图标，禁止 emoji 图标。

### 提交信息

- 使用中文撰写，格式：`类型: 简短描述`
- 类型：`feat` / `fix` / `chore` / `refactor` / `docs`
- 示例：`feat: 新增 MCP HTTP 传输支持`

---

完整的项目结构树见 [README.md](./README.md#-项目结构)。

---

## 关键设计

在提交 PR 前，请了解以下核心设计原则：

- **后端是状态的唯一权威源**。前端不自行推断会话状态，所有状态由 SSE 推送。
- **会话（Session）≠ 对话（Message Round）**。会话是聊天记录容器，对话是单轮用户↔LLM 交互。
- **工具模块**：每个工具独立一个模块，继承 `Tool` 抽象基类，通过 `ToolExecutor.register()` 注册。
- **MCP 协议**：标准 JSON-RPC 2.0，支持 stdio 子进程和 Streamable HTTP 两种传输。
- **前端浮窗**：所有浮窗基于 `FloatingWindow` 框架，使用 Teleport 渲染，z-index 分层管理。

---

## 开发工作流

1. 从 `main` 分支创建功能分支。
2. 开发并自测，确保类型检查通过：
   ```bash
   cd backend && uv run pyright --project pyrightconfig.json
   cd frontend && npx vue-tsc --noEmit
   ```
3. 更新 `CHANGELOG.md` 的「待发布」段落。
4. 检查 `README.md` 与 `CONTRIBUTING.md` 是否需同步更新（项目结构、关键设计、环境要求等）。
5. 提交 PR，描述变更内容与测试情况。
6. 等待 Code Review 后合并。
