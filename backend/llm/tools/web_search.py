"""网页搜索工具 — DuckDuckGo Instant Answer + HTML 回退。"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import cast

import httpx

from core.config import get_user_agent
from llm.constants import (
    WEB_SEARCH_DEFAULT_COUNT,
    WEB_SEARCH_HTML_FALLBACK,
    WEB_SEARCH_MAX_COUNT,
    WEB_SEARCH_RETRIES,
    WEB_SEARCH_RETRY_DELAY,
    WEB_SEARCH_TIMEOUT,
)
from llm.models import ToolDefinition
from llm.tools.base import Tool

logger = logging.getLogger(__name__)


def _strip_html(text: str) -> str:
    """移除 HTML 标签。"""
    return re.sub(r"<[^>]+>", "", text).strip()


class WebSearchTool(Tool):
    """网页搜索 — DuckDuckGo Instant Answer API → HTML 回退。"""

    icon = "fa-solid fa-globe"
    label = "网页搜索"
    order = 1.0

    definition = ToolDefinition(
        name="web_search",
        description=(
            "【优先使用】搜索互联网获取最新信息。这是你的首要信息来源——"
            "任何超出知识截止日期、需要实时数据、新闻、事实核查的问题，必须优先调用此工具。"
            "不要猜测答案，先搜索再回答。搜索结果中的链接需要用 open_url 打开以获取完整内容。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词。使用精确的关键词组合以提高命中率。",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最多返回结果数（默认 5，建议设 5-8 以获得足够的交叉验证素材）",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    )

    async def execute(self, query: str, max_results: int = WEB_SEARCH_DEFAULT_COUNT) -> str:  # type: ignore[override]
        """搜索互联网并返回结果。

        先尝试 DuckDuckGo Instant Answer API，无结果时回退到 HTML 搜索页面。
        网络请求超时由 WEB_SEARCH_TIMEOUT 控制（≤10s），失败时自动重试。
        """
        max_results = max(1, min(max_results, WEB_SEARCH_MAX_COUNT))

        for attempt in range(WEB_SEARCH_RETRIES + 1):
            try:
                return await self._do_search(query, max_results)
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
                logger.warning("web_search 连接失败 (attempt %d/%d): %s", attempt + 1, WEB_SEARCH_RETRIES + 1, e)
                if attempt < WEB_SEARCH_RETRIES:
                    await asyncio.sleep(WEB_SEARCH_RETRY_DELAY)
                    continue
                raise RuntimeError("搜索服务暂时不可用（网络连接失败），请稍后重试。") from e
            except Exception as e:
                logger.warning("web_search 异常: %s", e)
                raise RuntimeError(f"搜索失败: {e}") from e

        raise RuntimeError("搜索服务暂时不可用，请稍后重试。")

    async def _do_search(self, query: str, max_results: int) -> str:
        """执行单次搜索（Instant Answer → HTML 回退）。"""
        results: list[str] = []

        async with httpx.AsyncClient(timeout=WEB_SEARCH_TIMEOUT, follow_redirects=True) as client:
            # 1) Instant Answer API
            try:
                resp = await client.get(
                    "https://api.duckduckgo.com/",
                    params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                    headers={"User-Agent": get_user_agent()},
                )
                data = resp.json()
                abstract = data.get("AbstractText", "")
                if abstract:
                    source = data.get("AbstractURL", "")
                    results.append(f"📌 {abstract}\n   来源: {source}")
                for topic in data.get("RelatedTopics", [])[:max_results - len(results)]:
                    if isinstance(topic, dict):
                        topic = cast(dict[str, object], topic)
                        text = str(topic.get("Text", ""))
                        url = str(topic.get("FirstURL", ""))
                        if text:
                            results.append(f"• {_strip_html(text)}\n   {url}")
            except httpx.TimeoutException:
                logger.warning("DuckDuckGo Instant Answer API 超时，回退到 HTML 搜索")
            except Exception as e:
                logger.warning("DuckDuckGo Instant Answer API 失败: %s", e)

            # 2) HTML 搜索回退
            if len(results) < WEB_SEARCH_HTML_FALLBACK:
                try:
                    resp = await client.get(
                        "https://html.duckduckgo.com/html/",
                        params={"q": query},
                        headers={"User-Agent": get_user_agent()},
                    )
                    for match in re.finditer(
                        r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
                        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
                        resp.text, re.DOTALL,
                    ):
                        if len(results) >= max_results:
                            break
                        url = match.group(1)
                        title = _strip_html(match.group(2))
                        snippet = _strip_html(match.group(3))
                        results.append(f"• **{title}**\n   {snippet}\n   {url}")
                except httpx.TimeoutException:
                    logger.warning("DuckDuckGo HTML 搜索超时")
                except Exception as e:
                    logger.warning("DuckDuckGo HTML 搜索失败: %s", e)

        if not results:
            return f"未找到与 '{query}' 相关的结果。"
        return "\n\n".join(results[:max_results])
