<script setup lang="ts">
import { ref, computed, watch, shallowRef } from "vue";
import FloatingWindow from "./FloatingWindow.vue";
import type { PreviewPayload } from "../../types/api";
import { fileIcon, stripCodeFence } from "../../utils";
import { UI_CONTENT_PREVIEW, UI_DOWNLOAD, UI_FILE_NAME, UI_IMAGE_PREVIEW, UI_NO_TEXT_CONTENT, UI_OPEN_IN_NEW_TAB, UI_RAW_DATA, UI_VIDEO_PREVIEW, UI_WEBPAGE_PREVIEW, UI_FILE_PREVIEW } from "../../constants";
import { loadMd } from "../../utils/markdown-lazy";

// ── props / emits ────────────────────────────

const props = defineProps<{
  modelValue: boolean;
  payload: PreviewPayload;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: boolean];
  close: [];
}>();

const showRaw = ref(true);

// ── 头部信息 ──────────────────────────────────

const headerTitle = computed(() => {
  switch (props.payload.kind) {
    case "image":   return UI_IMAGE_PREVIEW;
    case "video":   return UI_VIDEO_PREVIEW;
    case "webpage": return UI_WEBPAGE_PREVIEW;
    case "file":    return UI_FILE_PREVIEW;
  }
});

const headerIcon = computed(() => {
  switch (props.payload.kind) {
    case "image":   return "fa-solid fa-image";
    case "video":   return "fa-solid fa-video";
    case "webpage": return "fa-solid fa-globe";
    case "file":    return "fa-solid fa-file-lines";
  }
});

// ── 渲染策略 ──────────────────────────────────
// 图片 / 视频：直接渲染，避免 iframe 被 X-Frame-Options 拦截
// 网页：iframe src（唯一需要 iframe 的类型）

// ── 文件 Markdown 渲染（异步懒加载）────────────

const renderedFileContent = shallowRef<string | null>(null);

watch(
  () => props.payload,
  async (p) => {
    if (p.kind !== "file" || !p.text_content) { renderedFileContent.value = null; return; }
    try {
      const raw = stripCodeFence(p.text_content, true);
      const md = await loadMd();
      renderedFileContent.value = md.render(raw);
    } catch {
      renderedFileContent.value = p.text_content;
    }
  },
  { immediate: true },
);

// ── 资源 URL / 文件名 ──────────────────────────

const resourceUrl = computed(() => {
  const p = props.payload;
  if (p.kind === "webpage") return p.url;
  if (p.kind === "file") return null;
  return p.src ?? null;
});

// ── 下载（文件：后端 download_suffix 决定扩展名；远程：新标签页）─

function handleDownload() {
  const p = props.payload;
  if (p.kind !== "file" || !p.text_content) return;
  const raw = stripCodeFence(p.text_content);
  const suffix = p.download_suffix || p.filename.slice(p.filename.lastIndexOf("."));
  const name = p.filename.slice(0, p.filename.lastIndexOf(".")) + suffix;
  const blob = new Blob([raw], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

// ── 原始数据文本 ──────────────────────────────

const rawText = computed(() => {
  const p = props.payload;
  switch (p.kind) {
    case "image":
    case "video":   return p.src;
    case "webpage": return p.url;
    case "file":    return p.text_content ?? "";
  }
});
</script>

<template>
  <FloatingWindow
    width="520px"
    :title="headerTitle"
    :icon="headerIcon"
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    @close="emit('close')"
  >
    <template v-if="resourceUrl || payload.kind === 'file'" #actions>
      <a v-if="resourceUrl" class="btn-icon" :href="resourceUrl" target="_blank" rel="noopener" :title="UI_OPEN_IN_NEW_TAB" @click.stop>
        <i class="fa-solid fa-arrow-up-right-from-square"></i>
      </a>
      <button v-if="payload.kind === 'file'" class="btn-icon" :title="UI_DOWNLOAD" @click.stop="handleDownload">
        <i class="fa-solid fa-download"></i>
      </button>
    </template>
    <div class="mp-body">
      <!-- 文件头（仅 file kind） -->
      <div v-if="payload.kind === 'file'" class="file-header">
        <i class="file-icon" :class="fileIcon(payload.filename)"></i>
        <span class="file-name">{{ payload.filename }}</span>
      </div>

      <!-- 文件名（image / video） -->
      <div v-if="(payload.kind === 'image' || payload.kind === 'video') && payload.filename" class="info-block">
        <div class="info-label">{{ UI_FILE_NAME }}</div>
        <div class="info-value">{{ payload.filename }}</div>
      </div>

      <!-- 图片：直接渲染 -->
      <div v-if="payload.kind === 'image'" class="media-wrap">
        <img :src="payload.src" class="media-img" />
      </div>

      <!-- 视频：直接渲染 -->
      <div v-else-if="payload.kind === 'video'" class="media-wrap">
        <video :src="payload.src" class="media-vid" controls autoplay />
      </div>

      <!-- iframe：网页（iframe 在前，标题在后） -->
      <template v-else-if="payload.kind === 'webpage'">
        <div class="iframe-wrap">
          <iframe
            class="media-frame"
            :src="payload.url"
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
            referrerpolicy="no-referrer"
          />
        </div>
        <div v-if="payload.title" class="wp-info">
          <div class="info-label">标题</div>
          <div class="info-value">{{ payload.title }}</div>
        </div>
      </template>

      <!-- 文件内容（markdown 渲染） -->
      <div v-if="payload.kind === 'file' && renderedFileContent" class="info-block">
        <div class="info-label">{{ UI_CONTENT_PREVIEW }}</div>
        <div class="file-markdown markdown-content" v-html="renderedFileContent" />
      </div>
      <div v-else-if="payload.kind === 'file' && !renderedFileContent" class="info-block">
        <div class="info-empty">{{ UI_NO_TEXT_CONTENT }}</div>
      </div>

      <!-- 原始数据 toggle -->
      <div v-if="rawText" class="info-block">
        <button class="raw-toggle" @click="showRaw = !showRaw">
          <i class="fa-solid" :class="showRaw ? 'fa-chevron-down' : 'fa-chevron-right'"></i>
          {{ UI_RAW_DATA }}
        </button>
        <pre v-if="showRaw" class="info-code">{{ rawText }}</pre>
      </div>
    </div>
  </FloatingWindow>
</template>

<style scoped>
/* ── Body ────────────────────────────────────── */

.mp-body {
  padding: 14px;
  max-height: 70vh;
  overflow-y: auto;
}


.info-empty {
  font-size: 14px;
  color: var(--text-dim);
  font-style: italic;
}

/* ── 图片 / 视频直显 ──── */

.media-wrap {
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 12px;
  background: var(--code-bg);
}

.media-img {
  width: 100%;
  max-height: 360px;
  object-fit: contain;
  display: block;
}

.media-vid {
  width: 100%;
  max-height: 360px;
  display: block;
  outline: none;
}

/* ── iframe（网页）────── */

.iframe-wrap {
  overflow: hidden;
  background: var(--code-bg);
}

.media-frame {
  width: 100%;
  height: 480px;
  border: none;
  display: block;
}

.wp-info {
  margin-top: 12px;
}

/* ── 文件预览 ──────────── */

.file-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.file-icon {
  font-size: 28px;
  color: var(--accent);
}

.file-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  overflow-wrap: break-word;
}

/* ── Markdown 渲染样式 ──────────────────────────── */

.file-markdown {
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-secondary);
}

/* 全局 .markdown-content 提供基础规则，此处仅保留 MediaPreview 特有样式 */

.file-markdown :deep(pre) {
  position: relative;
}
.file-markdown :deep(pre)::before {
  content: attr(data-lang);
  position: absolute;
  top: 0;
  right: 6px;
  font-size: 0.75em;
  color: var(--text-dim);
  font-family: var(--font-mono);
  text-transform: lowercase;
  padding: 1px 6px;
  background: var(--white-04);
  border-radius: 0 var(--radius) 0 var(--radius);
}
.file-markdown :deep(pre code.hljs) {
  display: block;
  padding: 8px 10px;
  padding-top: 4px;
  line-height: 1.45;
  background: transparent;
  overflow-x: auto;
}
</style>
