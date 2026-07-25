import { createApp } from "vue";
import App from "./App.vue";
import router from "./router";
import "./style.css";
import "@fortawesome/fontawesome-free/css/all.min.css";
import "highlight.js/styles/github-dark.min.css";
import "katex/dist/katex.min.css";

// ── 全局代码块复制 ──────────────────────────────

document.addEventListener("click", (e) => {
  const btn = (e.target as HTMLElement).closest<HTMLElement>(".code-copy-btn");
  if (!btn) return;
  const pre = btn.closest("pre");
  const code = pre?.querySelector("code");
  if (!code) return;
  navigator.clipboard.writeText(code.textContent || "").then(() => {
    btn.classList.add("copied");
    setTimeout(() => btn.classList.remove("copied"), 1500);
  }).catch(() => { /* 忽略复制失败 */ });
});

createApp(App).use(router).mount("#app");
