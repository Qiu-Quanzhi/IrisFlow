"""系统信息与运行状态接口。"""

import logging
import platform
import sys
import time

import fastapi
from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.config import app_config

_log = logging.getLogger(__name__)
router = APIRouter(tags=["System"])

_START_TIME = time.time()


# ── 响应模型 ──────────────────────────────────────────────

class AppInfo(BaseModel):
    """应用基本信息。"""

    name: str = Field(description="应用名称")
    version: str = Field(description="应用版本")
    description: str = Field(description="应用简介")
    docs: str = Field(description="Swagger 文档地址")


class VersionInfo(BaseModel):
    """详细版本信息。"""

    app: str = Field(description="应用名")
    app_version: str = Field(description="应用版本")
    description: str = Field(description="应用简介")
    python: str = Field(description="Python 版本")
    platform: str = Field(description="操作系统")
    arch: str = Field(description="系统架构")
    fastapi: str = Field(description="FastAPI 版本")


class RuntimeStatus(BaseModel):
    """运行状态。"""

    uptime_seconds: float = Field(description="运行时长（秒）")
    python_version: str = Field(description="Python 版本")
    platform: str = Field(description="操作系统")


# ── 路由 ──────────────────────────────────────────────────

@router.get("/api", response_model=AppInfo)
def app_info() -> AppInfo:
    """获取应用基本信息。"""
    return AppInfo(
        name=app_config.name,
        version=app_config.version,
        description=app_config.description,
        docs=app_config.docs_url,
    )


@router.get("/version", response_model=VersionInfo)
def version_info() -> VersionInfo:
    """获取详细版本信息。"""
    try:
        fastapi_ver = fastapi.__version__
    except Exception:
        fastapi_ver = "unknown"

    return VersionInfo(
        app=app_config.name,
        app_version=app_config.version,
        description=app_config.description,
        python=sys.version.split()[0],
        platform=platform.system(),
        arch=platform.machine(),
        fastapi=fastapi_ver,
    )


@router.get("/status", response_model=RuntimeStatus)
def runtime_status() -> RuntimeStatus:
    """获取运行状态。"""
    return RuntimeStatus(
        uptime_seconds=round(time.time() - _START_TIME, 2),
        python_version=sys.version.split()[0],
        platform=platform.system(),
    )


@router.get("/api/ping")
def ping() -> dict[str, bool]:
    """轻量连通性检查 — 无任何外部依赖，仅确认服务可达。"""
    _log.debug("GET /api/ping → 200 OK")
    return {"ok": True}
