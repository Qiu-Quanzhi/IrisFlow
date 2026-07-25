"""标准 MCP (Model Context Protocol) 客户端。

通过 JSON-RPC 2.0 over stdio 与 MCP 服务器通信。
使用 subprocess.Popen + 线程 I/O 桥接，兼容 Windows SelectorEventLoop
（uvicorn --reload 在 Windows 上强制使用 SelectorEventLoop，不支持
asyncio.create_subprocess_exec）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Any, Union, cast

import httpx

from core.config import app_config
from llm.constants import (
    ACCEPT_HEADER_SSE,
    CONTENT_TYPE_EVENT_STREAM,
    CONTENT_TYPE_JSON,
    JSONRPC_VERSION,
    MCP_CALL_TOOL_TIMEOUT,
    MCP_ERROR,
    MCP_FIELD_CLIENT_INFO,
    MCP_FIELD_CONTENT,
    MCP_FIELD_ERROR,
    MCP_FIELD_INPUT_SCHEMA,
    MCP_FIELD_IS_ERROR,
    MCP_FIELD_RESOURCE,
    MCP_FIELD_RESULT,
    MCP_FIELD_SERVER_INFO,
    MCP_FIELD_TEXT,
    MCP_FIELD_TYPE,
    MCP_FILE_WATCH_INTERVAL,
    MCP_HEALTH_CHECK_INTERVAL,
    MCP_HTTP_TIMEOUT,
    MCP_INIT_TIMEOUT,
    MCP_KEY_ARGS,
    MCP_KEY_COMMAND,
    MCP_KEY_DISABLED,
    MCP_KEY_ENV,
    MCP_KEY_HEADERS,
    MCP_KEY_NAME,
    MCP_KEY_TRANSPORT,
    MCP_KEY_URL,
    MCP_LIST_TOOLS_TIMEOUT,
    MCP_METHOD_INITIALIZED,
    MCP_METHOD_TOOLS_CALL,
    MCP_METHOD_TOOLS_LIST,
    MCP_PROTOCOL_VERSION,
    MCP_RETRY_INTERVAL,
    MCP_RUNNING,
    MCP_SHUTDOWN_TIMEOUT,
    MCP_SSE_TRUNCATE,
    MCP_STDERR_BUFFER,
    MCP_STOPPED,
    MCP_TRANSPORT_HTTP,
    MCP_TRANSPORT_STDIO,
    SSE_DATA_PREFIX,
)
from llm.models import ToolDefinition

logger = logging.getLogger(__name__)

# 服务器实例类型（stdio 进程 或 HTTP 客户端）
_MCPServer = Union["MCPServerProcess", "MCPHttpClient"]


class MCPServerError(Exception):
    """MCP 服务器通信错误。"""


class MCPServerProcess:
    """管理单个 MCP 服务器子进程。

    使用 subprocess.Popen + 线程 I/O 桥接到 asyncio Queue，
    兼容任何 event loop 类型（包括 Windows SelectorEventLoop）。
    """

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.command = command
        self.args = args or []
        self._env = env
        self._process: subprocess.Popen[bytes] | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._stdout_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_lines: list[str] = []
        self._closed = False
        self._initialized = False  # 子进程启动 ≠ 已完成 initialize 握手
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> dict[str, Any]:
        """启动子进程并执行 MCP 握手初始化。"""
        self._loop = asyncio.get_running_loop()

        env = dict(os.environ)
        if self._env:
            env.update(self._env)

        resolved = shutil.which(self.command)
        if resolved is None:
            raise MCPServerError(
                f"MCP 服务器 '{self.name}' 启动失败: 命令 '{self.command}' 未找到"
            )

        try:
            self._process = subprocess.Popen(
                [resolved, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as e:
            raise MCPServerError(
                f"MCP 服务器 '{self.name}' 启动失败: 命令 '{self.command}' 未找到"
            ) from e
        except Exception as e:
            logger.exception(
                "MCP '%s' 子进程创建异常: cmd=%s args=%s",
                self.name, resolved, self.args,
            )
            raise MCPServerError(
                f"MCP 服务器 '{self.name}' 子进程启动失败 ({type(e).__name__}): {e}"
            ) from e

        # 启动 stdout 读取线程 → asyncio Queue 桥接
        threading.Thread(target=self._read_stdout_thread, daemon=True).start()

        # 启动 stderr 读取线程 → asyncio Queue 桥接
        threading.Thread(target=self._read_stderr_thread, daemon=True).start()

        # 启动 asyncio 侧 stdout 消费者
        self._stdout_task = asyncio.create_task(self._consume_stdout())

        try:
            result = await asyncio.wait_for(
                self._request("initialize", {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    MCP_FIELD_CLIENT_INFO: {
                        "name": app_config.name,
                        "version": app_config.version,
                    },
                }),
                timeout=MCP_INIT_TIMEOUT,
            )

            await self._send_notification(MCP_METHOD_INITIALIZED)

            server_info = result.get(MCP_FIELD_SERVER_INFO, {})
            logger.info(
                "MCP '%s' 已连接: %s v%s",
                self.name,
                server_info.get(MCP_KEY_NAME, "?"),
                server_info.get("version", "?"),
            )
            self._initialized = True
            return result

        except asyncio.TimeoutError:
            stderr_tail = self._stderr_tail()
            await self.stop()
            detail = f"（stderr: {stderr_tail}）" if stderr_tail else ""
            raise MCPServerError(
                f"MCP 服务器 '{self.name}' 初始化超时 ({MCP_INIT_TIMEOUT}s){detail}"
            )
        except MCPServerError as orig:
            stderr_tail = self._stderr_tail()
            await self.stop()
            extra = f"（stderr: {stderr_tail}）" if stderr_tail else ""
            raise MCPServerError(f"{orig}{extra}") from None
        except Exception as e:
            stderr_tail = self._stderr_tail()
            await self.stop()
            detail = f"（stderr: {stderr_tail}）" if stderr_tail else ""
            raise MCPServerError(
                f"MCP 服务器 '{self.name}' 初始化失败: {e}{detail}"
            ) from e

    # ── 线程侧：stdout / stderr 读取 ──────────────────

    def _read_stdout_thread(self) -> None:
        """后台线程：阻塞式读取 stdout，通过 call_soon_threadsafe 推入队列。"""
        assert self._process and self._process.stdout
        assert self._loop is not None
        loop = self._loop
        q = self._stdout_queue
        try:
            while not self._closed:
                line = self._process.stdout.readline()
                if not line:
                    break
                loop.call_soon_threadsafe(q.put_nowait, line)
        except Exception as e:
            logger.warning("MCP '%s' stdout 读取线程异常: %s", self.name, e)
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)  # EOF 通知

    def _read_stderr_thread(self) -> None:
        """后台线程：阻塞式读取 stderr，推入 asyncio Queue。"""
        assert self._process and self._process.stderr
        try:
            while not self._closed:
                line = self._process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.debug("MCP '%s' stderr: %s", self.name, text)
                    self._stderr_lines.append(text)
                    if len(self._stderr_lines) > MCP_STDERR_BUFFER:
                        self._stderr_lines.pop(0)
        except Exception as e:
            logger.warning("MCP '%s' stderr 读取线程异常: %s", self.name, e)

    # ── asyncio 侧：stdout 消费 + JSON-RPC ────────────

    async def _consume_stdout(self) -> None:
        """asyncio 任务：消费 stdout 队列，分发 JSON-RPC 响应/通知。"""
        try:
            while True:
                line_bytes = await self._stdout_queue.get()
                if line_bytes is None:
                    break  # EOF

                text = line_bytes.decode("utf-8", errors="replace").strip()
                if not text:
                    continue

                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    logger.debug("MCP '%s' 非 JSON stdout: %s", self.name, text[:MCP_SSE_TRUNCATE])
                    continue

                if not isinstance(msg, dict):
                    continue
                msg = cast(dict[str, object], msg)

                if "id" in msg:
                    msg_id = int(str(msg["id"]))
                    future = self._pending.pop(msg_id, None)
                    if future is not None and not future.done():
                        if MCP_FIELD_RESULT in msg:
                            future.set_result(msg[MCP_FIELD_RESULT])  # type: ignore[arg-type]
                        elif MCP_FIELD_ERROR in msg:
                            err = msg[MCP_FIELD_ERROR]
                            if isinstance(err, dict):
                                _err = cast(dict[str, object], err)
                                err_msg = str(_err.get("message", "未知错误"))
                                err_code = str(_err.get("code", "?"))
                            else:
                                err_msg = str(err)
                                err_code = "?"
                            future.set_exception(
                                MCPServerError(
                                    f"MCP '{self.name}' 返回错误: {err_msg} (code {err_code})"
                                )
                            )
                elif "method" in msg:
                    method = str(msg.get("method", ""))
                    logger.debug("MCP '%s' 收到通知: %s", self.name, method)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not self._closed:
                logger.warning("MCP '%s' stdout 消费异常: %s", self.name, e)
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(
                        MCPServerError(f"MCP 服务器 '{self.name}' 已断开")
                    )
            self._pending.clear()

    # ── JSON-RPC 通信 ─────────────────────────────────

    async def _request(
        self, method: str, params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """发送 JSON-RPC 请求并等待响应。"""
        assert self._loop is not None  # start() 之后必定已设置
        if self._closed or not self._process or not self._process.stdin:
            raise MCPServerError(f"MCP 服务器 '{self.name}' 未连接")

        self._request_id += 1
        req_id = self._request_id

        future: asyncio.Future[dict[str, Any]] = self._loop.create_future()
        self._pending[req_id] = future

        msg: dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "id": req_id,
            "method": method,
        }
        if params:
            msg["params"] = params

        try:
            line = json.dumps(msg, ensure_ascii=False) + "\n"
            await self._loop.run_in_executor(
                None, self._process.stdin.write, line.encode("utf-8"),
            )
            await self._loop.run_in_executor(None, self._process.stdin.flush)
            return await future
        except Exception as e:
            self._pending.pop(req_id, None)
            if not future.done():
                future.cancel()
            raise MCPServerError(
                f"MCP 请求 '{method}' 失败: {e}"
            ) from e

    async def _send_notification(
        self, method: str, params: dict[str, Any] | None = None,
    ) -> None:
        """发送 JSON-RPC 通知（无 id，不等待响应）。"""
        assert self._loop is not None
        if not self._process or not self._process.stdin:
            return

        msg: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": method}
        if params:
            msg["params"] = params

        try:
            line = json.dumps(msg, ensure_ascii=False) + "\n"
            await self._loop.run_in_executor(
                None, self._process.stdin.write, line.encode("utf-8"),
            )
            await self._loop.run_in_executor(None, self._process.stdin.flush)
        except Exception as e:
            logger.debug("MCP '%s' 通知发送失败: %s", self.name, e)

    # ── 工具操作 ─────────────────────────────────────

    async def list_tools(self) -> list[ToolDefinition]:
        """发现 MCP 服务器提供的工具列表。"""
        try:
            result = await asyncio.wait_for(
                self._request(MCP_METHOD_TOOLS_LIST),
                timeout=MCP_LIST_TOOLS_TIMEOUT,
            )
        except (MCPServerError, asyncio.TimeoutError) as e:
            logger.warning("MCP '%s' 工具发现失败: %s", self.name, e)
            return []

        raw_tools: list[object] = result.get("tools", [])
        definitions: list[ToolDefinition] = []
        for t in raw_tools:
            if not isinstance(t, dict):
                continue
            t = cast(dict[str, object], t)
            definitions.append(ToolDefinition(
                name=str(t.get(MCP_KEY_NAME, "")),
                description=str(t.get("description", "")),
                parameters=cast(dict[str, object], t.get(MCP_FIELD_INPUT_SCHEMA, {})),
            ))
        return definitions

    async def call_tool(
        self, tool_name: str, arguments: dict[str, object],
    ) -> tuple[str, bool]:
        """调用 MCP 工具。

        Returns:
            (结果文本, 是否为错误) — 错误仅通过布尔值传递，
            不再将 "[错误]" 混入原始数据。
        """
        try:
            result = await asyncio.wait_for(
                self._request(MCP_METHOD_TOOLS_CALL, {
                    "name": tool_name,
                    "arguments": arguments,
                }),
                timeout=MCP_CALL_TOOL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return f"MCP 工具 '{tool_name}' 调用超时 ({MCP_CALL_TOOL_TIMEOUT}s)", True
        except MCPServerError as e:
            return f"MCP 工具 '{tool_name}' 调用失败: {e}", True
        except Exception as e:
            logger.warning("MCP '%s' 工具 '%s' 异常: %s", self.name, tool_name, e)
            return f"MCP 工具 '{tool_name}' 执行异常: {e}", True

        is_error = bool(result.get(MCP_FIELD_IS_ERROR, False))

        content = result.get(MCP_FIELD_CONTENT, [])
        if isinstance(content, list):
            content_items = cast(list[object], content)
            parts: list[str] = []
            for item in content_items:
                if isinstance(item, dict):
                    item = cast(dict[str, object], item)
                    item_type = str(item.get(MCP_FIELD_TYPE, ""))
                    if item_type == MCP_FIELD_TEXT:
                        parts.append(str(item.get(MCP_FIELD_TEXT, "")))
                    elif item_type == MCP_FIELD_RESOURCE:
                        resource = item.get(MCP_FIELD_RESOURCE, {})
                        if isinstance(resource, dict):
                            resource = cast(dict[str, object], resource)
                            resource_text = resource.get(MCP_FIELD_TEXT, "")
                            if resource_text:
                                parts.append(str(resource_text))
            result_text = "\n".join(parts) if parts else json.dumps(result, ensure_ascii=False)
            return result_text, is_error

        return json.dumps(result, ensure_ascii=False), is_error

    # ── 生命周期 ─────────────────────────────────────

    def _stderr_tail(self) -> str:
        """返回最近 stderr 输出的最后 10 行（用于错误诊断）。"""
        if not self._stderr_lines:
            return ""
        return " | ".join(self._stderr_lines[-10:])

    async def stop(self) -> None:
        """停止 MCP 服务器进程。"""
        assert self._loop is not None
        self._closed = True
        self._initialized = False

        # 通知 asyncio 消费者结束
        try:
            self._stdout_queue.put_nowait(None)
        except asyncio.QueueFull:
            pass

        if self._stdout_task:
            self._stdout_task.cancel()
            try:
                await self._stdout_task
            except asyncio.CancelledError:
                pass
            self._stdout_task = None

        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(
                    self._loop.run_in_executor(None, self._process.wait),
                    timeout=MCP_SHUTDOWN_TIMEOUT,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "MCP '%s' 进程未在 %ss 内退出，强制终止",
                    self.name, MCP_SHUTDOWN_TIMEOUT,
                )
                try:
                    self._process.kill()
                    await self._loop.run_in_executor(None, self._process.wait)
                except ProcessLookupError:
                    pass
            except ProcessLookupError:
                pass
            self._process = None

        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

    @property
    def is_running(self) -> bool:
        """检查服务器是否已完成初始化且子进程仍在运行。

        注意：子进程启动不等价于已就绪——必须完成 initialize 握手 +
        tools/list 后才能对外暴露工具。
        """
        return (
            self._initialized
            and self._process is not None
            and self._process.poll() is None
            and not self._closed
        )


# ── HTTP MCP 客户端 ──────────────────────────────────────


class MCPHttpClient:
    """通过 Streamable HTTP 与 MCP 服务器通信。

    使用 HTTP POST 发送 JSON-RPC 请求，适用于 GitHub Copilot MCP 等
    远程 MCP 服务。遵循 MCP Streamable HTTP 传输规范。
    """

    def __init__(
        self,
        name: str,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.url = url.rstrip("/")
        self._headers = headers or {}
        self._request_id = 0
        self._initialized = False
        self._client: httpx.AsyncClient | None = None

    # ── 连接与握手 ─────────────────────────────────────

    async def start(self) -> dict[str, Any]:
        """发送 MCP initialize 握手请求。"""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(MCP_HTTP_TIMEOUT),
            headers={
                "Content-Type": CONTENT_TYPE_JSON,
                "Accept": ACCEPT_HEADER_SSE,
                **self._headers,
            },
        )

        try:
            result = await asyncio.wait_for(
                self._request("initialize", {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    MCP_FIELD_CLIENT_INFO: {
                        "name": app_config.name,
                        "version": app_config.version,
                    },
                }),
                timeout=MCP_INIT_TIMEOUT,
            )

            await self._send_notification(MCP_METHOD_INITIALIZED)

            server_info = result.get(MCP_FIELD_SERVER_INFO, {})
            logger.info(
                "MCP '%s' 已连接 (HTTP): %s v%s",
                self.name,
                server_info.get(MCP_KEY_NAME, "?"),
                server_info.get("version", "?"),
            )
            self._initialized = True
            return result

        except asyncio.TimeoutError:
            await self.stop()
            raise MCPServerError(
                f"MCP 服务器 '{self.name}' HTTP 初始化超时 ({MCP_INIT_TIMEOUT}s)"
            )
        except MCPServerError:
            await self.stop()
            raise
        except Exception as e:
            await self.stop()
            raise MCPServerError(
                f"MCP 服务器 '{self.name}' HTTP 初始化失败: {e}"
            ) from e

    # ── JSON-RPC 通信 ──────────────────────────────────

    @staticmethod
    def _parse_sse_body(body: str) -> list[dict[str, Any]]:
        """从 SSE 文本中提取所有 data 行的 JSON 负载。"""
        events: list[dict[str, Any]] = []
        current_data: list[str] = []
        for line in body.splitlines():
            line = line.strip()
            if not line:
                # 空行表示事件结束
                if current_data:
                    payload = "\n".join(current_data)
                    try:
                        parsed = json.loads(payload)
                        if isinstance(parsed, dict):
                            events.append(cast(dict[str, Any], parsed))
                    except json.JSONDecodeError:
                        logger.debug("SSE data 行非 JSON: %s", payload[:MCP_SSE_TRUNCATE])
                    current_data = []
                continue
            if line.startswith(SSE_DATA_PREFIX):
                current_data.append(line[len(SSE_DATA_PREFIX):].strip())
            # 忽略其他字段（event:, id:, retry: 等）
        # 处理末尾无空行的情况
        if current_data:
            payload = "\n".join(current_data)
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, dict):
                    events.append(cast(dict[str, Any], parsed))
            except json.JSONDecodeError:
                logger.debug("SSE data 行非 JSON: %s", payload[:MCP_SSE_TRUNCATE])
        return events

    async def _request(
        self, method: str, params: dict[str, Any] | None = None,
        _timeout: float | None = None,
    ) -> dict[str, Any]:
        """发送 JSON-RPC HTTP POST 请求并等待响应。

        支持两种 MCP Streamable HTTP 响应格式：
        - application/json → 直接作为 JSON-RPC 响应解析
        - text/event-stream → 从 SSE data 行中提取 JSON-RPC 负载

        _timeout 仅用于覆盖单次请求的 HTTP 超时（如工具调用），
        不传则使用客户端默认的 MCP_HTTP_TIMEOUT。
        """
        if not self._client:
            raise MCPServerError(f"MCP 服务器 '{self.name}' 未连接")

        self._request_id += 1
        req_id = self._request_id

        msg: dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "id": req_id,
            "method": method,
        }
        if params:
            msg["params"] = params

        req_timeout = _timeout if _timeout is not None else MCP_HTTP_TIMEOUT
        try:
            response = await self._client.post(
                self.url, json=msg, timeout=req_timeout,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise MCPServerError(
                f"MCP HTTP 请求 '{method}' 超时 ({req_timeout}s)"
            )
        except httpx.HTTPStatusError as e:
            raise MCPServerError(
                f"MCP HTTP 请求 '{method}' 失败: HTTP {e.response.status_code}"
            )
        except httpx.RequestError as e:
            raise MCPServerError(
                f"MCP HTTP 请求 '{method}' 网络错误: {e}"
            )

        content_type = response.headers.get("content-type", "")

        if CONTENT_TYPE_EVENT_STREAM in content_type:
            return self._parse_sse_response(response.text, method, req_id)

        # 默认当作纯 JSON 处理
        try:
            data = response.json()
        except Exception:
            raise MCPServerError(
                f"MCP HTTP 响应无法解析为 JSON: {response.text[:MCP_SSE_TRUNCATE]}"
            )

        return self._extract_result(data, method)

    def _parse_sse_response(
        self, body: str, method: str, req_id: int,
    ) -> dict[str, Any]:
        """解析 SSE 响应体，提取与请求 ID 匹配的 JSON-RPC 结果。"""
        events = self._parse_sse_body(body)
        if not events:
            raise MCPServerError(
                f"MCP HTTP 请求 '{method}' SSE 响应中无有效 JSON 数据"
            )

        # 优先匹配 id，其次取第一个有 result 或 error 的事件
        for evt in events:
            if evt.get("id") == req_id:
                return self._extract_result(evt, method)

        for evt in events:
            if MCP_FIELD_RESULT in evt or MCP_FIELD_ERROR in evt:
                return self._extract_result(evt, method)

        raise MCPServerError(
            f"MCP HTTP 请求 '{method}' SSE 响应中无匹配的 JSON-RPC 结果"
        )

    @staticmethod
    def _extract_result(data: dict[str, Any], method: str) -> dict[str, Any]:
        """从 JSON-RPC 响应中提取 result，统一错误处理。"""
        if MCP_FIELD_ERROR in data:
            err = data[MCP_FIELD_ERROR]
            if isinstance(err, dict):
                err = cast(dict[str, object], err)
                err_msg = str(err.get("message", "未知错误"))
                err_code = str(err.get("code", "?"))
            else:
                err_msg = str(err)
                err_code = "?"
            raise MCPServerError(
                f"MCP HTTP 请求 '{method}' 返回错误: {err_msg} (code {err_code})"
            )
        return data.get(MCP_FIELD_RESULT, {})

    async def _send_notification(
        self, method: str, params: dict[str, Any] | None = None,
    ) -> None:
        """发送 JSON-RPC 通知（无 id，不等待响应）。"""
        if not self._client:
            return

        msg: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "method": method}
        if params:
            msg["params"] = params

        try:
            await self._client.post(self.url, json=msg)
        except Exception as e:
            logger.debug("MCP '%s' HTTP 通知发送失败: %s", self.name, e)

    # ── 工具操作 ──────────────────────────────────────

    async def list_tools(self) -> list[ToolDefinition]:
        """发现 MCP 服务器提供的工具列表。"""
        try:
            result = await asyncio.wait_for(
                self._request(MCP_METHOD_TOOLS_LIST),
                timeout=MCP_LIST_TOOLS_TIMEOUT,
            )
        except (MCPServerError, asyncio.TimeoutError) as e:
            logger.warning("MCP '%s' 工具发现失败: %s", self.name, e)
            return []

        raw_tools: list[object] = result.get("tools", [])
        definitions: list[ToolDefinition] = []
        for t in raw_tools:
            if not isinstance(t, dict):
                continue
            t = cast(dict[str, object], t)
            definitions.append(ToolDefinition(
                name=str(t.get(MCP_KEY_NAME, "")),
                description=str(t.get("description", "")),
                parameters=cast(dict[str, object], t.get(MCP_FIELD_INPUT_SCHEMA, {})),
            ))
        return definitions

    async def call_tool(
        self, tool_name: str, arguments: dict[str, object],
    ) -> tuple[str, bool]:
        """调用 MCP 工具。

        Returns:
            (结果文本, 是否为错误) — 错误仅通过布尔值传递，
            不再将 "[错误]" 混入原始数据。
        """
        try:
            result = await asyncio.wait_for(
                self._request(MCP_METHOD_TOOLS_CALL, {
                    "name": tool_name,
                    "arguments": arguments,
                }, _timeout=MCP_CALL_TOOL_TIMEOUT),
                timeout=MCP_CALL_TOOL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return f"MCP 工具 '{tool_name}' 调用超时 ({MCP_CALL_TOOL_TIMEOUT}s)", True
        except MCPServerError as e:
            return f"MCP 工具 '{tool_name}' 调用失败: {e}", True
        except Exception as e:
            logger.warning(
                "MCP '%s' 工具 '%s' 异常: %s", self.name, tool_name, e,
            )
            return f"MCP 工具 '{tool_name}' 执行异常: {e}", True

        is_error = bool(result.get(MCP_FIELD_IS_ERROR, False))

        content = result.get(MCP_FIELD_CONTENT, [])
        if isinstance(content, list):
            content_items = cast(list[object], content)
            parts: list[str] = []
            for item in content_items:
                if isinstance(item, dict):
                    item = cast(dict[str, object], item)
                    item_type = str(item.get(MCP_FIELD_TYPE, ""))
                    if item_type == MCP_FIELD_TEXT:
                        parts.append(str(item.get(MCP_FIELD_TEXT, "")))
                    elif item_type == MCP_FIELD_RESOURCE:
                        resource = item.get(MCP_FIELD_RESOURCE, {})
                        if isinstance(resource, dict):
                            resource = cast(dict[str, object], resource)
                            resource_text = resource.get(MCP_FIELD_TEXT, "")
                            if resource_text:
                                parts.append(str(resource_text))
            result_text = "\n".join(parts) if parts else json.dumps(result, ensure_ascii=False)
            return result_text, is_error

        return json.dumps(result, ensure_ascii=False), is_error

    # ── 生命周期 ──────────────────────────────────────

    async def stop(self) -> None:
        """关闭 HTTP 客户端连接。"""
        self._initialized = False
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def is_running(self) -> bool:
        """检查客户端是否已完成初始化握手。"""
        return self._initialized


# ── MCP 管理器 ──────────────────────────────────────────

# MCP_HEALTH_CHECK_INTERVAL 定义于 llm/constants.py


class MCPManager:
    """管理多个 MCP 服务器进程的生命周期和工具注册。

    单例 ``mcp_manager`` 供模块级访问。

    关键行为：
    - ``reload()`` 采用 diff 策略：仅移除/新增变更的服务器，未变更的保持运行。
    - 后台定期健康检查，探测到进程退出后自动清理对应工具。
    """

    def __init__(self) -> None:
        self._servers: dict[str, _MCPServer] = {}
        self._tool_to_server: dict[str, str] = {}  # tool_name → server_name
        self._lock = asyncio.Lock()
        self._health_task: asyncio.Task[None] | None = None
        self._reloading = False
        self._last_mtime: float = 0.0
        self._last_errors: dict[str, str] = {}  # server_name → error message
        self._last_retry_attempt: dict[str, float] = {}  # server_name → monotonic timestamp

    # ── 公开 API ──────────────────────────────────────

    @property
    def is_reloading(self) -> bool:
        """是否有重载任务正在执行中。"""
        return self._reloading

    async def reload(self, config_text: str) -> None:
        """Diff-based 重载：仅重启变更的服务器，未变更者保持运行。

        这是启动和配置修改时的统一入口。

        内置重入保护：若已有重载在执行，自动跳过重复请求。
        """
        if self._reloading:
            logger.info("MCP 重载已在执行中，跳过重复请求")
            return

        self._reloading = True
        self._last_errors.clear()
        logger.info("MCP 开始 diff 重载")
        try:
            from core.config import parse_mcp_config, get_mcp_config_mtime

            new_configs = parse_mcp_config(config_text)
            new_names: set[str] = set()
            new_cfg_map: dict[str, dict[str, object]] = {}
            for c in new_configs:
                name = str(c["name"])
                if not c.get("disabled"):
                    new_names.add(name)
                    new_cfg_map[name] = c

            added = 0
            removed = 0
            revived = 0

            async with self._lock:
                old_names = set(self._servers.keys())

                # 1. 移除不再需要的服务器
                for name in old_names - new_names:
                    logger.info("MCP '%s' 已从配置中移除，断开连接", name)
                    await self._remove_server(name)
                    removed += 1

                # 2. 对仍存在的服务器：检查进程是否存活，死进程重新连接
                for name in old_names & new_names:
                    server = self._servers.get(name)
                    if server and not server.is_running:
                        logger.info("MCP '%s' 进程已退出，重新连接", name)
                        self._cleanup_server_tools(name)
                        await self._stop_server(name)
                        await self._add_server(new_cfg_map[name])
                        revived += 1
                    # 存活且配置未变 → 不操作

                # 3. 添加新服务器
                for name in new_names - old_names:
                    await self._add_server(new_cfg_map[name])
                    added += 1

                # 4. 确保健康检查在运行
                self._ensure_health_monitor()

            logger.info(
                "MCP diff 重载完成: +%d 新增 / %d 移除 / %d 复活",
                added, removed, revived,
            )

            # 重载成功后同步文件 mtime，避免文件监听误触发
            try:
                self._last_mtime = get_mcp_config_mtime()
            except Exception:
                pass

        except Exception:
            logger.exception("MCP diff 重载异常")
        finally:
            self._reloading = False

    async def disconnect_all(self) -> None:
        """断开所有服务器并停止健康检查（供 shutdown 使用）。"""
        self._last_errors.clear()
        self._last_retry_attempt.clear()
        async with self._lock:
            self._stop_health_monitor()
            from llm.tools import tool_executor
            for tool_name in list(self._tool_to_server.keys()):
                tool_executor.unregister(tool_name)
            self._tool_to_server.clear()
            await self._disconnect_all()

    def get_server_tools(self) -> dict[str, list[str]]:
        """返回 MCP 服务器 → 工具名列表的映射（供前端展示用）。"""
        result: dict[str, list[str]] = {}
        for tool_name, server_name in self._tool_to_server.items():
            result.setdefault(server_name, []).append(tool_name)
        return result

    def get_status(self) -> dict[str, str]:
        """返回 MCP 服务器状态映射（供 API 展示）。

        Returns:
            {server_name: "运行中" | "已停止" | "异常"}
        """
        result: dict[str, str] = {}
        for name, server in self._servers.items():
            if server.is_running:
                result[name] = MCP_RUNNING
            else:
                result[name] = MCP_STOPPED
        # 也包括已注册工具但进程未在 _servers 中的（异常状态）
        for server_name in set(self._tool_to_server.values()):
            if server_name not in result:
                result[server_name] = MCP_ERROR
        # 最近一次重载中启动失败的服务器（供前端识别完成状态）
        for name in self._last_errors:
            if name not in result:
                result[name] = MCP_ERROR
        return result

    # ── 内部：单服务器操作 ──────────────────────────────

    async def _add_server(self, cfg: dict[str, object]) -> None:
        """连接单个 MCP 服务器并注册其全部工具。"""
        name = str(cfg[MCP_KEY_NAME])
        # 兼容 "type" 与 "transport" 两种写法（mcp.json 常用 "type"）
        transport = str(cfg.get(MCP_KEY_TRANSPORT) or cfg.get("type", MCP_TRANSPORT_STDIO))

        if transport == MCP_TRANSPORT_HTTP:
            await self._add_http_server(cfg)
            return

        command = str(cfg.get(MCP_KEY_COMMAND, ""))
        if not command:
            logger.warning("MCP '%s' 缺少 command 字段，跳过", name)
            return

        args_raw = cfg.get(MCP_KEY_ARGS, [])
        args: list[str] = [str(a) for a in cast(list[object], args_raw)] if isinstance(args_raw, list) else []

        env_raw = cfg.get(MCP_KEY_ENV)
        env: dict[str, str] | None = None
        if isinstance(env_raw, dict):
            env = {str(k): str(v) for k, v in cast(dict[str, object], env_raw).items()}

        server: _MCPServer = MCPServerProcess(name=name, command=command, args=args, env=env)

        try:
            await server.start()
        except MCPServerError as e:
            logger.warning("MCP '%s' 启动失败: %s", name, e)
            self._last_errors[name] = str(e)
            await server.stop()
            return

        await self._register_server_tools(server, name)
        self._servers[name] = server

    async def _add_http_server(self, cfg: dict[str, object]) -> None:
        """连接 HTTP MCP 服务器并注册其全部工具。"""
        name = str(cfg[MCP_KEY_NAME])
        url = str(cfg.get(MCP_KEY_URL, ""))
        if not url:
            logger.warning("MCP '%s' 缺少 url 字段，跳过", name)
            return

        headers_raw = cfg.get(MCP_KEY_HEADERS)
        headers: dict[str, str] | None = None
        if isinstance(headers_raw, dict):
            headers = {str(k): str(v) for k, v in cast(dict[str, object], headers_raw).items()}

        server: _MCPServer = MCPHttpClient(name=name, url=url, headers=headers)

        try:
            await server.start()
        except MCPServerError as e:
            logger.warning("MCP '%s' HTTP 启动失败: %s", name, e)
            self._last_errors[name] = str(e)
            await server.stop()
            return

        await self._register_server_tools(server, name)
        self._servers[name] = server

    async def _register_server_tools(
        self, server: _MCPServer, name: str,
    ) -> None:
        """注册指定服务器的全部工具到 ToolExecutor。"""
        from llm.tools import tool_executor

        tools = await server.list_tools()
        registered_count = 0
        for tool_def in tools:
            if tool_def.name in self._tool_to_server:
                logger.warning(
                    "工具名 '%s' 已被 MCP '%s' 注册，跳过 '%s'",
                    tool_def.name, self._tool_to_server[tool_def.name], name,
                )
                continue

            _server = server
            _tool_name = tool_def.name

            async def _call_mcp(
                _s: _MCPServer = _server,
                _tn: str = _tool_name,
                **kwargs: object,
            ) -> tuple[str, bool]:
                return await _s.call_tool(_tn, dict(kwargs))

            tool_executor.register(
                tool_def.name, _call_mcp, tool_def,
                source=name,
                icon="fa-solid fa-puzzle-piece",
                label=tool_def.name,
                order=100.0,
            )
            self._tool_to_server[tool_def.name] = name
            registered_count += 1

        logger.info(
            "MCP '%s' 就绪，注册 %d/%d 个工具",
            name, registered_count, len(tools),
        )

    async def _remove_server(self, name: str) -> None:
        """移除单个 MCP 服务器：注销工具 + 终止进程。"""
        self._cleanup_server_tools(name)
        self._last_errors.pop(name, None)
        await self._stop_server(name)

    def _cleanup_server_tools(self, name: str) -> None:
        """注销指定 MCP 服务器的所有工具（不终止进程）。"""
        from llm.tools import tool_executor
        removed = 0
        for tool_name, server_name in list(self._tool_to_server.items()):
            if server_name == name:
                tool_executor.unregister(tool_name)
                del self._tool_to_server[tool_name]
                removed += 1
        if removed:
            logger.info("MCP '%s' 清理 %d 个工具", name, removed)

    async def _stop_server(self, name: str) -> None:
        """终止指定 MCP 服务器进程。"""
        server = self._servers.pop(name, None)
        if server:
            try:
                await server.stop()
            except Exception as e:
                logger.warning("MCP '%s' 关闭异常: %s", name, e)

    # ── 内部：全量操作 ──────────────────────────────────

    async def _disconnect_all(self) -> None:
        """断开所有 MCP 服务器连接（不做工具清理，由调用方负责）。"""
        for name in list(self._servers.keys()):
            await self._stop_server(name)

    # ── 内部：健康检查 ──────────────────────────────────

    def _ensure_health_monitor(self) -> None:
        """确保健康检查后台任务在运行。"""
        if self._health_task and not self._health_task.done():
            return
        self._health_task = asyncio.create_task(self._health_check_loop())

    def _stop_health_monitor(self) -> None:
        """停止健康检查后台任务。"""
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
        self._health_task = None

    async def _health_check_loop(self) -> None:
        """后台定期检查：文件监听 + 进程存活检测 + 自动重连。

        - 每 MCP_FILE_WATCH_INTERVAL 检查 mcp.json 的 mtime，变更时自动热重载
        - 每 MCP_HEALTH_CHECK_INTERVAL 检查进程存活，死进程/零工具服务器自动重连
        - 对持续故障的服务器实行 MCP_RETRY_INTERVAL 冷却，避免频繁重试
        """
        file_cycles = max(1, int(MCP_HEALTH_CHECK_INTERVAL / MCP_FILE_WATCH_INTERVAL))
        cycle = 0

        while True:
            await asyncio.sleep(MCP_FILE_WATCH_INTERVAL)
            cycle += 1

            # ── 文件监听：mtime 变更 → 自动热重载 ──
            try:
                from core.config import get_mcp_config_mtime, get_mcp_config_text
                current_mtime = get_mcp_config_mtime()
                if (current_mtime > 0 and self._last_mtime > 0
                        and abs(current_mtime - self._last_mtime) > 0.001):
                    logger.info(
                        "MCP 配置文件已变更 (mtime %.3f → %.3f)，触发自动热重载",
                        self._last_mtime, current_mtime,
                    )
                    config_text = get_mcp_config_text()
                    await self.reload(config_text)
                elif self._last_mtime == 0.0 and current_mtime > 0:
                    # 首次启动后记录 mtime，不触发重载
                    self._last_mtime = current_mtime
            except Exception as e:
                logger.warning("MCP 文件监听异常: %s", e)

            # ── 进程存活检查 + 自动重连（每个完整周期执行一次）──
            if cycle < file_cycles:
                continue
            cycle = 0

            # 需要在锁外重试的服务器配置
            to_retry: list[dict[str, object]] = []

            async with self._lock:
                now = time.monotonic()

                # 1. 检测并清理死进程 / 零工具服务器
                dead_or_empty: list[str] = []
                for name, server in self._servers.items():
                    tool_count = len([t for t, s in self._tool_to_server.items() if s == name])
                    if not server.is_running:
                        logger.warning("MCP '%s' 进程意外退出，清理 %d 个工具", name, tool_count)
                        dead_or_empty.append(name)
                    elif tool_count == 0:
                        # initialize 成功但 tools/list 可能因网络问题失败
                        logger.warning(
                            "MCP '%s' 工具数为 0（初始化后工具发现可能失败），标记待重连",
                            name,
                        )
                        dead_or_empty.append(name)

                for name in dead_or_empty:
                    self._cleanup_server_tools(name)
                    await self._stop_server(name)

                # 2. 解析当前配置，找出应运行但未运行的服务器
                try:
                    from core.config import get_mcp_config_text, parse_mcp_config
                    config_text = get_mcp_config_text()
                    configs = parse_mcp_config(config_text)
                except Exception as e:
                    logger.warning("MCP 健康检查读取配置失败: %s", e)
                    configs = []

                for cfg in configs:
                    name = str(cfg[MCP_KEY_NAME])
                    if cfg.get(MCP_KEY_DISABLED):
                        continue
                    if name in self._servers:
                        continue  # 已在运行

                    # 检查重试冷却
                    last_retry = self._last_retry_attempt.get(name, 0.0)
                    if now - last_retry < MCP_RETRY_INTERVAL:
                        continue

                    logger.info(
                        "MCP '%s' 未运行（距上次重试 %.0fs），尝试自动重连",
                        name, now - last_retry,
                    )
                    self._last_retry_attempt[name] = now
                    to_retry.append(cfg)

            # ── 锁外：逐个尝试重连（_add_server 内部含网络 I/O，不可持锁）──
            for cfg in to_retry:
                name = str(cfg["name"])
                try:
                    # 重连前二次检查：可能被并发的 reload() 抢先添加
                    async with self._lock:
                        if name in self._servers:
                            continue
                    await self._add_server(cfg)
                except Exception:
                    logger.exception("MCP '%s' 健康检查自动重连异常", name)


# ── 单例 ───────────────────────────────────────────────────

mcp_manager = MCPManager()
