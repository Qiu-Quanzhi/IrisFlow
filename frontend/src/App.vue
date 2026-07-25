<script setup lang="ts">
import { ref, onMounted, onUnmounted, provide, defineAsyncComponent } from "vue";
import ChatPanel from "./components/ChatPanel.vue";

const ConversationList = defineAsyncComponent(() => import("./components/floating/ConversationList.vue"));
const WorkflowDetail = defineAsyncComponent(() => import("./components/floating/WorkflowDetail.vue"));
const MediaPreview = defineAsyncComponent(() => import("./components/floating/MediaPreview.vue"));
const SettingsPanel = defineAsyncComponent(() => import("./components/floating/SettingsPanel.vue"));
import { getLLMConfig, ping } from "./api/client";
import { HEARTBEAT_INTERVAL, TOOL_REFRESH_INTERVAL, WF_TOOL_CALL, WF_TOOL_RESULT, UI_CONNECTION_LOST, UI_AUTO_RECOVER, UI_SESSION_LIST, UI_SETTINGS } from "./constants";
import { ON_CONNECTION_LOST_KEY, REFRESH_CONVERSATION_LIST_KEY, REMOVE_SESSION_CACHE_KEY } from "./composables/injectionKeys";
import { discoverTools } from "./composables/toolMetadata";
import { loadMd } from "./utils/markdown-lazy";
import type { WorkflowEntry, PreviewPayload } from "./types/api";

const model = ref("");
const showSettings = ref(false);
const chatPanelRef = ref<InstanceType<typeof ChatPanel> | null>(null);
const conversationListRef = ref<InstanceType<typeof ConversationList> | null>(null);

// ── 持久浮窗（v-model 驱动，纯内存）───────────

const showConversationList = ref(true);  // 默认显示

// ── 动态窗管理体系 ────────────────────────────
// 点击即创建，关闭即销毁。同类可并行多开。

type PanelType = 'tool-call' | 'tool-result' | 'think' | 'media';

interface PanelWindow {
  id: number;
  type: PanelType;
  visible: boolean;
  data: WorkflowEntry | PreviewPayload;
}

let _nextPanelId = 0;
const panels = ref<PanelWindow[]>([]);

function createPanel(type: PanelType, data: WorkflowEntry | PreviewPayload) {
  panels.value.push({ id: ++_nextPanelId, type, visible: true, data });
}

function closePanel(id: number) {
  const p = panels.value.find(p => p.id === id);
  if (!p) return;
  p.visible = false;  // 触发隐藏动画
  setTimeout(() => {
    panels.value = panels.value.filter(p => p.id !== id);
  }, 250);
}

function toPanelType(entry: WorkflowEntry): PanelType {
  if (entry.type === WF_TOOL_CALL) return 'tool-call';
  if (entry.type === WF_TOOL_RESULT) return 'tool-result';
  return 'think';
}

function onSelectEntry(entry: WorkflowEntry | null) {
  if (entry) createPanel(toPanelType(entry), entry);
}

function onPreview(payload: PreviewPayload) {
  createPanel('media', payload);
}

// ── 模板内类型窄化辅助 ──────────────────────────

function wfEntry(data: WorkflowEntry | PreviewPayload): WorkflowEntry {
  return data as WorkflowEntry;
}
function mpPayload(data: WorkflowEntry | PreviewPayload): PreviewPayload {
  return data as PreviewPayload;
}

// ── 断联占屏 + 心跳（3s 周期：失败 → 占屏，恢复 → 刷新）──

const connectionLost = ref(false);
let _timer: ReturnType<typeof setInterval> | null = null;
let _toolTimer: ReturnType<typeof setInterval> | null = null;

function onConnectionLost() {
  connectionLost.value = true;
}

async function heartbeatTick() {
  try {
    await ping();
    if (connectionLost.value) window.location.reload();
  } catch {
    onConnectionLost();
  }
}

function startHeartbeat() {
  if (_timer) clearInterval(_timer);
  heartbeatTick();  // 启动时立即检测一次
  _timer = setInterval(heartbeatTick, HEARTBEAT_INTERVAL);
}

// ── 跨组件通信 ────────────────────────────────────

provide(REMOVE_SESSION_CACHE_KEY, (id: string) => {
  chatPanelRef.value?.removeSession(id);
});
provide(REFRESH_CONVERSATION_LIST_KEY, () => {
  conversationListRef.value?.refresh();
});
provide(ON_CONNECTION_LOST_KEY, onConnectionLost);

// ── 初始化 ─────────────────────────────────────────

getLLMConfig().then(cfg => { model.value = cfg.default_model || ""; }).catch(() => { model.value = ""; });

onMounted(() => {
  startHeartbeat();
  // 后台定期刷新 MCP 工具列表（覆盖健康检查自动重连等非手动触发场景）
  _toolTimer = setInterval(discoverTools, TOOL_REFRESH_INTERVAL);
  // 预热 markdown 渲染管线，避免首条消息出现纯文本→富文本闪烁
  loadMd();
});

onUnmounted(() => {
  if (_timer) clearInterval(_timer);
  if (_toolTimer) clearInterval(_toolTimer);
});

function handleUpdateSettings(cfg: { model: string }) {
  model.value = cfg.model;
}

// ── 单例窗口显现（不可重复创建）───────────────

function showWindow(type: 'conversations' | 'settings') {
  if (type === 'conversations') showConversationList.value = true;
  else showSettings.value = true;
}
</script>

<template>
  <div class="app-layout">
    <main class="main-area">
      <ChatPanel
        ref="chatPanelRef"
        :model="model"
        @select-entry="onSelectEntry"
        @preview="onPreview"
      />
    </main>

    <SettingsPanel
      v-model="showSettings"
      @update="handleUpdateSettings"
    />
  </div>

  <!-- 会话浮岛（持久：关闭仅隐藏不销毁，默认显示） -->
  <ConversationList
    ref="conversationListRef"
    v-model="showConversationList"
  />

  <!-- 动态窗（点击即创建，可并行多开） -->
  <template v-for="panel in panels" :key="panel.id">
    <WorkflowDetail
      v-if="panel.type === 'tool-call' || panel.type === 'tool-result' || panel.type === 'think'"
      v-model="panel.visible"
      :entry="wfEntry(panel.data)"
      @close="closePanel(panel.id)"
    />
    <MediaPreview
      v-else-if="panel.type === 'media'"
      v-model="panel.visible"
      :payload="mpPayload(panel.data)"
      @close="closePanel(panel.id)"
    />
  </template>

  <!-- 浮岛切换按钮（左上角） -->
  <button
    class="circle-btn-lg floating-toggle floating-toggle--tl"
    @click="showWindow('conversations')"
    :title="UI_SESSION_LIST"
  >
    <i class="fa-solid fa-bars"></i>
  </button>

  <!-- 设置按钮（右上角） -->
  <button
    class="circle-btn-lg floating-toggle floating-toggle--tr"
    @click="showWindow('settings')"
    :title="UI_SETTINGS"
  >
    <i class="fa-solid fa-gear"></i>
  </button>

  <!-- 断联占屏：心跳每 3s 自动重试，恢复后自动刷新 -->
  <div v-if="connectionLost" class="conn-lost-overlay">
    <div class="conn-lost-card">
      <i class="fa-solid fa-plug-circle-xmark conn-lost-icon"></i>
      <p class="conn-lost-msg">{{ UI_CONNECTION_LOST }}</p>
      <p class="conn-lost-hint">{{ UI_AUTO_RECOVER }}</p>
    </div>
  </div>
</template>

<style scoped>
/* ═══════════════════════════════════════════════════
   布局
   ═══════════════════════════════════════════════════ */

.app-layout {
  display: flex;
  height: 100%;
  overflow-x: hidden;
}

.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
}

/* ═══════════════════════════════════════════════════
   浮动切换按钮
   ═══════════════════════════════════════════════════ */

.floating-toggle {
  position: fixed;
  z-index: 150;
  font-size: 14px;

  &:active {
    color: var(--text-primary);
    background: var(--bg-tertiary);
    border-color: var(--accent);
  }

  &.floating-toggle--tl { top: 12px; left: 12px; }
  &.floating-toggle--tr { top: 12px; right: 12px; }
}

/* ═══════════════════════════════════════════════════
   断联占屏
   ═══════════════════════════════════════════════════ */

.conn-lost-overlay {
  position: fixed; inset: 0; z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--bg-primary) 92%, transparent);
  backdrop-filter: blur(4px);
}

.conn-lost-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.conn-lost-icon {
  font-size: 56px;
  color: var(--error);
  margin-bottom: 20px;
}

.conn-lost-msg {
  font-size: 18px; font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 8px;
}

.conn-lost-hint {
  font-size: 14px;
  color: var(--text-dim);
}

.conn-lost-input {
  width: 280px;
  margin-top: 12px;
  padding: 8px 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text-primary);
  font-size: 14px;
  font-family: var(--font-mono);
  text-align: center;
  outline: none;
}
.conn-lost-input:focus { border-color: var(--accent); }
</style>
