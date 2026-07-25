<script setup lang="ts">
import { ref, watch, computed, onMounted, onUnmounted, nextTick } from "vue";
import { UI_CLOSE, UI_PIN, UI_UNPIN } from "../../constants";
import { register, unregister, focusWindow, setVisible } from "../../composables/windowZIndex";

type Position = "center" | "top" | "bottom" | "left" | "right"
  | "top-left" | "top-right" | "bottom-left" | "bottom-right";

const GAP = "16px";

const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    width?: string;
    title?: string;
    icon?: string;
    position?: Position;
  }>(),
  {
    modelValue: false,
    width: "420px",
    title: "",
    icon: "",
    position: "center",
  },
);

const emit = defineEmits<{
  "update:modelValue": [value: boolean];
  close: [];
}>();

// ── z-index / 置顶 ────────────────────────────

const myKey = Symbol();
const PINNED_Z = 9999;
const pinned = ref(false);
const zIndex = ref(200);

function setZ(z: number) {
  if (!pinned.value) zIndex.value = z;
}

function bringToFront() {
  if (pinned.value) return;
  focusWindow(myKey);
}

function togglePin() {
  pinned.value = !pinned.value;
  if (pinned.value) {
    zIndex.value = PINNED_Z;
  } else {
    focusWindow(myKey);
  }
}

// ── 初始位置 ──────────────────────────────────

const posStyle = computed<Record<string, string>>(() => {
  const s: Record<string, string> = {};
  switch (props.position) {
    case "center":      s.left = "50%"; s.top = "50%"; s.transform = "translate(-50%, -50%)"; break;
    case "top":         s.left = "50%"; s.top = GAP;   s.transform = "translateX(-50%)"; break;
    case "bottom":      s.left = "50%"; s.bottom = GAP; s.transform = "translateX(-50%)"; break;
    case "left":        s.left = GAP;   s.top = "50%"; s.transform = "translateY(-50%)"; break;
    case "right":       s.right = GAP;  s.top = "50%"; s.transform = "translateY(-50%)"; break;
    case "top-left":    s.left = GAP;   s.top = GAP;   break;
    case "top-right":   s.right = GAP;  s.top = GAP;   break;
    case "bottom-left": s.left = GAP;   s.bottom = GAP; break;
    case "bottom-right":s.right = GAP;  s.bottom = GAP; break;
  }
  return s;
});

function applyPosStyle(el: HTMLElement) {
  const s = posStyle.value;
  el.style.left = s.left ?? "";
  el.style.top = s.top ?? "";
  el.style.right = s.right ?? "";
  el.style.bottom = s.bottom ?? "";
  el.style.transform = s.transform ?? "";
}

// ── 显示/隐藏 ──────────────────────────────────

const ANIM_DURATION = 180; // 与 CSS transition 时长一致（ms）

const show = ref(false);
const closing = ref(false);
const panelEl = ref<HTMLElement | null>(null);

function close() {
  if (closing.value) return;
  closing.value = true;
  show.value = false; // 触发退出动画
  setTimeout(() => {
    // 动画完成后才通知父组件，避免 v-if 销毁导致动画被截断
    closing.value = false;
    emit("update:modelValue", false);
    emit("close");
  }, ANIM_DURATION);
}

watch(
  () => props.modelValue,
  async (val) => {
    if (closing.value) return; // close() 正在处理，忽略外部变化
    setVisible(myKey, val);
    if (val) {
      bringToFront();
      // 延迟一帧：确保元素先以隐藏态渲染，CSS transition 才能触发
      await nextTick();
      show.value = true;
      await nextTick();
      clampToViewport();
    } else {
      show.value = false;
    }
  },
);

// ── 初始定位（onMounted 时 panelEl 已就绪）────

onMounted(() => {
  register(myKey, setZ, close);
  if (props.modelValue) setVisible(myKey, true);
  applyPosStyle(panelEl.value!);
  if (props.modelValue) {
    // 延迟到下一帧再显示：首次渲染不带 --show，然后触发入场动画
    requestAnimationFrame(() => {
      show.value = true;
      bringToFront();
    });
  }
  window.addEventListener("resize", clampToViewport);
  document.addEventListener("mousedown", onDocMouseDown);
});

onUnmounted(() => {
  unregister(myKey);
  window.removeEventListener("resize", clampToViewport);
  document.removeEventListener("mousedown", onDocMouseDown);
  document.removeEventListener("mousemove", onMouseMove);
  document.removeEventListener("mouseup", onMouseUp);
});

// ── 聚焦置顶（document mousedown + contains）───

function onDocMouseDown(e: MouseEvent) {
  if (show.value && panelEl.value?.contains(e.target as HTMLElement)) {
    bringToFront();
  }
}

// ── 拖动 ───────────────────────────────────────

const dragging = ref(false);

interface DragState {
  startMouseX: number;
  startMouseY: number;
  startPanelX: number;
  startPanelY: number;
}

let _drag: DragState | null = null;

function onHeaderMouseDown(e: MouseEvent) {
  if (!panelEl.value) return;
  const rect = panelEl.value.getBoundingClientRect();
  dragging.value = true;
  panelEl.value.style.left = `${rect.left}px`;
  panelEl.value.style.top = `${rect.top}px`;
  panelEl.value.style.right = "";
  panelEl.value.style.bottom = "";
  panelEl.value.style.transform = "none";
  _drag = {
    startMouseX: e.clientX,
    startMouseY: e.clientY,
    startPanelX: rect.left,
    startPanelY: rect.top,
  };
  document.addEventListener("mousemove", onMouseMove);
  document.addEventListener("mouseup", onMouseUp);
}

function onMouseMove(e: MouseEvent) {
  if (!_drag || !panelEl.value) return;
  const dx = e.clientX - _drag.startMouseX;
  const dy = e.clientY - _drag.startMouseY;
  panelEl.value.style.left = `${_drag.startPanelX + dx}px`;
  panelEl.value.style.top = `${_drag.startPanelY + dy}px`;
}

function onMouseUp() {
  _drag = null;
  dragging.value = false;
  document.removeEventListener("mousemove", onMouseMove);
  document.removeEventListener("mouseup", onMouseUp);
}

// ── 视口边界约束（窗口 resize 后拉回可见区域）─────

const MIN_VISIBLE = 60;

function clampToViewport() {
  if (!panelEl.value || !show.value) return;
  const rect = panelEl.value.getBoundingClientRect();
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  let left = rect.left;
  let top = rect.top;

  if (left > vw - MIN_VISIBLE) left = vw - MIN_VISIBLE;
  if (left + rect.width < MIN_VISIBLE) left = MIN_VISIBLE - rect.width;
  if (top > vh - MIN_VISIBLE) top = vh - MIN_VISIBLE;
  if (top + rect.height < MIN_VISIBLE) top = MIN_VISIBLE - rect.height;

  if (left !== rect.left || top !== rect.top) {
    panelEl.value.style.left = `${left}px`;
    panelEl.value.style.top = `${top}px`;
    panelEl.value.style.right = "";
    panelEl.value.style.bottom = "";
    panelEl.value.style.transform = "none";
  }
}

</script>

<template>
  <Teleport to="body">
    <div
      ref="panelEl"
      class="fw-panel"
      :class="{ 'fw-panel--show': show, 'fw-panel--pinned': pinned, 'fw-panel--dragging': dragging }"
      :style="{ width, zIndex }"
    >
      <div class="fw-inner" :class="{ 'fw-inner--show': show }">
        <!-- 头部（拖动手柄） -->
        <div
          class="fw-header"
          @mousedown="onHeaderMouseDown"
          @mousedown.middle.prevent="close"
        >
          <slot name="header">
            <span class="fw-title">
              <i v-if="icon" :class="[icon, 'fw-title-icon']" />
              {{ title }}
            </span>
          </slot>
          <div class="fw-actions">
            <slot name="actions" />
            <button
              class="btn-icon fw-pin-btn"
              :class="{ on: pinned }"
              @click.stop="togglePin"
              :title="pinned ? UI_UNPIN : UI_PIN"
            >
              <i class="fa-solid fa-thumbtack" />
            </button>
            <button class="btn-icon fw-close-btn" @click.stop="close" :title="UI_CLOSE">
              <i class="fa-solid fa-xmark" />
            </button>
          </div>
        </div>

        <!-- 主体 -->
        <div class="fw-body">
          <slot />
        </div>

        <!-- 底部（可选） -->
        <div v-if="$slots.footer" class="fw-footer">
          <slot name="footer" />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* ═══════════════════════════════════════════════════
   浮窗面板（外层：定位 + 显隐）
   ═══════════════════════════════════════════════════ */

.fw-panel {
  --fw-shadow: var(--shadow-md);
  --fw-glow: 0 0 12px var(--accent-strong);

  position: fixed;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  pointer-events: none;

  /* 状态 */
  &.fw-panel--show { pointer-events: auto; }
  &.fw-panel--pinned {
    .fw-inner {
      border-color: var(--accent);
      box-shadow: var(--fw-shadow), var(--fw-glow);
    }
  }
}

/* ═══════════════════════════════════════════════════
   浮窗内层（承载所有可见样式 + 弹出动画）
   ═══════════════════════════════════════════════════ */

.fw-inner {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--fw-shadow);
  overflow: hidden;
  transform: scale(0.97);
  opacity: 0;
  transition: transform 0.18s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.15s ease;

  &.fw-inner--show {
    transform: scale(1);
    opacity: 1;
  }
}

/* ═══════════════════════════════════════════════════
   头部
   ═══════════════════════════════════════════════════ */

.fw-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px 8px 14px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  cursor: grab;
  user-select: none;

  &:active { cursor: grabbing; }
}

.fw-title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.fw-title-icon {
  font-size: 14px;
  color: var(--accent);
}

/* ═══════════════════════════════════════════════════
   头部操作按钮
   ═══════════════════════════════════════════════════ */

.fw-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

/* 置顶 — 主题色 */
.fw-pin-btn {
  &.on {
    color: var(--accent);
    border-color: var(--accent);
    background: var(--accent-bg);
  }
  &:hover {
    color: var(--accent);
    border-color: var(--accent);
    background: var(--accent-bg);
  }
  &:active {
    color: var(--white);
    background: var(--accent);
    border-color: var(--accent);
  }
}

/* 关闭 — 红色系 */
.fw-close-btn {
  &:hover {
    color: var(--error);
    border-color: var(--error);
    background: var(--error-bg-hover);
  }
  &:active {
    color: var(--white);
    background: var(--error);
    border-color: var(--error);
  }
}

/* ═══════════════════════════════════════════════════
   主体 & 底部
   ═══════════════════════════════════════════════════ */

.fw-body {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.fw-footer {
  padding: 10px 14px;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}

</style>
