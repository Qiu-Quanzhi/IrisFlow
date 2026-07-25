"""工具基类。

所有工具（内置、MCP 注入）均遵循此接口。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from llm.models import ToolDefinition


class Tool(ABC):
    """工具基类。

    每个工具需提供 ``definition`` 类属性和 ``execute()`` 方法。

    UI 元数据（icon / label / order）由后端权威定义，
    前端通过 ``GET /api/tools`` 获取，不做任何硬编码。

    用法::

        class MyTool(Tool):
            definition = ToolDefinition(
                name="my_tool",
                description="描述",
                parameters={...},
            )
            icon = "fa-solid fa-star"
            label = "我的工具"
            order = 5.0

            async def execute(self, **kwargs) -> str:
                return f"结果: {kwargs}"

        tool_executor.register_tool(MyTool())
    """

    definition: ToolDefinition  # 子类必须覆盖为类属性

    # ── UI 元数据（后端权威，前端通过 GET /api/tools 获取） ──
    icon: str = "fa-solid fa-wrench"   # Font Awesome 图标类
    label: str = ""                     # 中文显示名（空则回退到 name）
    order: float = 100.0                # 排序权重（越小越靠左）

    @property
    def name(self) -> str:
        """工具名称（从 definition 派生）。"""
        return self.definition.name

    @abstractmethod
    async def execute(self, **kwargs: object) -> str:
        """执行工具，返回结果字符串。"""
        ...
