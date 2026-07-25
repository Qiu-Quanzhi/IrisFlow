"""LLM 会话管理。

在内存中维护对话上下文，通过 SQLite 持久化，重启后恢复。
基于 Chat 类构建。会话仅由用户手动删除，不做自动过期或驱逐。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from llm.chat import Chat

_log = logging.getLogger(__name__)
from llm.constants import (
    DEFAULT_TITLE,
    MODE_CHAT,
    MODE_AGENT,
    MSG_ABORTED,
    MSG_GENERATING,
    MSG_QUEUED,
    ROLE_ASSISTANT,
    ROLE_USER,
    SESSION_ID_LENGTH,
    SQLITE_BUSY_TIMEOUT,
    STATUS_COMPLETED,
    STATUS_GENERATING,
    STATUS_PENDING,
)
from llm.models import (
    ChatMessage,
    ConversationDetail,
    ConversationInfo,
    SessionSettings,
    SessionStatus,
)

# ── 会话存储配置 ──────────────────────────────────────────

_DB_PATH: Path = Path(__file__).resolve().parent.parent / "data" / "sessions.db"


def _get_db() -> sqlite3.Connection:
    """获取数据库连接（每次新建，线程安全）。"""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT}")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            model TEXT NOT NULL DEFAULT '',
            system_prompt TEXT DEFAULT '',
            title TEXT DEFAULT '无标题',
            mode TEXT DEFAULT 'chat',
            status TEXT DEFAULT '{STATUS_COMPLETED}',
            messages TEXT NOT NULL DEFAULT '[]',
            created_at REAL NOT NULL,
            last_access REAL NOT NULL
        )"""
    )
    # Migration: add columns to existing databases
    # 异常表示列已存在（幂等），静默跳过即可。
    try:
        conn.execute(f"ALTER TABLE sessions ADD COLUMN status TEXT DEFAULT '{STATUS_COMPLETED}'")
    except Exception:
        pass  # 列已存在（首次运行或旧库）
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN pinned INTEGER DEFAULT 0")
    except Exception:
        pass  # 列已存在
    try:
        conn.execute("ALTER TABLE sessions ADD COLUMN settings TEXT DEFAULT '{}'")
    except Exception:
        pass  # 列已存在
    conn.commit()
    return conn


class _Session:
    """单个会话。"""

    def __init__(
        self, session_id: str, chat: Chat, system_prompt: str | None,
        title: str = DEFAULT_TITLE,
        mode: str = MODE_CHAT,
        created_at: float | None = None,
        last_access: float | None = None,
        status: str = STATUS_COMPLETED,
        pinned: bool = False,
        settings: "SessionSettings | None" = None,
    ) -> None:
        self.session_id = session_id
        self.chat = chat
        self.system_prompt = system_prompt
        self.title = title
        self.mode = mode
        self.status = status  # "generating" | "completed" | "pending"
        self.pinned = pinned
        self.settings = settings
        self.created_at: float = created_at or time.time()
        self.last_access: float = last_access or time.time()

    def touch(self) -> None:
        self.last_access = time.time()


class SessionStore:
    """线程安全的内存 + SQLite 持久化会话存储。

    重启后自动从 SQLite 恢复所有会话。
    """

    def __init__(self) -> None:
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._lock: asyncio.Lock = asyncio.Lock()
        self._load_all()

    # ── 持久化 ───────────────────────────────────────

    def _save(self, s: _Session) -> None:
        """将会话写入 SQLite。"""
        try:
            conn = _get_db()
            msgs_json = json.dumps(
                [m.model_dump(exclude_none=True) for m in s.chat.messages],
                ensure_ascii=False,
            )
            settings_json = json.dumps(
                s.settings.model_dump(exclude_none=True) if s.settings else {},
                ensure_ascii=False,
            )
            conn.execute(
                """INSERT OR REPLACE INTO sessions
                   (session_id, model, system_prompt, title, mode, status, pinned, messages, settings, created_at, last_access)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (s.session_id, s.chat.model, s.system_prompt or "",
                 s.title, s.mode, s.status, 1 if s.pinned else 0,
                 msgs_json, settings_json, s.created_at, s.last_access),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            _log.warning("Failed to persist session %s: %s", s.session_id, exc)

    def _delete_from_db(self, session_id: str) -> None:
        try:
            conn = _get_db()
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            _log.warning("[sess:%s] 数据库删除失败: %s", session_id, e)

    def _load_all(self) -> None:
        """从 SQLite 恢复所有会话。"""
        try:
            conn = _get_db()
            rows = conn.execute(
                "SELECT session_id, model, system_prompt, title, mode, status, pinned, messages, settings, created_at, last_access FROM sessions ORDER BY last_access DESC"
            ).fetchall()
            conn.close()

            for row in rows:
                sid, model, sys_prompt, title, mode, status, pinned, msgs_json, settings_json, created_at, last_access = row
                # 生成任务不存活过重启：残留的 generating / pending → completed
                if status in (STATUS_GENERATING, STATUS_PENDING):
                    status = STATUS_COMPLETED
                chat = Chat(model=model, system_prompt=sys_prompt or None)
                try:
                    raw_msgs = json.loads(msgs_json)
                    chat.messages = [
                        ChatMessage(**cast("dict[str, Any]", m)) for m in raw_msgs
                        if isinstance(m, dict) and m.get("role")  # pyright: ignore[reportUnknownMemberType]
                    ]
                except (json.JSONDecodeError, TypeError):
                    _log.warning("[sess:%s] 消息 JSON 解析失败，跳过", sid)
                # 服务端重启 → 未完成的 assistant 消息标记为已终止
                for msg in chat.messages:
                    if msg.role == ROLE_ASSISTANT and msg.message_status in (MSG_QUEUED, MSG_GENERATING):
                        msg.message_status = MSG_ABORTED
                loaded_settings: SessionSettings | None = None
                try:
                    raw_settings = cast("dict[str, Any]", json.loads(settings_json)) if settings_json else {}
                    if raw_settings:
                        loaded_settings = SessionSettings(**raw_settings)
                        chat.apply_settings(loaded_settings)
                except (json.JSONDecodeError, TypeError):
                    _log.warning("[sess:%s] settings JSON 解析失败，使用默认", sid)
                self._sessions[sid] = _Session(
                    sid, chat, sys_prompt or None,
                    title=title, mode=mode,
                    created_at=created_at, last_access=last_access,
                    status=status, pinned=bool(pinned),
                    settings=loaded_settings,
                )
        except Exception as e:
            _log.warning("SQLite 会话加载失败（数据库可能不存在或损坏）: %s", e)

        _log.info("从 SQLite 恢复 %d 个会话", len(self._sessions))

    # ── 公共 API ─────────────────────────────────────

    async def create(
        self, model: str, system_prompt: str | None = None, title: str = DEFAULT_TITLE,
        mode: str = MODE_CHAT,
        settings: SessionSettings | None = None,
    ) -> str:
        sid = uuid.uuid4().hex[:SESSION_ID_LENGTH]
        chat = Chat(model=model, system_prompt=system_prompt)
        if settings:
            chat.apply_settings(settings)
        session = _Session(sid, chat, system_prompt, title=title, mode=mode, settings=settings)
        async with self._lock:
            self._sessions[sid] = session
        self._save(session)
        _log.info("[sess:%s] 会话创建: model=%s, mode=%s", sid, model, mode)
        return sid

    async def get_chat(self, session_id: str) -> Chat | None:
        async with self._lock:
            session = self._sessions.get(session_id)
            return session.chat if session else None

    async def register(
        self, session_id: str, chat: Chat, system_prompt: str | None = None,
        title: str = DEFAULT_TITLE, mode: str = MODE_AGENT,
    ) -> None:
        async with self._lock:
            existing = self._sessions.get(session_id)
            created_at = existing.created_at if existing else time.time()
            # Preserve existing status, title, settings so register() doesn't clobber
            # update_status() / update() calls that preceded it.
            prev_status = existing.status if existing else STATUS_COMPLETED
            prev_title = existing.title if existing else title
            prev_pinned = existing.pinned if existing else False
            prev_settings = existing.settings if existing else None
            session = _Session(
                session_id, chat, system_prompt, title=prev_title, mode=mode,
                created_at=created_at,
                status=prev_status, pinned=prev_pinned,
                settings=prev_settings,
            )
            self._sessions[session_id] = session
        self._save(session)
        _log.info("[sess:%s] 会话注册: messages=%d", session_id, len(chat.messages))

    async def get(self, session_id: str) -> ConversationDetail:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"会话不存在: {session_id}")
            return ConversationDetail(
                session_id=session.session_id,
                model=session.chat.model,
                messages=list(session.chat.messages),
                status=SessionStatus(session.status),
                created_at=_iso(session.created_at),
                settings=session.settings,
            )

    async def delete(self, session_id: str) -> bool:
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                self._delete_from_db(session_id)
                _log.info("[sess:%s] 会话删除", session_id)
                return True
            return False

    async def update(self, session_id: str, title: str | None = None, pinned: bool | None = None) -> None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"会话不存在: {session_id}")
            if title is not None:
                session.title = title
            if pinned is not None:
                session.pinned = pinned
            session.touch()
            self._save(session)

    async def update_settings(self, session_id: str, settings: SessionSettings) -> None:
        """更新会话 LLM 参数设定并持久化。"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"会话不存在: {session_id}")
            session.settings = settings
            session.touch()
            self._save(session)

    async def get_title(self, session_id: str) -> str:
        """获取会话标题（不加载完整消息历史）。"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"会话不存在: {session_id}")
            return session.title

    async def update_status(self, session_id: str, status: str) -> str:
        """更新会话状态，返回更新后的 last_access ISO 字符串。"""
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(f"会话不存在: {session_id}")
            session.status = status
            session.touch()
            self._save(session)
            return _iso(session.last_access)

    async def list_all(self) -> list[ConversationInfo]:
        async with self._lock:
            # Sort by last_access descending so most recent appears first
            sorted_sessions = sorted(
                self._sessions.values(),
                key=lambda s: s.last_access,
                reverse=True,
            )
            return [
                ConversationInfo(
                    session_id=s.session_id,
                    model=s.chat.model,
                    title=s.title,
                    mode=s.mode,
                    message_count=sum(
                        1 for m in s.chat.messages if m.role in (ROLE_USER, ROLE_ASSISTANT)
                    ),
                    status=SessionStatus(s.status),
                    pinned=s.pinned,
                    created_at=_iso(s.created_at),
                    last_access=_iso(s.last_access),
                )
                for s in sorted_sessions
            ]

def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# 模块级单例
session_store = SessionStore()
