<script setup lang="ts">
import { ref, computed, onMounted, watch, inject, nextTick } from "vue";
import { useRoute } from "vue-router";
import { getToolDisplay, getToolInfo } from "../composables/toolMetadata";
import { getUploadConfig, getServerUrl, isConnectionError, BASE, PATH_UPLOAD } from "../api/client";
import {
  DEFAULT_MAX_SIZE_MB,
  DRAFT_NEW,
  UI_FAST_MODE,
  UI_INPUT_PLACEHOLDER,
  UI_SESSION_SETTINGS,
  UI_STOP,
  UI_THINK_MODE,
} from "../constants";
import { draftStore } from "../composables/drafts";
import { fileIcon, filePreview } from "../utils";
import { ON_CONNECTION_LOST_KEY } from "../composables/injectionKeys";
import type { FileAttachment, PreviewPayload, SessionSettings } from "../types/api";
import ImageViewer from "./ImageViewer.vue";
import SessionSettingsPanel from "./SessionSettingsPanel.vue";

const props = defineProps<{
  loading: boolean;
  disabled?: boolean;
  enabledBuiltins: string[];
  toolGroups: Record<string, string[]>;
  sessionSettings: SessionSettings;
  defaultSettings: SessionSettings;
}>();

const route = useRoute();
const sessionId = computed(() => (route.params.sessionId as string) ?? null);
const onConnectionLost = inject(ON_CONNECTION_LOST_KEY, () => {});

const emit = defineEmits<{
  send: [message: string, files?: FileAttachment[], thinking?: boolean];
  stop: [];
  toggleTool: [name: string];
  toggleGroup: [payload: { groupName: string; toolNames: string[] }];
  manageGroup: [groupName: string];
  preview: [payload: PreviewPayload];
  "update:sessionSettings": [value: SessionSettings];
}>();

const input = ref("");
const textareaRef = ref<HTMLTextAreaElement | null>(null);
const uploadFiles = ref<FileAttachment[]>([]);
const uploading = ref(false);
const thinking = ref(true);
const settingsVisible = ref(false);
// ── 工具组 ─────────────────────────────────────────

/** 工具组条目列表（"内置"优先，其余按名称排序） */
const sortedGroupEntries = computed<[string, string[]][]>(() =>
  Object.entries(props.toolGroups)
    .sort(([a], [b]) => {
      if (a === "内置") return -1;
      if (b === "内置") return 1;
      return a.localeCompare(b);
    })
);

const fileInputRef = ref<HTMLInputElement | null>(null);
const acceptExts = ref("");
const maxSizeMB = ref(DEFAULT_MAX_SIZE_MB);
const uploadError = ref("");
const allowedExts = ref<Set<string>>(new Set());

onMounted(async () => {
  try {
    const cfg = await getUploadConfig();
    maxSizeMB.value = cfg.max_size_mb;
    allowedExts.value = new Set([...cfg.images, ...cfg.text, ...cfg.documents]);
    // 构建 accept 字符串：图片用 MIME，其余用扩展名
    const parts: string[] = [];
    for (const ext of cfg.images) {
      if (ext === ".jpg" || ext === ".jpeg") parts.push("image/jpeg");
      else if (ext === ".png") parts.push("image/png");
      else if (ext === ".gif") parts.push("image/gif");
      else if (ext === ".webp") parts.push("image/webp");
      else if (ext === ".svg") parts.push("image/svg+xml");
      else if (ext === ".bmp") parts.push("image/bmp");
      else if (ext === ".avif") parts.push("image/avif");
      else parts.push(ext);
    }
    for (const ext of cfg.documents) parts.push(ext);
    for (const ext of cfg.text) parts.push(ext);
    acceptExts.value = parts.join(",");
  } catch {
    acceptExts.value = "image/*,.txt,.md,.pdf,.doc,.docx";
  }
});

// ── 草稿（仅内存，页面刷新后消失） ──────────────────

function saveDraft(sid: string | null | undefined) {
  if (sid === undefined) return;
  const key = sid ?? DRAFT_NEW;
  if (!draftStore[key]) draftStore[key] = {};
  draftStore[key].text = input.value;
  draftStore[key].files = [...uploadFiles.value];
  draftStore[key].thinking = thinking.value;
}

function restoreDraft(sid: string | null) {
  // 新会话界面：消息为空 → 始终重置为默认值
  if (sid === null) {
    input.value = "";
    uploadFiles.value = [];
    thinking.value = true;
    emit("update:sessionSettings", { ...props.defaultSettings });
    return;
  }
  const key = sid;
  const draft = draftStore[key];
  // 若该会话无已保存的草稿，继承新会话界面的 thinking 偏好（不继承文字/文件）
  const fallback = !draft ? draftStore[DRAFT_NEW] : undefined;
  input.value = draft?.text ?? "";
  uploadFiles.value = draft?.files ? [...draft.files] : [];
  thinking.value = draft?.thinking ?? fallback?.thinking ?? true;
}

/** 会话切换时保存旧草稿、恢复新草稿 */
watch(sessionId, (sid, oldSid) => {
  saveDraft(oldSid);
  restoreDraft(sid);
}, { immediate: true });

/** defaultSettings 后端异步加载完成后，补发到新会话（消除竞态） */
watch(() => props.defaultSettings, (d) => {
  if (sessionId.value === null) {
    emit("update:sessionSettings", { ...d });
  }
});

const hasFiles = computed(() => uploadFiles.value.length > 0);

/** 按类型分组，图片与文件分行展示 */
interface UploadFileEntry extends FileAttachment { _idx: number }
const imageFiles = computed<UploadFileEntry[]>(() =>
  uploadFiles.value.map((f, i) => ({ ...f, _idx: i })).filter(f => f.data_url)
);
const docFiles = computed<UploadFileEntry[]>(() =>
  uploadFiles.value.map((f, i) => ({ ...f, _idx: i })).filter(f => !f.data_url)
);

async function handleFileChange(e: Event) {
  const target = e.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;
  uploadError.value = "";

  // 客户端预检（配置来自后端 GET /api/upload/config）
  const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
  if (allowedExts.value.size > 0 && !allowedExts.value.has(ext)) {
    uploadError.value = `不支持的文件类型：${ext}`;
    target.value = "";
    return;
  }
  const sizeMB = file.size / (1024 * 1024);
  if (sizeMB > maxSizeMB.value) {
    uploadError.value = `文件过大（${sizeMB.toFixed(1)} MB），最大 ${maxSizeMB.value} MB`;
    target.value = "";
    return;
  }

  uploading.value = true;
  try {
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(`${getServerUrl()}${BASE}${PATH_UPLOAD}`, { method: "POST", body: form });
    if (!resp.ok) {
      // HTTP 错误 — 后端可达，静默忽略
      return;
    }
    const data = await resp.json();
    uploadFiles.value.push({
      filename: (data.filename as string) || file.name,
      data_url: data.data_url as string | undefined,
      text_content: data.text_content as string | undefined,
      download_suffix: data.download_suffix as string | undefined,
    });
  } catch (e) {
    if (isConnectionError(e)) onConnectionLost();
  }
  finally { uploading.value = false; target.value = ""; }
}

function removeFile(idx: number) {
  uploadFiles.value.splice(idx, 1);
}

// ── 分组工具开关 ────────────────────────────────────

function groupToggleState(names: string[]): "all" | "partial" | "none" {
  const count = names.filter(n => props.enabledBuiltins.includes(n)).length;
  if (count === names.length) return "all";
  if (count === 0) return "none";
  return "partial";
}

function toggleGroup(groupName: string, toolNames: string[]) {
  emit("toggleGroup", { groupName, toolNames });
}

function onInputAutoResize(event: Event) {
  const el = event.target as HTMLTextAreaElement;
  el.style.height = "auto";
  el.style.height = el.scrollHeight + "px";
}

function handleSend() {
  const text = input.value.trim();
  if ((!text && !hasFiles.value) || props.loading) return;
  const files = uploadFiles.value.length ? [...uploadFiles.value] : undefined;
  emit("send", text || "", files, thinking.value);
  // 清空草稿：仅清除文字与文件，保留思考/工具偏好
  const key = sessionId.value ?? DRAFT_NEW;
  if (!draftStore[key]) draftStore[key] = {};
  draftStore[key].text = "";
  draftStore[key].files = [];
  draftStore[key].thinking = thinking.value;
  input.value = "";
  uploadFiles.value = [];
  nextTick(() => {
    if (textareaRef.value) textareaRef.value.style.height = "auto";
  });
}

</script>

<template>
  <div class="input-card">
    <!-- 上传错误提示 -->
    <div v-if="uploadError" class="upload-error">
      <span>{{ uploadError }}</span>
      <button class="upload-error-close" @click="uploadError = ''"><i class="fa-solid fa-xmark"></i></button>
    </div>
    <!-- 附件预览 — 图片 -->
    <div v-if="imageFiles.length" class="upload-previews">
      <div v-for="f in imageFiles" :key="f._idx" class="preview-item">
        <ImageViewer
          :src="f.data_url!" :size="56"
          @click="emit('preview', { kind: 'image', src: f.data_url!, filename: f.filename })"
        />
        <button class="preview-remove" @click.stop="removeFile(f._idx)"><i class="fa-solid fa-xmark"></i></button>
      </div>
    </div>
    <!-- 附件预览 — 文档 -->
    <div v-if="docFiles.length" class="upload-previews">
      <div v-for="f in docFiles" :key="f._idx" class="preview-item preview-file">
        <div
          class="preview-file-card"
          @click="emit('preview', { kind: 'file', filename: f.filename, text_content: f.text_content, download_suffix: f.download_suffix })"
        >
          <i class="preview-file-icon" :class="fileIcon(f.filename)"></i>
          <span class="preview-file-name">{{ f.filename }}</span>
          <span class="preview-file-text">{{ filePreview(f) }}</span>
        </div>
        <button class="preview-remove" @click.stop="removeFile(f._idx)"><i class="fa-solid fa-xmark"></i></button>
      </div>
    </div>
    <!-- 会话参数浮窗 -->
    <SessionSettingsPanel
      v-model="settingsVisible"
      :settings="sessionSettings"
      :defaults="defaultSettings"
      @update:settings="$emit('update:sessionSettings', $event)"
    />
    <!-- 文字输入 -->
    <textarea
      ref="textareaRef"
      v-model="input"
      class="input-area"
      :placeholder="UI_INPUT_PLACEHOLDER"
      rows="3"
      :disabled="disabled"
      @keydown.enter.exact.prevent="handleSend"
      @input="onInputAutoResize"
    />

    <!-- 工具栏 + 发送按钮 -->
    <div class="input-row">
      <div class="input-tools">
        <!-- 工具组：胶囊开关 + 管理浮窗入口 -->
        <div v-for="[groupName, toolNames] in sortedGroupEntries" :key="groupName" class="group-block">
          <div class="group-pill-wrap">
            <button
              class="group-pill"
              :class="{
                on: groupToggleState(toolNames) === 'all',
                partial: groupToggleState(toolNames) === 'partial',
              }"
              @click="toggleGroup(groupName, toolNames)"
              :title="`${groupName}（${toolNames.length} 个工具）`"
            >
              <span class="group-dot" :class="{ active: groupToggleState(toolNames) !== 'none' }"></span>
              <span class="group-name">{{ groupName }}</span>
            </button>
            <button
              class="group-expand-btn"
              @click="emit('manageGroup', groupName)"
              title="打开工具管理浮窗"
            >
              <i class="fa-solid fa-angles-right group-expand-icon"></i>
            </button>
          </div>
        </div>
      </div>

      <div class="input-actions">
        <button class="circle-btn-lg attach-btn" :class="{ on: uploading || hasFiles }" @click="fileInputRef?.click()">
          <i v-if="uploading" class="fa-solid fa-spinner fa-spin"></i>
          <i v-else class="fa-solid fa-paperclip"></i>
        </button>
        <button class="circle-btn-lg attach-btn settings-btn" :class="{ on: settingsVisible }" @click="settingsVisible = true" :title="UI_SESSION_SETTINGS">
          <i class="fa-solid fa-sliders"></i>
        </button>
        <input
          ref="fileInputRef"
          type="file"
          class="file-input"
          :accept="acceptExts"
          @change="handleFileChange"
        />
        <button
          class="circle-btn-lg think-btn"
          :class="{ on: thinking }"
          @click="thinking = !thinking"
          :title="thinking ? UI_THINK_MODE : UI_FAST_MODE"
        >
          <i :class="thinking ? 'fa-solid fa-lightbulb' : 'fa-solid fa-feather-pointed'"></i>
        </button>
        <button
          v-if="loading"
          class="btn-send stop"
          @click="emit('stop')"
          :title="UI_STOP"
        >
          <i class="fa-solid fa-stop"></i>
        </button>
        <button
          v-else
          class="btn-send"
          :disabled="!input.trim() && !hasFiles"
          @click="handleSend"
        >
          <i class="fa-solid fa-play"></i>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.input-card {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 20px;
  overflow: hidden;
}

.input-area {
  width: 100%;
  background: transparent;
  border: none;
  padding: 10px 14px 8px;
  color: var(--text-primary);
  font-size: 17px;
  resize: none;
  outline: none;
  max-height: 40vh;
  line-height: 1.5;
}

.input-area::placeholder {
  color: var(--text-dim);
}

.input-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px 10px;
}

.input-tools {
  display: flex;
  gap: 10px;
  align-items: center;
}

.input-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-shrink: 0;
}

.btn-send {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--accent);
  color: var(--white);
  border: none;
  font-size: 17px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  flex-shrink: 0;
  padding: 0;
}

.btn-send:hover { background: var(--accent-hover); }
.btn-send:disabled { opacity: 0.4; cursor: not-allowed; }

.attach-btn { font-size: 17px; }
.think-btn { font-size: 14px; }

/* ── 工具组胶囊按钮 ────────── */

.group-pill-wrap {
  display: flex;
  align-items: center;
}

.group-pill {
  height: 32px;
  border-radius: 16px 0 0 16px;
  padding: 0 4px 0 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-dim);
  background: transparent;
  border: 1px solid var(--border);
  border-right: none;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: color 0.15s, background 0.15s, border-color 0.15s;
}

.group-pill:hover {
  color: var(--text-secondary);
  background: var(--bg-hover);
  border-color: var(--text-dim);
}

.group-pill.on {
  color: var(--accent);
  border-color: var(--accent);
  background: var(--accent-bg);
}

.group-pill.on + .group-expand-btn {
  color: var(--accent);
  border-color: var(--accent);
  background: var(--accent-bg);
}

.group-pill.partial .group-dot { background: var(--accent); }

.group-expand-btn {
  height: 32px;
  width: 26px;
  border-radius: 0 16px 16px 0;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text-dim);
  background: transparent;
  border: 1px solid var(--border);
  border-left: none;
  flex-shrink: 0;
  font-size: 10px;
  transition: color 0.15s, background 0.15s, border-color 0.15s;
}

.group-expand-btn:hover {
  color: var(--text-secondary);
  background: var(--bg-hover);
  border-color: var(--text-dim);
}

.group-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--text-dim);
  flex-shrink: 0;
  transition: background 0.15s;
}

.group-dot.active { background: var(--accent); }

.group-name {
  font-size: 13px;
  line-height: 1;
}

.group-expand-icon {
  font-size: 10px;
}

.file-input { position: absolute; width: 0; height: 0; opacity: 0; pointer-events: none; }

.upload-previews { display: flex; gap: 6px; padding: 10px 14px 0; overflow-x: auto; flex-wrap: wrap; }

.upload-error {
  display: flex; align-items: center; justify-content: space-between;
  margin: 10px 10px 0;
  padding: 5px 10px;
  background: var(--error-bg);
  border: 1px solid var(--error-border);
  border-radius: 20px;
  font-size: 14px; color: var(--error);
}
.upload-error-close {
  background: none; border: none; color: var(--error);
  font-size: 14px; cursor: pointer; padding: 0 2px;
  opacity: 0.6;
}
.upload-error-close:hover { opacity: 1; }

.preview-item { position: relative; flex-shrink: 0; }
.preview-remove {
  position: absolute; top: -6px; right: -6px;
  width: 18px; height: 18px; border-radius: 50%;
  background: var(--bg-tertiary); border: 1px solid var(--border);
  color: var(--text-dim); font-size: 12px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}

/* 文档预览卡片 */
.preview-file-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  min-width: 120px;
  max-width: 200px;
  padding: 8px 10px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 10px;
  cursor: pointer;
}
.preview-file-card:hover { background: var(--bg-hover); }
.preview-file-icon {
  font-size: 21px;
  color: var(--accent);
  margin-bottom: 2px;
}
.preview-file-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}
.preview-file-text {
  font-size: 12px;
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
  line-height: 1.3;
}
</style>
