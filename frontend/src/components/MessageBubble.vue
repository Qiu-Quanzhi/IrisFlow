<script setup lang="ts">
import { ref, computed, watch, shallowRef } from "vue";
import { COPY_FEEDBACK_DURATION, ROLE_ASSISTANT, ROLE_USER, UI_COPIED, UI_COPY } from "../constants";
import type { UIMessage, PreviewPayload } from "../types/api";
import { fileIcon, filePreview } from "../utils";
import { loadMd, mediaKindFromUrl, isExternalUrl } from "../utils/markdown-lazy";
import ImageViewer from "./ImageViewer.vue";

const props = defineProps<{
  msg: UIMessage;
}>();

const emit = defineEmits<{
  preview: [payload: PreviewPayload];
}>();

const copied = ref(false);

// ── 点击 markdown 内容：图片/视频/链接 → MediaPreview ──

function handleContentClick(e: MouseEvent) {
  const target = e.target as HTMLElement;
  // <img> 点击 → 图片预览（包括卡片缩略图）
  if (target.tagName === "IMG") {
    const src = (target as HTMLImageElement).src;
    if (src) { e.preventDefault(); emit("preview", { kind: "image", src }); }
    return;
  }
  // 找到最近的 <a> 祖先（支持点击卡片内部子元素）
  const anchor = target.closest<HTMLAnchorElement>("a");
  if (!anchor) return;
  const href = anchor.getAttribute("href") || "";
  if (!isExternalUrl(href)) return;
  e.preventDefault();
  const kind = mediaKindFromUrl(href);
  if (kind === "image") {
    emit("preview", { kind: "image", src: href });
  } else if (kind === "video") {
    emit("preview", { kind: "video", src: href });
  } else {
    emit("preview", { kind: "webpage", url: href, title: anchor.textContent?.trim() || undefined });
  }
}

const renderedContent = shallowRef<string | null>(null);

// 异步渲染 markdown — lazy-load 整个 markdown-it/hljs/katex 管线
watch(
  () => props.msg.content,
  async (content) => {
    if (props.msg.role !== ROLE_ASSISTANT || !content?.trim()) {
      renderedContent.value = null;
      return;
    }
    try {
      const md = await loadMd();
      renderedContent.value = md.render(content);
    } catch {
      renderedContent.value = content;
    }
  },
  { immediate: true },
);

/** 空内容的 assistant 气泡不展示 */
const isEmpty = computed(() => props.msg.role === ROLE_ASSISTANT && !props.msg.content);

async function handleCopy() {
  try {
    await navigator.clipboard.writeText(props.msg.content);
    copied.value = true;
    setTimeout(() => (copied.value = false), COPY_FEEDBACK_DURATION);
  } catch { /* ignore */ }
}
</script>

<template>
  <div v-if="!isEmpty" class="msg-row" :class="{ user: msg.role === ROLE_USER, assistant: msg.role === ROLE_ASSISTANT }">
    <div
      class="bubble"
      :class="{ user: msg.role === ROLE_USER, assistant: msg.role === ROLE_ASSISTANT }"
    >
      <!-- 图片 → 文件 → 文字（与发送区顺序一致） -->
      <div v-if="msg.images?.length && msg.role === ROLE_USER" class="msg-images">
        <ImageViewer
          v-for="(img, i) in msg.images" :key="i" :src="img"
          @click="emit('preview', { kind: 'image', src: img })"
        />
      </div>
      <div v-if="msg.files?.length && msg.role === ROLE_USER" class="msg-files">
        <div
          v-for="(f, i) in msg.files" :key="i" class="msg-file-card"
          @click="emit('preview', { kind: 'file', filename: f.filename, text_content: f.text_content, download_suffix: f.download_suffix })"
        >
          <i class="msg-file-icon" :class="fileIcon(f.filename)"></i>
          <span class="msg-file-name">{{ f.filename }}</span>
          <span class="msg-file-text">{{ filePreview(f) }}</span>
        </div>
      </div>
      <div
        v-if="renderedContent"
        class="content markdown markdown-content"
        v-html="renderedContent"
        @click="handleContentClick"
      />
      <div v-if="!renderedContent && msg.content" class="content">{{ msg.content }}</div>
    </div>

    <!-- 复制按钮：气泡下方，靠两侧 -->
    <button
      v-if="msg.content && (msg.role === ROLE_USER ? msg.streamDone !== false : msg.streamDone)"
      class="copy-btn below"
      :class="{ ok: copied }"
      @click="handleCopy"
      :title="copied ? UI_COPIED : UI_COPY"
    >
      <i v-if="copied" class="fa-solid fa-check"></i>
      <i v-else class="fa-regular fa-copy"></i>
    </button>
  </div>
</template>

<style scoped>
.msg-row {
  display: flex;
  flex-direction: column;
  width: 100%;
  margin-bottom: 12px;
}

.msg-row.user {
  align-items: flex-end;
}

.msg-row.assistant {
  align-items: flex-start;
}

.copy-btn.below {
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-dim);
  cursor: pointer;
  margin-top: 4px;
}

.copy-btn.below.ok {
  color: var(--accent);
  border-color: var(--accent);
}

.bubble {
  max-width: 85%;
  padding: 10px 14px;
  border-radius: var(--radius-lg);
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.bubble.user {
  background: var(--accent);
  color: var(--white);
  border-radius: var(--radius-lg) var(--radius-lg) 4px var(--radius-lg);
}

.bubble.assistant {
  width: 100%;
  max-width: none;
  padding: 8px 0;
  background: transparent;
  border: none;
  border-radius: 0;
}

.content {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

.msg-images { display: flex; gap: 4px; flex-wrap: wrap; justify-content: flex-end; margin-bottom: 4px; }

.msg-files { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; margin-bottom: 6px; }

.msg-file-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  min-width: 120px;
  max-width: 200px;
  padding: 8px 10px;
  background: var(--white-12);
  border: 1px solid var(--white-20);
  border-radius: 10px;
  cursor: pointer;
}
.msg-file-card:hover { background: var(--white-18); }

.msg-file-icon { font-size: 21px; color: var(--white-85); margin-bottom: 2px; }

.msg-file-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--white-95);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.msg-file-text {
  font-size: 12px;
  color: var(--white-55);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
  line-height: 1.3;
}

/* ── Markdown 渲染样式 ──────────────────────────── */

/* 全局 .markdown-content 提供基础规则，此处仅保留 MessageBubble 特有样式 */

.markdown :deep(img) {
  max-width: 100%;
  border-radius: var(--radius);
  cursor: pointer;
  margin: 4px 0;
}

/* ── 行内链接徽章 ──────────────────────────────── */

.markdown :deep(.link-badge) {
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
  padding: 0 3px;
  text-decoration: none;
  cursor: pointer;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  transition: color 0.15s, background 0.15s;
}
.markdown :deep(.link-badge:hover) {
  color: var(--accent);
  background: var(--accent-bg-subtle);
}
.markdown :deep(.link-badge .lb-icon) {
  font-size: 0.8em;
  opacity: 0.7;
  transition: opacity 0.15s;
}
.markdown :deep(.link-badge:hover .lb-icon) {
  opacity: 1;
}

/* ── 块级预览卡片 ──────────────────────────────── */

.markdown :deep(.link-card) {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 360px;
  margin: 6px 0;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  text-decoration: none;
  cursor: pointer;
  overflow: hidden;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.markdown :deep(.link-card:hover) {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent-shadow);
}

/* 预览区（图片 / 视频 placeholder / 网页图标） */
.markdown :deep(.lc-preview) {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  aspect-ratio: 1.618 / 1;
  background: var(--code-bg);
  color: var(--text-dim);
  font-size: 48px;
  overflow: hidden;
}
.markdown :deep(.lc-preview img),
.markdown :deep(.lc-preview video) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.markdown :deep(.lc-url) {
  padding: 12px;
  font-size: 13px;
  font-family: var(--font-mono);
  color: var(--text-dim);
  overflow-wrap: break-word;
  line-height: 1.5;
}
/* 底部信息栏 */
.markdown :deep(.lc-bar) {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-top: 1px solid var(--border);
}
.markdown :deep(.lc-bar-icon) {
  font-size: 14px;
  color: var(--text-dim);
  flex-shrink: 0;
  width: 16px;
  text-align: center;
}
.markdown :deep(.lc-title) {
  flex: 1;
  min-width: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.3;
}

/* 图片/视频卡片：隐藏尾部原始 URL 文本 */
.markdown :deep(.link-card--image),
.markdown :deep(.link-card--video) {
  font-size: 0;
}
.markdown :deep(.link-card--image .lc-bar),
.markdown :deep(.link-card--video .lc-bar) {
  font-size: 14px;
}
</style>
