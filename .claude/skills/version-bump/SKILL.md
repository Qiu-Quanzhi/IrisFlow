---
name: version-bump
description: 当完成一组功能开发后，同步更新版本号与文档并提交。
---
# 版本更新与文档同步

## 触发条件

用户说 "bump version"、"更新版本"、"同步文档"、"编入 changelog" 或类似表述。

## 流程

### 1. 确定版本号

遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)：

版本格式：主版本号.次版本号.修订号，版本号递增规则如下：

主版本号：当你做了不兼容的 API 修改，

次版本号：当你做了向下兼容的功能性新增，

修订号：当你做了向下兼容的问题修正。

先行版本号及版本编译信息可以加到“主版本号.次版本号.修订号”的后面，作为延伸。

同步版本号到：
- `backend/pyproject.toml` → `version` 字段
- `frontend/package.json` → `version` 字段
- `package.json`（根目录，如存在）→ `version` 字段
- `README.md` → 版本徽章

### 2. 更新 CHANGELOG.md

遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 格式：

```markdown
## X.Y.Z

### 添加
- 新增功能描述

### 变更
- 修改描述

### 修复
- 修复描述
```

### 3. 更新 README.md

- 版本徽章：`[![Version](https://img.shields.io/badge/版本-X.Y.Z-green)]()`
- 如有新增/删除模块，更新 "项目结构" 章节
- 如有新增技术栈，更新 "技术栈" 章节

### 4. 更新 CLAUDE.md

- "Current state" 版本号
- 新增的 API 端点（如有）
- 新增的模块或设计模式（如有）

### 5. 更新 CONTRIBUTING.md

- 环境要求表格中的工具版本号（如有变化）
- 开发环境搭建中的命令（如有变化）
- 关键设计章节（如有架构变更）

### 6. Git 提交

**步骤 0：工作区完整性检查（在编辑任何文件之前执行）**

运行 `git status` 记录当前工作区所有变更（包括 unstaged 和 untracked）。这些变更是本次版本发布的一部分，**必须在后续提交中全部纳入**，不得遗漏：

```
git status    # 记录输出，作为后续"无遗漏"的参照系
```

常见会遗漏的文件类型：
- 根目录 `package.json` / `pnpm-lock.yaml` — 统一启动脚本
- `.gitignore` — 项目级忽略规则变更
- 根目录 `tsconfig.json` / `eslint.config.js` 等工具配置
- 新增的 `docs/` 资源文件

**步骤 1：提交前 staging**

分两次提交：

1. **backend + docs + 根目录配置**：`chore: vX.Y.Z — 简短描述`
   - `git add` 范围：
     - 版本配置文件：`backend/pyproject.toml`、`frontend/package.json`、**根目录 `package.json`**（如存在）
     - `backend/` 下所有修改的 `.py` 文件
     - 文档：`README.md`、`CHANGELOG.md`、`CLAUDE.md`、`CONTRIBUTING.md`（如有修改）
     - **必须包含 `backend/uv.lock`**（`pyproject.toml` 版本号变更会自动触发 lockfile 重写）
     - **必须包含 `pnpm-lock.yaml`**（如根目录 `package.json` 版本号变更）
     - 新资源：`docs/` 目录（截图等）
     - 项目配置：`.gitignore`（如有修改）
   - **逐项对照步骤 0 的 `git status` 输出**，确认每一条变更都已纳入暂存区或明确排除
   - 再次 `git status` 确认无遗漏后提交

2. **frontend**：`chore: frontend version → X.Y.Z`
   - `git add frontend/package.json`
   - **仅此一个文件**，不要 `git add frontend/` 通配
   - 注意：如果 `frontend/package.json` 已在 commit 1 中提交，则跳过此步

**步骤 2：提交后验证**

```
git status    # 必须显示 "nothing to commit, working tree clean"
```

如果仍有未提交文件，对照步骤 0 的输出逐一排查：
- 属于本次发布变更 → 补充提交
- 故意排除（构建产物、本地配置）→ 确认 `.gitignore` 已覆盖

**重要**：提交信息中**禁止**添加 `Co-Authored-By:` 行。仅使用标准 Conventional Commits 格式。

## 示例

```
用户: "bump version to 0.3.0"

→ 0. git status（记录工作区全部变更，作为提交完整性参照系）
→ 1. 编辑 backend/pyproject.toml: version = "0.3.0"
→ 2. 编辑 frontend/package.json: "version": "0.3.0"
→ 3. 编辑 package.json（根目录）: "version": "0.3.0"
→ 4. 编辑 README.md: 版本徽章 → 0.3.0
→ 5. 编辑 CHANGELOG.md: 新增 0.3.0 条目
→ 6. 编辑 CLAUDE.md: 更新版本号
→ 7. 检查 CONTRIBUTING.md: 环境版本、命令、关键设计
→ 8. uv lock（同步 backend/uv.lock）
→ 9. git add backend/pyproject.toml backend/uv.lock backend/... package.json pnpm-lock.yaml .gitignore README.md CHANGELOG.md CLAUDE.md docs/
→ 10. git status（对照步骤 0 输出，逐项确认无遗漏）
→ 11. git commit (backend + docs + 根目录配置)
→ 12. git add frontend/package.json && git commit (frontend)
→ 13. git status（必须 clean）
```
