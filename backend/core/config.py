"""应用级配置常量 + 全量配置持久化。

所有可配置项通过前端设置面板保存，持久化到 data/llm_config.json。
不再依赖 .env。
"""

import json
import logging
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

# 配置键常量（定义于此而非 llm.constants 以避免循环导入：
#   config → llm.constants → llm.agent → llm.client → config）
_BASE_URL = "base_url"
_AUTH_TOKEN = "auth_token"
_MODEL = "model"
_MAX_CONCURRENT = "max_concurrent"
_MCP_SERVERS = "mcpServers"
_KEY_NAME = "name"

_log = logging.getLogger(__name__)

# ── 日志常量 ──────────────────────────────────────────────
LOG_LEVEL: str = "INFO"
LOG_FORMAT: str = "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s"

# ── 持久化路径 ─────────────────────────────────────────────
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "llm_config.json"
_SECRETS_PATH = Path(__file__).resolve().parent.parent / "data" / "secrets.json"

_SUBSTITUTION_PATTERN = re.compile(r"\$\{(\w+)\}")


def _load_config_file() -> dict[str, object]:
    """从持久化文件加载全部配置。"""
    try:
        if _CONFIG_PATH.exists():
            result: dict[str, object] = json.loads(_CONFIG_PATH.read_text("utf-8"))
            return result
    except Exception as e:
        _log.debug("加载持久化配置失败（首次运行正常）: %s", e)
    return {}


def _save_config_file(data: dict[str, object]) -> None:
    """将全部配置写入持久化文件（与已有配置合并）。"""
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = _load_config_file()
        existing.update(data)
        _CONFIG_PATH.write_text(json.dumps(existing, indent=2, ensure_ascii=False), "utf-8")
    except Exception as e:
        _log.warning("保存配置失败: %s", e)


_persisted = _load_config_file()


# ── 密钥存储 ──────────────────────────────────────────────

def _load_secrets_file() -> dict[str, str]:
    """从 secrets.json 加载密钥字典。"""
    try:
        if _SECRETS_PATH.exists():
            raw: object = json.loads(_SECRETS_PATH.read_text("utf-8"))
            if isinstance(raw, dict):
                d = cast(dict[object, object], raw)
                return {str(k): str(v) for k, v in d.items()}
    except Exception as e:
        _log.debug("加载密钥文件失败（首次运行正常）: %s", e)
    return {}


def _save_secrets_file(data: dict[str, str]) -> None:
    """将密钥字典写入 secrets.json。"""
    try:
        _SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SECRETS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    except Exception as e:
        _log.warning("保存密钥文件失败: %s", e)


_secrets: dict[str, str] = _load_secrets_file()


def _resolve_secrets(text: str) -> str:
    """将字符串中所有 ${VAR_NAME} 替换为对应的密钥值。

    未定义的变量保持原样不替换，并记录警告。
    """
    def _replacer(m: re.Match[str]) -> str:
        var_name = m.group(1)
        if var_name not in _secrets:
            _log.warning("密钥变量 ${%s} 未定义，保留原文", var_name)
            return m.group(0)
        return _secrets[var_name]
    return _SUBSTITUTION_PATTERN.sub(_replacer, text)


def get_secret(key: str) -> str | None:
    """按 key 查询单个密钥值（供 MCP 服务器等外部进程使用）。

    Returns:
        密钥值，若 key 不存在则返回 None。
    """
    return _secrets.get(key)


def get_secrets_keys() -> list[str]:
    """返回所有密钥的 key 列表（前端查询用，不泄露值）。"""
    return list(_secrets.keys())


def apply_secrets(updates: dict[str, str | None]) -> None:
    """合并更新密钥存储并持久化。

    - None 或空字符串 = 删除该 key
    - 非空字符串 = 设置/更新
    - 未在 updates 中出现的 key = 保持现有值不变
    """
    merged = dict(_secrets)
    for key, value in updates.items():
        if value is None or value == "":
            merged.pop(key, None)
        else:
            merged[key] = value
    _secrets.clear()
    _secrets.update(merged)
    _save_secrets_file(merged)


def _get_persisted_str(key: str) -> str | None:
    """从持久化配置中读取字符串值。"""
    val = _persisted.get(key)
    return str(val) if isinstance(val, str) and val else None


def _get_persisted_int(key: str) -> int | None:
    """从持久化配置中读取整数值。"""
    val = _persisted.get(key)
    return int(val) if isinstance(val, (int, float)) else None


# ── LLM 配置 ──────────────────────────────────────────────

_override_base_url: str | None = _get_persisted_str(_BASE_URL)
_override_auth_token: str | None = _get_persisted_str(_AUTH_TOKEN)
_override_model: str | None = _get_persisted_str(_MODEL)
_override_max_concurrent: int | None = _get_persisted_int(_MAX_CONCURRENT)


def get_base_url() -> str:
    """获取有效的 LLM 网关地址（含密钥替换）。"""
    return _resolve_secrets((_override_base_url or "").rstrip("/"))


def get_auth_token() -> str:
    """获取有效的认证令牌（含密钥替换）。"""
    return _resolve_secrets(_override_auth_token or "")


def get_raw_auth_token() -> str:
    """获取原始认证令牌（不含密钥替换，供前端展示）。"""
    return _override_auth_token or ""


def get_default_model() -> str:
    """获取有效的默认模型。"""
    return _override_model or ""


def get_max_concurrent() -> int:
    """获取最大并发生成数。"""
    return _override_max_concurrent if _override_max_concurrent is not None else 1


def apply_llm_overrides(
    base_url: str | None = None,
    auth_token: str | None = None,
    model: str | None = None,
    max_concurrent: int | None = None,
) -> None:
    """应用前端传入的 LLM 配置覆盖并持久化。"""
    global _override_base_url, _override_auth_token, _override_model, _override_max_concurrent
    if base_url is not None and base_url.strip():
        _override_base_url = base_url.strip().rstrip("/")
    if auth_token is not None:
        _override_auth_token = auth_token
    if model is not None:
        _override_model = model
    if max_concurrent is not None:
        _override_max_concurrent = max_concurrent

    _save_config_file({
        _BASE_URL: _override_base_url,
        _AUTH_TOKEN: _override_auth_token,
        _MODEL: _override_model,
        _MAX_CONCURRENT: _override_max_concurrent,
    })


# ── 默认会话设定 ────────────────────────────────────────────

_SESSION_SETTINGS_PATH = Path(__file__).resolve().parent.parent / "data" / "session_settings.json"

# 模块级缓存 — 启动时从 JSON 加载，运行时通过 apply 修改
_session_settings: dict[str, object] | None = None


def _load_session_settings() -> dict[str, object]:
    try:
        if _SESSION_SETTINGS_PATH.exists():
            return json.loads(_SESSION_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        _log.debug("加载会话默认设定失败（首次运行正常）: %s", e)
    return {}


def _save_session_settings(data: dict[str, object]) -> None:
    try:
        _SESSION_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SESSION_SETTINGS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        _log.warning("保存会话默认设定失败: %s", e)


def get_default_session_settings() -> dict[str, object]:
    """返回默认会话设定。若 JSON 不存在，以 SessionSettings 模型默认值为准。"""
    global _session_settings
    if _session_settings is None:
        from llm.models import SessionSettings
        fallback = SessionSettings().model_dump()
        _session_settings = _load_session_settings() or fallback
    return dict(_session_settings)


def apply_default_session_settings(updates: dict[str, object]) -> None:
    """合并更新并持久化默认会话设定。null 值表示清除该字段（回退到模型默认）。"""
    global _session_settings
    current = get_default_session_settings()
    for key, val in updates.items():
        current[key] = val
    _session_settings = current
    _save_session_settings(current)


# ── MCP JSON 配置 ──────────────────────────────────────────

_MCP_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "mcp.json"


def get_mcp_config_text() -> str:
    """获取原始 MCP JSON 配置文本。"""
    try:
        if _MCP_CONFIG_PATH.exists():
            return _MCP_CONFIG_PATH.read_text("utf-8")
    except Exception as e:
        _log.debug("读取 MCP 配置失败（首次运行正常）: %s", e)
    return ""


def get_mcp_config_mtime() -> float:
    """获取 mcp.json 的最后修改时间戳（用于文件监听热重载）。

    Returns:
        st_mtime 浮点值。文件不存在或读取失败返回 0.0。
    """
    try:
        if _MCP_CONFIG_PATH.exists():
            return _MCP_CONFIG_PATH.stat().st_mtime
    except Exception as e:
        _log.debug("读取 MCP 配置 mtime 失败: %s", e)
    return 0.0


def apply_mcp_config_text(text: str) -> None:
    """保存 MCP JSON 配置到文件。"""
    try:
        _MCP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MCP_CONFIG_PATH.write_text(text, "utf-8")
    except Exception as e:
        _log.warning("无法保存 MCP 配置: %s", e)


def parse_mcp_config(text: str) -> list[dict[str, object]]:
    """解析标准 MCP JSON 配置为服务器配置列表。

    格式：``{_MCP_SERVERS: {"名称": {"command": "...", "args": [...], "env": {...}}}}``
    服务器名称为 ``mcpServers`` 对象的 key。

    每个服务器支持的字段：
    - command: 可执行命令（必填）
    - args: 命令参数列表
    - env: 环境变量（支持 ${VAR} 密钥替换）
    - transport: "stdio"（默认）或 "http"
    - url: HTTP 模式下的服务器地址
    - disabled: 是否禁用

    Returns:
        解析后的服务器配置字典列表。解析失败返回空列表。
    """
    text = text.strip()
    if not text:
        return []

    try:
        data: object = json.loads(text)
    except Exception as e:
        _log.warning("MCP JSON 解析失败: %s", e)
        return []

    if not isinstance(data, dict):
        return []

    d = cast(dict[str, object], data)
    mcp_servers = d.get(_MCP_SERVERS)
    if not isinstance(mcp_servers, dict):
        return []

    servers_dict = cast(dict[str, object], mcp_servers)
    result: list[dict[str, object]] = []
    for name, cfg in servers_dict.items():
        if not isinstance(cfg, dict):
            continue
        cfg_dict = cast(dict[str, object], cfg)
        server: dict[str, object] = {_KEY_NAME: str(name)}
        for k, v in cfg_dict.items():
            server[str(k)] = _resolve_secrets_in_dict(v)
        result.append(server)

    return result


def _resolve_secrets_in_dict(obj: object) -> object:
    """递归解析字典/列表/字符串中的 ${VAR} 占位符。"""
    if isinstance(obj, str):
        return _resolve_secrets(obj)
    elif isinstance(obj, dict):
        d = cast(dict[object, object], obj)
        return {str(k): _resolve_secrets_in_dict(v) for k, v in d.items()}
    elif isinstance(obj, list):
        lst = cast(list[object], obj)
        return [_resolve_secrets_in_dict(v) for v in lst]
    return obj


# ── 应用配置 ──────────────────────────────────────────────


def _read_project_meta() -> tuple[str, str]:
    """从 pyproject.toml 读取版本号与描述。"""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        with open(pyproject, "rb") as f:
            raw = tomllib.load(f)
        d = cast(dict[str, object], raw)
        project = cast(dict[str, object] | None, d.get("project"))
        if project is None:
            return "0.0.0", "IrisFlow"
        version: str = str(project.get("version", "0.0.0"))
        description: str = str(project.get("description", "IrisFlow"))
        if " — " in description:
            description = description.split(" — ", 1)[1]
        return version, description
    except Exception as e:
        _log.warning("读取 pyproject.toml 失败: %s", e)
        return "0.0.0", "IrisFlow"


@dataclass(frozen=True)
class AppConfig:
    """IrisFlow 应用配置。

    版本与描述从 pyproject.toml 读取，作为元数据的唯一来源。
    """

    name: str = "IrisFlow"
    docs_url: str = "/docs"

    _version, _description = _read_project_meta()
    version: str = _version
    description: str = _description


app_config = AppConfig()


def get_user_agent() -> str:
    """返回 HTTP User-Agent 字符串，版本号从 pyproject.toml 动态读取。"""
    return f"IrisFlow/{app_config.version}"
