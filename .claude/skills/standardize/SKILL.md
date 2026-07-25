# 代码规范化检查

对项目进行全面代码质量审查与优化，遵循"无需前向兼容、可维护性与最小可行逻辑"原则。

## 触发条件

用户说 "全面检查优化"、"规范化"、"清理代码"、"standardize" 或类似表述。

## 检查维度

### 1. 版本依赖值 — 以项目配置文件为单一来源

- **禁止**在常量文件中硬编码版本号（如 `IRISFLOW_USER_AGENT = "IrisFlow/X.Y.Z"`）
- 版本号应从 `pyproject.toml`（后端）或 `package.json`（前端）动态读取
- 每次版本更新后，检查 `README.md` 中的 curl 示例、徽章是否同步更新

### 2. 硬编码字符串 → 常量

| 类别 | 后端常量文件 | 前端常量文件 |
|------|-------------|-------------|
| 会话状态 | `constants.py` | `constants.ts` |
| 消息角色 | `ROLE_USER/ASSISTANT/SYSTEM/TOOL` | 同名 |
| SSE 事件类型 | `SSE_*` | 同名 |
| HTTP 状态码 | — | `HTTP_*` |
| UI 文案 | — | `UI_*` 前缀常量 |

- 模板中的展示文本应优先使用 `UI_*` 常量（未来 i18n 候选）
- 前端 `SSE_DATA_PREFIX_LEN` 必须用于 `line.slice()` 而非裸数字

### 3. CSS 变量化

- 搜索 `.vue` / `.css` 文件中的 `#` 和 `rgba(`，对照现有 CSS 变量（`--white`、`--accent-bg`、`--error-bg`、`--code-bg` 等）替换
- 无对应变量时在 `:root` 块新增

### 4. 后端代码质量

- **导入清理**：禁止函数内部 re-import，统一使用顶层导入
- **角色字符串**：全部使用 `ROLE_USER` / `ROLE_ASSISTANT` / `ROLE_SYSTEM` / `ROLE_TOOL`
- **魔法数字**：超时、截断长度等移到 `constants.py`
- **异常处理**：避免 `except BaseException: pass`（会吞噬 `CancelledError`），使用 `except Exception:`
- **类型注解**：所有路由处理器应标注返回类型

### 5. 前端代码质量

- **导入顺序**：所有 import 集中在文件顶部
- **消除无意义间接引用**：如 `const X = SOME_CONST` 直接使用原常量
- **消除重复逻辑**：同一正则 / 工具函数在多处使用 → 提取到 `utils/` 或 `composables/`
- **提供 / 注入键**：使用类型化的 `InjectionKey<T>` Symbol

### 6. 样式去重

跨 SFC 的 `<style scoped>` 块中搜索重复属性组合（display、border-radius、padding 等），提取到全局 `style.css`。

### 7. 文档同步

- `README.md`：curl 示例版本号、项目结构树
- `CLAUDE.md`：版本号、组件路径、API 端点列表
- `CONTRIBUTING.md`：环境版本号、开发命令、关键设计是否与 CLAUDE.md 一致
- 检查是否有对已删除文件的残留引用
- 检查注释文案是否符合现状

## 验证

所有修改完成后必须通过（前后端均零错误）：

```bash
cd backend && uv run pyright --project pyrightconfig.json
cd frontend && pnpm build
```
