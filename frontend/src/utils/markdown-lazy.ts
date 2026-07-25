/** 轻量入口 — markdown-it + hljs + katex 仅在 loadMd() 首次调用时动态加载。
 *  工具函数从 media-utils.ts 直接导入（零依赖），不会引入重型 chunk。 */

import type MarkdownIt from "markdown-it";

export { isExternalUrl, IMG_EXTS, VID_EXTS, mediaKindFromUrl } from "./media-utils";

let _mdPromise: Promise<MarkdownIt> | null = null;

/** 懒加载 markdown-it 实例（含 hljs + katex），多次调用共享同一缓存 */
export function loadMd(): Promise<MarkdownIt> {
  if (!_mdPromise) {
    _mdPromise = import("./markdown").then(m => m.getMd());
  }
  return _mdPromise;
}
