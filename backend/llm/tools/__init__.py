"""工具注册表与执行器。

提供工具注册机制和内置工具集合。
MCP 工具通过 register() 注入，无需硬编码。

支持两种注册方式：

1. 内置工具类 — ``tool_executor.register_tool(MyTool())``
2. 动态函数 — ``tool_executor.register("name", fn, definition)``
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import cast

from llm.constants import TOOL_EXECUTION_TIMEOUT
from llm.models import ToolDefinition
from llm.tools.base import Tool

logger = logging.getLogger(__name__)

# ── 内置工具（每个工具独立文件） ──────────────────────────

from llm.tools.web_search import WebSearchTool
from llm.tools.calculator import CalculatorTool
from llm.tools.open_url import OpenUrlTool

BUILTIN_TOOLS: list[Tool] = [
    WebSearchTool(),
    CalculatorTool(),
    OpenUrlTool(),
]


# ── 工具执行器 ─────────────────────────────────────────────


class ToolExecutor:
    """工具注册表与执行器。

    管理内置工具和外部注入工具（MCP、用户自定义）。
    通过唯一的单例 tool_executor 访问。

    用法::

        from llm.tools import tool_executor
        result = await tool_executor.execute("web_search", {"query": "AI news"})
    """

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., object]] = {}
        self._definitions: dict[str, ToolDefinition] = {}
        self._tool_source: dict[str, str] = {}  # tool_name → "内置" | MCP server name
        # UI 元数据（icon/label/order），供 GET /api/tools 返回
        self._tool_meta: dict[str, dict[str, object]] = {}

    @property
    def tools(self) -> dict[str, Callable[..., object]]:
        """返回所有注册的工具名 → 可调用对象。"""
        return dict(self._tools)

    def register(
        self,
        name: str,
        fn: Callable[..., object],
        definition: ToolDefinition | None = None,
        source: str = "unknown",
        icon: str = "fa-solid fa-puzzle-piece",
        label: str = "",
        order: float = 100.0,
    ) -> None:
        """注册一个工具（函数 + 可选定义）。

        适用于 MCP 动态注入等无法预定义类的场景。
        """
        self._tools[name] = fn
        self._tool_source[name] = source
        self._tool_meta[name] = {
            "icon": icon,
            "label": label or name,
            "order": order,
        }
        if definition:
            self._definitions[name] = definition

    def register_tool(self, tool: Tool) -> None:
        """注册一个 Tool 实例。

        内置工具的推荐注册方式。
        """
        self._tools[tool.name] = tool.execute
        self._definitions[tool.name] = tool.definition
        self._tool_source[tool.name] = "内置"
        self._tool_meta[tool.name] = {
            "icon": tool.icon,
            "label": tool.label or tool.name,
            "order": tool.order,
        }

    def unregister(self, name: str) -> None:
        """取消注册一个工具。"""
        self._tools.pop(name, None)
        self._definitions.pop(name, None)
        self._tool_source.pop(name, None)
        self._tool_meta.pop(name, None)

    def get_tool_source(self, name: str) -> str:
        """返回工具的来源（"内置" / MCP 服务器名称 / "unknown"）。"""
        return self._tool_source.get(name, "unknown")

    def get_tool_sources(self) -> dict[str, str]:
        """返回所有工具的 名称 → 来源 映射。"""
        return dict(self._tool_source)

    def get_tools_metadata(self) -> list[dict[str, object]]:
        """返回所有工具的 UI 元数据列表。

        供 GET /api/tools 使用，前端通过此接口获取图标、标签、排序等信息。
        工具定义（description）从 _definitions 中读取。
        """
        result: list[dict[str, object]] = []
        for name in self._tools:
            meta = self._tool_meta.get(name, {})
            entry: dict[str, object] = {
                "name": name,
                "icon": meta.get("icon", "fa-solid fa-puzzle-piece"),
                "label": meta.get("label", name),
                "order": meta.get("order", 100.0),
            }
            # 附加工具描述（供前端展示用）
            if name in self._definitions:
                entry["description"] = self._definitions[name].description
            else:
                entry["description"] = f"外部工具: {name}"
            result.append(entry)
        # 按 order 排序
        result.sort(key=lambda t: (float(t["order"]), str(t["name"])))  # type: ignore[arg-type]
        return result

    @property
    def tool_names(self) -> set[str]:
        """返回所有已注册工具的名称集合。"""
        return set(self._tools.keys())

    def get_definitions(self) -> list[ToolDefinition]:
        """返回所有已注册工具的定义列表。"""
        result: list[ToolDefinition] = []
        for name in self._tools:
            if name in self._definitions:
                result.append(self._definitions[name])
            else:
                result.append(ToolDefinition(
                    name=name,
                    description=f"External tool: {name}",
                    parameters={"type": "object", "properties": {}, "required": []},
                ))
        return result

    def get_definitions_by_names(self, names: list[str]) -> list[ToolDefinition]:
        """按名称列表返回已注册工具的定义（跳过未注册的名称）。"""
        result: list[ToolDefinition] = []
        for name in names:
            if name in self._definitions:
                result.append(self._definitions[name])
        return result

    def can_execute(self, name: str) -> bool:
        """检查工具是否已注册且可执行。"""
        return name in self._tools

    async def execute(self, name: str, arguments: dict[str, object]) -> tuple[str, bool]:
        """执行已注册的工具。

        Args:
            name: 工具名称。
            arguments: 工具参数。

        Returns:
            (结果文本, 是否为错误) — 调用方据此设置 SSE is_error 字段，
            前端负责错误样式的渲染，后端不再将 ERROR_PREFIX 混入原始数据。

        Raises:
            KeyError: 工具未注册。
        """
        fn = self._tools.get(name)
        if fn is None:
            raise KeyError(f"工具 '{name}' 未注册")

        try:
            result = fn(**{k: v for k, v in arguments.items()})
            if hasattr(result, "__await__"):
                result = await asyncio.wait_for(result, timeout=TOOL_EXECUTION_TIMEOUT)  # type: ignore[arg-type]
            # MCP call_tool 也会返回 tuple[str, bool]
            if isinstance(result, tuple):
                r = cast(tuple[object, object], result)
                if len(r) == 2 and isinstance(r[1], bool):
                    return str(r[0]), r[1]
            return str(cast(object, result)), False
        except asyncio.TimeoutError:
            logger.warning("工具 '%s' 执行超时（%ss），已取消", name, TOOL_EXECUTION_TIMEOUT)
            return f"工具 '{name}' 执行超时，已取消。", True
        except Exception as e:
            logger.warning("工具 '%s' 执行失败: %s", name, e)
            return f"工具 '{name}' 执行失败: {e}", True


# ── 单例 + 自动注册内置工具 ────────────────────────────────


tool_executor = ToolExecutor()

for _tool in BUILTIN_TOOLS:
    tool_executor.register_tool(_tool)
