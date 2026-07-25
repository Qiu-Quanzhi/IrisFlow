"""IrisFlow 入口。

挂载核心路由与 LLM 路由。
支持有序关闭：状态切换 + 资源清理。
"""

import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

# MCP 子进程通过 subprocess.Popen + 线程 I/O 桥接实现，
# 兼容所有 event loop 类型（包括 Windows SelectorEventLoop）。

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles

from core import router as core_router
from core.config import app_config
from llm.constants import CORS_ORIGIN, MCP_RELOAD_TIMEOUT
from llm import router as llm_router

# ── 日志配置 ──────────────────────────────────────────


def setup_logging() -> None:
    """配置根 logger：INFO 级别，控制台 + 文件双输出。"""
    from core.config import LOG_FORMAT, LOG_LEVEL

    # Windows 控制台默认使用系统代码页（GBK），强制 UTF-8 避免中文乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    fmt = logging.Formatter(LOG_FORMAT)

    # 文件（持久化）
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    fh = logging.FileHandler(log_dir / "backend.log", encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # 控制台（uvicorn 开发时可见）
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)


setup_logging()
_log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。

    启动时连接 MCP 服务器；
    Shutdown 时切换状态并执行资源清理。
    """
    # ── 启动：连接 MCP 服务器（diff-based reload，失败不阻塞 startup）──
    from core.config import get_mcp_config_text
    from llm.mcp import mcp_manager

    text = get_mcp_config_text()
    if text.strip():
        try:
            await asyncio.wait_for(mcp_manager.reload(text), timeout=MCP_RELOAD_TIMEOUT)
        except asyncio.TimeoutError:
            _log.warning(
                "MCP 初始化超时（30s），已连接的服务器继续运行，未完成的将在健康检查后重试"
            )
        except Exception:
            _log.exception("MCP 初始化异常，后台健康检查将继续监控")

    # ── 启动：清理过时的 PENDING 会话（上次运行中断残留）──
    try:
        from llm.sessions import session_store
        from llm.models import SessionStatus
        all_sessions = await session_store.list_all()
        for s in all_sessions:
            if s.status == SessionStatus.PENDING or s.status == SessionStatus.GENERATING:
                await session_store.update_status(s.session_id, SessionStatus.COMPLETED.value)
    except Exception:
        _log.warning("启动时清理残留会话状态失败，数据库可能尚不存在")

    yield
    # ── 有序关闭：终止生成、清空队列、通知订阅者 ──
    from llm.router import shutdown_generations
    await shutdown_generations()

    # ── 有序关闭：断开所有 MCP 服务器 ──
    await mcp_manager.disconnect_all()


app = FastAPI(
    title=app_config.name,
    description=app_config.description,
    version=app_config.version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[CORS_ORIGIN],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── HTTP 请求日志中间件 ──────────────────────────────

_http_log = logging.getLogger("http")


@app.middleware("http")
async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """记录每个 HTTP 请求的方法、路径、状态码与耗时。"""
    path = request.url.path
    if path in ("/", "/api/ping", "/api/health"):
        return await call_next(request)

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        _log.exception("请求失败: %s %s", request.method, path)
        raise
    elapsed = (time.perf_counter() - start) * 1000
    _http_log.info("%s %s → %d (%.0fms)", request.method, path, response.status_code, elapsed)
    return response

app.include_router(core_router)
app.include_router(llm_router)

# ── 生产模式：serve 前端静态文件（SPA fallback）──

_DIST_DIR = (Path(__file__).resolve().parent.parent / "frontend" / "dist").resolve()
if _DIST_DIR.is_dir() and (_DIST_DIR / "index.html").is_file():
    _log.info("检测到前端构建产物：%s，启用生产模式", _DIST_DIR)

    # 挂载 /assets/ 静态资源（Vite 构建产物中的 hashed 文件）
    _assets_dir = _DIST_DIR / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    # SPA fallback：所有不匹配 API 路由的 GET 请求 → index.html
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """转发所有非 API GET 请求到前端 SPA 入口。
        Vue Router 在客户端接管路由解析。"""
        file = _DIST_DIR / full_path.lstrip("/")
        if file.is_file():
            return FileResponse(file)
        return FileResponse(_DIST_DIR / "index.html")
else:
    _log.info("未检测到前端构建产物，仅运行 API 服务")
