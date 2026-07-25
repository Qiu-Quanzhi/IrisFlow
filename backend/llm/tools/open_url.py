"""打开网页工具 — 下载 + trafilatura 正文提取。"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

from core.config import get_user_agent
from llm.constants import (
    OPEN_URL_RETRIES,
    OPEN_URL_RETRY_DELAY,
    OPEN_URL_TIMEOUT,
    OPEN_URL_TRUNCATE,
)
from llm.models import ToolDefinition
from llm.tools.base import Tool

logger = logging.getLogger(__name__)


def _strip_html(text: str) -> str:
    """移除 HTML 标签。"""
    return re.sub(r"<[^>]+>", "", text).strip()


class OpenUrlTool(Tool):
    """打开网页 — httpx 下载 + trafilatura 正文提取。"""

    icon = "fa-solid fa-up-right-from-square"
    label = "打开网页"
    order = 1.5

    definition = ToolDefinition(
        name="open_url",
        description=(
            "【搜索后必须跟进】打开指定网址获取网页完整内容。这是搜索的标准后续步骤——"
            "搜索结果仅提供摘要，必须打开最有价值的 1-3 个链接阅读全文以获取细节、核实准确性。"
            "用户提供链接时，必须打开原文阅读后再回复。需要交叉验证信息时，打开多个来源对比。"
            "不要仅凭搜索摘要就下结论——打开原文是验证信息真伪的唯一途径。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要打开的网页地址（完整 URL，从搜索结果或用户消息中提取）",
                },
            },
            "required": ["url"],
        },
    )

    async def execute(self, url: str) -> str:  # type: ignore[override]
        """获取网页内容并提取正文。

        使用 httpx 下载（带超时控制）+ trafilatura 提取正文。
        失败时直接抛出异常，由 ToolExecutor 统一捕获并标记 is_error。
        """
        import trafilatura

        downloaded: str | None = None
        last_error: str | None = None

        for attempt in range(OPEN_URL_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=OPEN_URL_TIMEOUT, follow_redirects=True) as client:
                    resp = await client.get(url, headers={"User-Agent": get_user_agent()})
                    resp.raise_for_status()
                    downloaded = resp.text
                break
            except httpx.TimeoutException:
                last_error = f"打开网页超时: {url}"
                logger.warning("open_url 超时 (attempt %d/%d): %s", attempt + 1, OPEN_URL_RETRIES + 1, url)
            except httpx.HTTPStatusError as e:
                raise RuntimeError(f"网页返回 HTTP {e.response.status_code}: {url}") from e
            except httpx.ConnectError as e:
                last_error = f"无法连接到服务器: {url}"
                logger.warning("open_url 连接失败 (attempt %d/%d): %s — %s", attempt + 1, OPEN_URL_RETRIES + 1, url, e)
            except Exception as e:
                raise RuntimeError(f"无法获取网页: {e}") from e

            if attempt < OPEN_URL_RETRIES:
                await asyncio.sleep(OPEN_URL_RETRY_DELAY)

        if downloaded is None:
            raise RuntimeError(last_error or f"无法获取网页: {url}")

        # 提取标题
        tm = re.search(r"<title[^>]*>(.*?)</title>", downloaded, re.IGNORECASE | re.DOTALL)
        title = _strip_html(tm.group(1)) if tm else ""

        # trafilatura 提取正文（优先 Markdown，回退 TXT）
        text = trafilatura.extract(downloaded, output_format="markdown", with_metadata=True)
        if not text:
            text = trafilatura.extract(downloaded, output_format="txt")

        if not text or not text.strip():
            return f"{url} 无法提取正文内容，可能是纯客户端渲染页面。"

        limit = OPEN_URL_TRUNCATE
        if len(text) > limit:
            text = text[:limit] + f"\n\n…（已截断，共 {len(text)} 字符）"

        header = f"📄 {title}\n{url}\n\n" if title else f"📄 {url}\n\n"
        return header + text.strip()
