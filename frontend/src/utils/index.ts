import type { FileAttachment } from "../types/api";
import { IMG_EXTS } from "./media-utils";

/** 剥离后端对文本文件包裹的 ``` 围栏，返回纯内容。
 *  `strict`: true → 仅匹配 markdown/md 语言标识；
 *            false/省略 → 匹配任意语言标识（用于下载）。 */
export function stripCodeFence(raw: string, strict?: boolean): string {
  const re = strict
    ? /^```(?:markdown|md)\n([\s\S]*?)\n```$/
    : /^```[\w-]*\n([\s\S]*?)\n```$/;
  const m = raw.match(re);
  return m ? m[1] : raw;
}

/** 从扩展名推测 Font Awesome 图标。 */
export function fileIcon(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  if (IMG_EXTS.has("." + ext)) return "fa-solid fa-image";
  if (["pdf"].includes(ext)) return "fa-solid fa-file-pdf";
  if (["doc","docx"].includes(ext)) return "fa-solid fa-file-word";
  if (["xls","xlsx","csv","tsv"].includes(ext)) return "fa-solid fa-file-excel";
  if (["ppt","pptx"].includes(ext)) return "fa-solid fa-file-powerpoint";
  if (["epub","mobi"].includes(ext)) return "fa-solid fa-book";
  if (["zip","rar","7z","tar","gz"].includes(ext)) return "fa-solid fa-file-zipper";
  if (["py","js","ts","jsx","tsx","java","go","rs","cpp","c","h","hpp","cs","swift","kt","kts","scala","lua","sql","r","rmd","rb","php","dart","groovy","pl","ps1","sh","bash","bat","cmd","fs","fsx","vb","vbs","m","mm"].includes(ext)) return "fa-solid fa-file-code";
  if (["html","htm","css","scss","sass","less","vue","svelte","ejs","pug","haml","xml"].includes(ext)) return "fa-solid fa-file-code";
  if (["txt","md","rst","log","tex","bib","json","yaml","yml","toml","ini","cfg","conf"].includes(ext)) return "fa-solid fa-file-lines";
  return "fa-solid fa-file";
}

/** 获取文件预览文本（截断） */
export function filePreview(f: FileAttachment): string {
  if (f.data_url) return f.filename;
  const text = f.text_content || "";
  const clean = text.replace(/```[\s\S]*?\n?/g, "").trim();
  return clean.slice(0, 80) + (clean.length > 80 ? "…" : "");
}

/** 解析消息中的 [文件: name] 块，提取为 FileAttachment[]，返回纯文本 */
export function parseFileBlocks(content: string): { text: string; files: FileAttachment[] } {
  if (!content || !content.startsWith("[文件:")) {
    return { text: content, files: [] };
  }
  const parts = content.split("\n\n---\n\n");
  const files: FileAttachment[] = [];
  const textParts: string[] = [];

  for (const part of parts) {
    const match = part.match(/^\[文件: (.+?)\]\n\n([\s\S]*)/);
    if (match) {
      files.push({ filename: match[1], text_content: match[2] });
    } else if (part.trim()) {
      textParts.push(part);
    }
  }

  return { text: textParts.join("\n\n"), files };
}
