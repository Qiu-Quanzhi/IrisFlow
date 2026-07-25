"""安全计算器工具 — 数学表达式求值。"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from llm.models import ToolDefinition
from llm.tools.base import Tool

_log = logging.getLogger(__name__)

# ── 安全表达式求值 ─────────────────────────────────────────

_SAFE_MATH: dict[str, Any] = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "pow": pow, "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "pi": lambda: math.pi, "e": lambda: math.e,
}

_SAFE_EXPR = re.compile(r"^[\d\s+\-*/().,%\s\w]+$")


class CalculatorTool(Tool):
    """安全计算器 — 仅允许白名单数学函数 + 受限表达式。"""

    icon = "fa-solid fa-calculator"
    label = "计算辅助"
    order = 2.0

    definition = ToolDefinition(
        name="calculator",
        description=(
            "【必须使用】精确计算数学表达式。支持基本运算符 (+, -, *, /, **)、三角函数、sqrt、log 等数学函数。"
            "任何涉及数字的问题——包括简单的百分比、单位换算、汇率折算、统计数据汇总——都必须用此工具计算。"
            "禁止心算或估算。即便看起来很简单，也要调用此工具以确保 100% 准确。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "数学表达式，如 '2 + 3 * 4' 或 'sqrt(16)' 或 '85 * 0.15'",
                },
            },
            "required": ["expression"],
        },
    )

    async def execute(self, expression: str) -> str:  # type: ignore[override]
        """安全计算数学表达式。表达式不合法或计算失败时抛出异常。"""
        expr = expression.strip()
        if not _SAFE_EXPR.match(expr):
            raise ValueError(f"表达式包含不允许的字符: {expression}")
        result = eval(expr, {"__builtins__": {}}, _SAFE_MATH)
        _log.debug("Calculator: %s = %s", expr, result)
        return str(result)
