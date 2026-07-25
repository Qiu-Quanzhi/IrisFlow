<script setup lang="ts">
import { ref, computed, watch } from "vue";
import type { WorkflowEntry } from "../types/api";
import {
  UI_ABORTED_LABEL,
  UI_COMPLETED_LABEL,
  UI_PROCESSING_LABEL,
  UI_QUEUED_LABEL,
  UI_THINKING_LABEL,
  UI_THOUGHT_LABEL,
  WF_THINK,
  WF_TOOL_CALL,
} from "../constants";
import { getToolIcon } from "../composables/toolMetadata";

const props = withDefaults(defineProps<{
  entries?: WorkflowEntry[];
  aborted?: boolean;
  /** 是否排队等待调度 */
  queued?: boolean;
  /** 流是否已结束（连接关闭 / 完成 / 终止）。 */
  streamDone?: boolean;
  /** 是否已有正式输出内容（非思考、非工具调用）。 */
  hasContent?: boolean;
  /** 本轮对话是否启用了思考模式（后端权威）。 */
  thinking?: boolean;
}>(), {
  entries: () => [],
});

const emit = defineEmits<{
  select: [entry: WorkflowEntry];
}>();

const hasEntries = computed(() => props.entries.length > 0);

// ── 完工判定 ───────────────────────────────────────

/**
 * 工作流是否完工。
 * 完工标准：有正式输出（进入正文生成阶段）或流已结束。
 * 未完工 → 展开工作流日志；已完工 → 折叠。
 */
const isWorkDone = computed(() => props.hasContent || props.streamDone);

// ── 展开/折叠 ──────────────────────────────────────

const expanded = ref(!isWorkDone.value);

watch(isWorkDone, (done) => {
  // 完工 → 折叠；未完工 → 展开（含 resumeStream 把 streamDone 切回 false 的场景）
  expanded.value = !done;
});

// ── 工具计数 ───────────────────────────────────────

const toolCallCount = computed(() => props.entries.filter(e => e.type === WF_TOOL_CALL).length);

function entryIcon(entry: WorkflowEntry): string {
  if (entry.type === WF_THINK) return "fa-solid fa-lightbulb";
  if (entry.toolName) return getToolIcon(entry.toolName);
  return entry.type === WF_TOOL_CALL ? "fa-solid fa-wrench" : "fa-solid fa-inbox";
}

// ── 文案 ───────────────────────────────────────────

const summaryText = computed(() => {
  const firstThink = props.entries.find(e => e.type === WF_THINK);
  if (firstThink) return firstThink.text;
  if (toolCallCount.value) return `${toolCallCount.value} 次工具调用`;
  return "";
});

/** 标题：排队 → 队列中；终止 → 已终止；未完工 → 思考中/处理中；已完工 → 已思考/已完成。 */
const headerLabel = computed(() => {
  if (props.queued) return UI_QUEUED_LABEL;
  if (props.aborted) return UI_ABORTED_LABEL;
  if (!isWorkDone.value) return props.thinking ? UI_THINKING_LABEL : UI_PROCESSING_LABEL;
  return props.thinking ? UI_THOUGHT_LABEL : UI_COMPLETED_LABEL;
});
</script>

<template>
  <div class="workflow-log">
    <div
      class="wf-header"
      :class="{ clickable: hasEntries }"
      @click="hasEntries && (expanded = !expanded)"
    >
      <i
        class="wf-header-icon"
        :class="queued ? 'fa-solid fa-spinner fa-spin' : aborted ? 'fa-solid fa-ban' : (thinking ? 'fa-solid fa-bolt' : 'fa-solid fa-feather-pointed')"
      ></i>
      <span class="wf-header-text">{{ headerLabel }}</span>
      <i v-if="hasEntries" class="wf-toggle fa-solid" :class="expanded ? 'fa-chevron-down' : 'fa-chevron-right'"></i>
      <span v-if="!expanded && summaryText" class="wf-header-preview">{{ summaryText }}</span>
    </div>
    <div v-if="hasEntries && expanded" class="wf-body">
      <div
        v-for="(entry, i) in entries"
        :key="i"
        class="wf-entry"
        :class="{ clickable: entry.type !== WF_THINK }"
        @click="entry.type !== WF_THINK && emit('select', entry)"
      >
        <div class="wf-left">
          <i class="wf-entry-icon" :class="[entryIcon(entry), { 'wf-entry-icon--error': entry.isError }]"></i>
          <div class="wf-connector"></div>
        </div>
        <span class="wf-entry-text" :class="{ 'wf-entry-text--error': entry.isError }">{{ entry.text }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workflow-log {
  margin: 4px 0;
  padding: 0 4px;
  font-size: 14px;
  line-height: 1.7;
}

.wf-header {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--text-dim);
  padding: 2px 0;
  user-select: none;
}

.wf-header.clickable {
  cursor: pointer;
}

.wf-header.clickable:hover {
  color: var(--text-secondary);
}

.wf-header-icon {
  font-size: 17px;
}

.wf-header-text {
  font-size: 14px;
  font-weight: 600;
}

.wf-header-preview {
  font-size: 14px;
  opacity: 0.7;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
  margin-left: auto;
}

.wf-toggle {
  font-size: 12px;
}

/* ── 展开体 ──────────────────────────────────────── */

.wf-body {
  position: relative;
}

/* ── 条目 ────────────────────────────────────────── */

.wf-entry {
  display: flex;
  align-items: baseline;
  gap: 4px;
  color: var(--text-secondary);
  border-radius: var(--radius-sm);
  position: relative;
}

.wf-entry.clickable {
  cursor: pointer;
}

.wf-entry.clickable:hover {
  color: var(--text-primary);
}

/* ── 左列：图标 + 连接线 ─────────────────────────── */

.wf-left {
  flex-shrink: 0;
}

.wf-entry-icon {
  font-size: 14px;
  line-height: 1;
  width: 15px;
  text-align: center;
  position: relative;
}

/* 连接线：从图标下方延至条目底（图标 14px + 行高间距 ≈ 27px） */
.wf-connector {
  position: absolute;
  top: 27px;
  bottom: 0;
  left: 7px;   /* wf-left 15px 宽的中心 */
  border: 1.25px solid var(--border);
}

/* ── 右列：文本 ──────────────────────────────────── */

.wf-entry-text {
  white-space: pre-wrap;
  word-break: break-word;
  padding: 1px 0;
}

.wf-entry-text--error {
  color: var(--error);
}

.wf-entry-icon--error {
  color: var(--error);
}
</style>
