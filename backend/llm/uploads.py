"""文件上传处理模块。

提供支持的扩展名映射、文件分类、内容提取与转换。
后端是文件类型支持的唯一来源，前端通过 GET /api/upload/config 查询。
"""

from __future__ import annotations

import base64
import logging
import uuid

_log = logging.getLogger(__name__)
from pathlib import Path

from fastapi import HTTPException, UploadFile
from pydantic import BaseModel, Field

from llm.constants import CONTENT_TYPE_OCTET_STREAM, CONTENT_TYPE_TEXT, MAX_TEXT_LENGTH, MAX_UPLOAD_SIZE, MB_BYTES

# ── 常量 ──────────────────────────────────────────────────

_UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
_UPLOAD_DIR.mkdir(exist_ok=True)

# ── 支持的文件扩展名 ─────────────────────────────────────

IMAGE_MIMES: dict[str, str] = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
    ".svg": "image/svg+xml", ".svgz": "image/svg+xml-compressed",
    ".ico": "image/x-icon", ".tif": "image/tiff", ".tiff": "image/tiff",
    ".avif": "image/avif", ".apng": "image/apng",
}

TEXT_EXTENSIONS: set[str] = {
    ".txt", ".md", ".rst", ".csv", ".tsv", ".log",
    ".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".tex", ".bib",
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
    ".css", ".scss", ".sass", ".less",
    ".vue", ".svelte", ".html", ".htm", ".ejs", ".pug", ".haml",
    ".sh", ".bash", ".bat", ".cmd", ".ps1",
    ".lua", ".pl", ".sql", ".r", ".rmd",
    ".py", ".rb", ".php", ".java", ".kt", ".kts", ".scala",
    ".cs", ".go", ".rs", ".swift", ".dart",
    ".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx",
    ".m", ".mm", ".fs", ".fsx", ".vb", ".vbs", ".groovy",
}

DOC_EXTENSIONS: set[str] = {
    ".pdf", ".epub", ".mobi",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".ipynb",
}

ALL_EXTENSIONS: set[str] = set(IMAGE_MIMES.keys()) | TEXT_EXTENSIONS | DOC_EXTENSIONS


# ── 语言提示映射 ─────────────────────────────────────────

_LANG_MAP: dict[str, str] = {
    ".py": "python", ".rb": "ruby", ".php": "php",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "jsx", ".ts": "typescript", ".tsx": "tsx",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".scala": "scala", ".cs": "csharp", ".go": "go",
    ".rs": "rust", ".swift": "swift", ".dart": "dart",
    ".c": "c", ".cpp": "cpp", ".cxx": "cpp", ".cc": "cpp",
    ".h": "c", ".hpp": "cpp", ".hxx": "cpp",
    ".m": "objectivec", ".mm": "objectivec",
    ".lua": "lua", ".r": "r", ".sql": "sql",
    ".sh": "bash", ".bash": "bash", ".bat": "batch", ".ps1": "powershell",
    ".html": "html", ".htm": "html", ".css": "css",
    ".scss": "scss", ".sass": "sass", ".less": "less",
    ".vue": "html", ".svelte": "html",
    ".json": "json", ".xml": "xml", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".tex": "latex",
    ".fs": "fsharp", ".fsx": "fsharp", ".vb": "vb",
    ".groovy": "groovy", ".pl": "perl",
    ".md": "markdown", ".rst": "rst",
}


def _get_language_hint(ext: str) -> str:
    """根据扩展名返回 Markdown 代码块语言标识。"""
    return _LANG_MAP.get(ext, "")


# ── 公共 API ─────────────────────────────────────────────


class UploadConfigResponse(BaseModel):
    """上传支持的文件类型配置。"""

    images: list[str] = Field(description="图片文件扩展名列表，含前导点")
    text: list[str] = Field(description="文本/代码文件扩展名列表，含前导点")
    documents: list[str] = Field(description="文档文件扩展名列表（需 MarkItDown 转换），含前导点")
    max_size_mb: int = Field(description="最大上传大小（MB）")


def get_upload_config() -> UploadConfigResponse:
    """返回上传配置 — 前端 accept 属性与客户端校验的唯一来源。"""
    return UploadConfigResponse(
        images=sorted(IMAGE_MIMES.keys()),
        text=sorted(TEXT_EXTENSIONS),
        documents=sorted(DOC_EXTENSIONS),
        max_size_mb=MAX_UPLOAD_SIZE // (MB_BYTES),
    )


async def process_upload(file: UploadFile) -> dict[str, object]:
    """处理上传文件，返回文件引用。

    图片：转为 base64 data URL 供多模态模型使用。
    文本 / 代码：直接读取为 UTF-8 文本。
    文档（PDF / Office / ePub / ipynb）：通过 MarkItDown 转为 Markdown。

    Raises:
        HTTPException: 文件过大、类型不支持、或转换失败。
    """
    if file.size and file.size > MAX_UPLOAD_SIZE:
        _log.warning("文件过大: %s (%d bytes, max=%d)", file.filename or "?", file.size, MAX_UPLOAD_SIZE)
        raise HTTPException(status_code=413, detail=f"文件过大，最大 {MAX_UPLOAD_SIZE // (MB_BYTES)} MB")

    content = await file.read()
    filename = file.filename or "file"
    ext = Path(filename).suffix.lower()

    # ── 分类 ──────────────────────────────────────────
    mime = IMAGE_MIMES.get(ext, CONTENT_TYPE_OCTET_STREAM)
    if mime == CONTENT_TYPE_OCTET_STREAM and ext in TEXT_EXTENSIONS:
        mime = CONTENT_TYPE_TEXT
    elif mime == CONTENT_TYPE_OCTET_STREAM and ext in DOC_EXTENSIONS:
        mime = CONTENT_TYPE_OCTET_STREAM

    is_image = ext in IMAGE_MIMES
    is_text = ext in TEXT_EXTENSIONS
    is_doc = ext in DOC_EXTENSIONS

    result: dict[str, object] = {
        "file_id": f"{uuid.uuid4().hex}_{filename}",
        "filename": filename,
        "size": len(content),
        "mime_type": mime,
        "is_image": is_image,
    }

    if is_image:
        result["data_url"] = f"data:{mime};base64,{base64.b64encode(content).decode()}"

    elif is_text:
        text = _decode_text(content)
        if len(text) > MAX_TEXT_LENGTH:
            text = text[:MAX_TEXT_LENGTH] + "\n\n…（内容过长，已截断）"

        lang = _get_language_hint(ext)
        if lang or ext not in (".txt", ".md", ".rst", ".log", ".csv", ".tsv"):
            _lang = lang or ext.lstrip(".")
            text = f"```{_lang}\n{text}\n```"

        result["text_content"] = text
        result["download_suffix"] = ext

    elif is_doc:
        safe_name = f"{uuid.uuid4().hex}{ext}"
        dest = _UPLOAD_DIR / safe_name
        dest.write_bytes(content)
        try:
            from markitdown import MarkItDown
            md = MarkItDown()
            conv_result = md.convert(str(dest))
            text = str(conv_result)
            if len(text) > MAX_TEXT_LENGTH:
                text = text[:MAX_TEXT_LENGTH] + "\n\n…（内容过长，已截断）"
            result["text_content"] = text
            result["download_suffix"] = ".md"
        except Exception as e:
            _log.warning("文档转换失败: %s (%s): %s", filename, ext, e)
            raise HTTPException(
                status_code=422, detail=f"文档转换失败: {e}"
            ) from e
        finally:
            try:
                dest.unlink()
            except Exception as e:
                _log.warning("临时文件清理失败: %s: %s", dest, e)

    else:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的文件类型：{ext}。支持的类型：图片、文本/代码、PDF/Office/ePub 文档。",
        )

    _log.info("文件上传: %s (%d bytes, type=%s)", filename, len(content), mime)
    return result


def _decode_text(content: bytes) -> str:
    """解码字节为文本，依次尝试 UTF-8 → latin-1 → replacement。"""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return content.decode("latin-1")
        except UnicodeDecodeError:
            return content.decode("utf-8", errors="replace")
