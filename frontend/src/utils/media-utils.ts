/** 轻量媒体工具 — 零依赖，可被任意模块安全导入而不引入 markdown 重型依赖 */

export const IMG_EXTS = new Set([
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
  ".bmp", ".ico", ".avif", ".apng", ".tif", ".tiff",
]);
export const VID_EXTS = new Set([
  ".mp4", ".webm", ".ogg", ".mov", ".avi", ".mkv", ".wmv", ".flv",
]);

export function isExternalUrl(url: string): boolean {
  return url.startsWith("http://") || url.startsWith("https://");
}

/** HTML 转义（等效 markdown-it 内置 escapeHtml） */
export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function mediaKindFromUrl(url: string): "image" | "video" | "webpage" {
  try {
    const path = new URL(url).pathname.toLowerCase();
    const ext = path.slice(path.lastIndexOf("."));
    if (IMG_EXTS.has(ext)) return "image";
    if (VID_EXTS.has(ext)) return "video";
  } catch { /* invalid URL */ }
  return "webpage";
}
