/** 共享 markdown-it 实例 — 通过 getMd() 异步创建，katex 按需加载。
 *  ⚠️ 仅通过 markdown-lazy.ts 动态导入，禁止直接静态 import。 */

import type MarkdownIt from "markdown-it";
import MarkdownItBase from "markdown-it";
import texmath from "markdown-it-texmath";
import hljs from "highlight.js/lib/core";
import { isExternalUrl, mediaKindFromUrl } from "./media-utils";
export { isExternalUrl, IMG_EXTS, VID_EXTS, mediaKindFromUrl } from "./media-utils";

// ── 注册常用语言 ──────────────────────────────────

import javascript from "highlight.js/lib/languages/javascript";
import typescript from "highlight.js/lib/languages/typescript";
import python from "highlight.js/lib/languages/python";
import bash from "highlight.js/lib/languages/bash";
import json from "highlight.js/lib/languages/json";
import xml from "highlight.js/lib/languages/xml";
import css from "highlight.js/lib/languages/css";
import sql from "highlight.js/lib/languages/sql";
import markdown from "highlight.js/lib/languages/markdown";
import yaml from "highlight.js/lib/languages/yaml";
import rust from "highlight.js/lib/languages/rust";
import go from "highlight.js/lib/languages/go";
import java from "highlight.js/lib/languages/java";
import c from "highlight.js/lib/languages/c";
import cpp from "highlight.js/lib/languages/cpp";
import csharp from "highlight.js/lib/languages/csharp";
import php from "highlight.js/lib/languages/php";
import ruby from "highlight.js/lib/languages/ruby";
import swift from "highlight.js/lib/languages/swift";
import kotlin from "highlight.js/lib/languages/kotlin";
import dart from "highlight.js/lib/languages/dart";
import diff from "highlight.js/lib/languages/diff";
import plaintext from "highlight.js/lib/languages/plaintext";
import shell from "highlight.js/lib/languages/shell";

hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("js", javascript);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("ts", typescript);
hljs.registerLanguage("python", python);
hljs.registerLanguage("py", python);
hljs.registerLanguage("bash", bash);
hljs.registerLanguage("sh", bash);
hljs.registerLanguage("shell", shell);
hljs.registerLanguage("json", json);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("html", xml);
hljs.registerLanguage("css", css);
hljs.registerLanguage("sql", sql);
hljs.registerLanguage("markdown", markdown);
hljs.registerLanguage("md", markdown);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("yml", yaml);
hljs.registerLanguage("rust", rust);
hljs.registerLanguage("rs", rust);
hljs.registerLanguage("go", go);
hljs.registerLanguage("java", java);
hljs.registerLanguage("c", c);
hljs.registerLanguage("cpp", cpp);
hljs.registerLanguage("c++", cpp);
hljs.registerLanguage("csharp", csharp);
hljs.registerLanguage("cs", csharp);
hljs.registerLanguage("php", php);
hljs.registerLanguage("ruby", ruby);
hljs.registerLanguage("rb", ruby);
hljs.registerLanguage("swift", swift);
hljs.registerLanguage("kotlin", kotlin);
hljs.registerLanguage("kt", kotlin);
hljs.registerLanguage("dart", dart);
hljs.registerLanguage("diff", diff);
hljs.registerLanguage("plaintext", plaintext);
hljs.registerLanguage("text", plaintext);

// ── 懒创建 md 实例（katex 动态导入，独立 chunk）───

let _mdPromise: Promise<MarkdownIt> | null = null;

export function getMd(): Promise<MarkdownIt> {
  if (_mdPromise) return _mdPromise;
  _mdPromise = import("katex").then(katexMod => {
    const katex = katexMod.default;
    const md = MarkdownItBase({ html: true, breaks: true, linkify: true })
      .use(texmath, {
        engine: katex,
        delimiters: ["dollars"],
        katexOptions: { throwOnError: false },
      });

    // ── 代码块渲染 ──────────────────────────────

    function _copyBtn(): string {
      return `<button class="code-copy-btn" title="复制"><i class="fa-solid fa-copy"></i></button>`;
    }

    md.renderer.rules.fence = (tokens, idx, _options, _env, _self) => {
      const token = tokens[idx];
      const lang = token.info?.trim() || "";
      const code = token.content;
      const langTag = lang ? `<span class="code-lang">${md.utils.escapeHtml(lang)}</span>` : "";

      if (lang && hljs.getLanguage(lang)) {
        try {
          const highlighted = hljs.highlight(code, { language: lang }).value;
          return `<pre data-lang="${lang}"><div class="code-header">${langTag}${_copyBtn()}</div><code class="hljs">${highlighted}</code></pre>`;
        } catch { /* fall through */ }
      }

      const escaped = md.utils.escapeHtml(code);
      return `<pre data-lang="${lang || ''}"><div class="code-header">${langTag}${_copyBtn()}</div><code>${escaped}</code></pre>`;
    };

    // ── 辅助函数 ──────────────────────────────────

    function escAttr(s: string) {
      return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
    }

    function filenameFromUrl(url: string): string {
      try { return decodeURIComponent(url.split("/").pop() || url); }
      catch { return url; }
    }

    // ── `![alt](url)` → 预览卡片 ──────────────────

    const _defaultImage = md.renderer.rules.image!;
    md.renderer.rules.image = (tokens, idx, options, env, self) => {
      const token = tokens[idx];
      const src = token.attrGet("src") || "";
      const alt = token.content || "";

      if (!isExternalUrl(src)) {
        token.attrSet("loading", "lazy");
        return _defaultImage(tokens, idx, options, env, self);
      }

      const kind = mediaKindFromUrl(src);
      const preview =
        kind === "image" ? `<img src="${escAttr(src)}" loading="lazy" referrerpolicy="no-referrer">`
        : kind === "video" ? `<video src="${escAttr(src)}" preload="metadata" muted disablepictureinpicture disableremoteplayback></video>`
        : `<span class="lc-url">${escAttr(src)}</span>`;
      const title = alt || filenameFromUrl(src);
      const barIcon = kind === "image" ? "fa-solid fa-image"
        : kind === "video" ? "fa-solid fa-video" : "fa-solid fa-globe";

      return `<a class="link-card link-card--${kind}" href="${escAttr(src)}" target="_blank" rel="noopener noreferrer" data-kind="${kind}">`
        + `<span class="lc-preview">${preview}</span>`
        + `<span class="lc-bar"><i class="${barIcon} lc-bar-icon"></i><span class="lc-title">${title}</span></span>`
        + `</a>`;
    };

    // ── Core：独立成行 `[]()` → 块级卡片 ─────────

    md.core.ruler.push("link_blocks", (state) => {
      for (const token of state.tokens) {
        if (token.type !== "inline" || !token.children?.length) continue;
        const kids = token.children;
        let segStart = 0;
        for (let i = 0; i <= kids.length; i++) {
          if (i < kids.length && kids[i].type !== "softbreak" && kids[i].type !== "hardbreak") continue;
          const seg = kids.slice(segStart, i).filter(
            k => k.type !== "text" || (k.content || "").trim()
          );
          if (seg.length >= 2 && seg[0].type === "link_open" && seg[seg.length - 1].type === "link_close") {
            seg[0].attrSet("data-block", "1");
          }
          segStart = i + 1;
        }
      }
    });

    // ── `[]()` 渲染：独立行 → 卡片，行内 → 徽章 ──

    function cardPreview(kind: string, href: string): string {
      if (kind === "image") return `<img src="${escAttr(href)}" loading="lazy" referrerpolicy="no-referrer">`;
      if (kind === "video") return `<video src="${escAttr(href)}" preload="metadata" muted disablepictureinpicture disableremoteplayback></video>`;
      return `<span class="lc-url">${escAttr(href)}</span>`;
    }
    function cardBarIcon(kind: string): string {
      if (kind === "image") return "fa-solid fa-image";
      if (kind === "video") return "fa-solid fa-video";
      return "fa-solid fa-globe";
    }

    const _defaultLink =
      md.renderer.rules.link_open ||
      ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options));

    md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
      const token = tokens[idx];
      const href = token.attrGet("href") || "";

      if (!href.startsWith("http://") && !href.startsWith("https://")) {
        token.attrSet("target", "_blank");
        token.attrSet("rel", "noopener noreferrer");
        return _defaultLink(tokens, idx, options, env, self);
      }

      const kind = mediaKindFromUrl(href);
      token.attrSet("target", "_blank");
      token.attrSet("rel", "noopener noreferrer");
      token.attrSet("data-kind", kind);

      if (token.attrGet("data-block") === "1") {
        token.attrSet("class", `link-card link-card--${kind}`);
        return `<a${self.renderAttrs(token)}>`
          + `<span class="lc-preview">${cardPreview(kind, href)}</span>`
          + `<span class="lc-bar"><i class="${cardBarIcon(kind)} lc-bar-icon"></i><span class="lc-title">`;
      }

      token.attrSet("class", `link-badge link-badge--${kind}`);
      return `<a${self.renderAttrs(token)}><i class="${cardBarIcon(kind)} lb-icon"></i>`;
    };

    const _defaultLinkClose =
      md.renderer.rules.link_close ||
      ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options));

    md.renderer.rules.link_close = (tokens, idx, options, env, self) => {
      let openToken: any = null;
      for (let i = idx - 1; i >= 0; i--) {
        if (tokens[i].type === "link_open" && tokens[i].level === tokens[idx].level) {
          openToken = tokens[i]; break;
        }
        if (tokens[i].level < tokens[idx].level) break;
      }
      const cls: string = openToken?.attrGet?.("class") || "";
      if (cls.includes("link-badge")) return `</a>`;
      if (cls.includes("link-card")) return `</span></span></a>`;
      return _defaultLinkClose(tokens, idx, options, env, self);
    };

    return md;
  });
  return _mdPromise;
}
