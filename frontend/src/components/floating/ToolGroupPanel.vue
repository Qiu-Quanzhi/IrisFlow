<script setup lang="ts">
import { computed } from "vue";
import FloatingWindow from "./FloatingWindow.vue";
import { getToolDisplay } from "../../composables/toolMetadata";
import { UI_ON, UI_OFF } from "../../constants";

const props = defineProps<{
  modelValue: boolean;
  groupName: string;
  toolNames: string[];
  enabledBuiltins: string[];
}>();

const emit = defineEmits<{
  "update:modelValue": [value: boolean];
  close: [];
  toggleTool: [name: string];
}>();

const enabledCount = computed(() =>
  props.toolNames.filter(n => props.enabledBuiltins.includes(n)).length
);
</script>

<template>
  <FloatingWindow
    width="320px"
    :title="groupName"
    icon="fa-solid fa-screwdriver-wrench"
    position="bottom-left"
    :model-value="modelValue"
    @update:model-value="emit('update:modelValue', $event)"
    @close="emit('close')"
  >
    <div class="tgp-body">
      <p class="tgp-summary">
        已启用 {{ enabledCount }} / {{ toolNames.length }} 个工具
      </p>
      <div class="tgp-tools">
        <button
          v-for="toolName in toolNames"
          :key="toolName"
          class="tgp-tool-btn"
          :class="{ on: enabledBuiltins.includes(toolName) }"
          @click="emit('toggleTool', toolName)"
        >
          <i class="tgp-tool-icon" :class="getToolDisplay(toolName).icon"></i>
          <div class="tgp-tool-info">
            <span class="tgp-tool-label">{{ getToolDisplay(toolName).label }}</span>
            <span class="tgp-tool-name">{{ toolName }}</span>
          </div>
          <span class="tgp-tool-state">{{ enabledBuiltins.includes(toolName) ? UI_ON : UI_OFF }}</span>
        </button>
      </div>
    </div>
  </FloatingWindow>
</template>

<style scoped>
.tgp-body {
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tgp-summary {
  margin: 0;
  font-size: 13px;
  color: var(--text-dim);
}

.tgp-tools {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tgp-tool-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 10px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text-dim);
  font-size: 13px;
  cursor: pointer;
  transition: color 0.15s, background 0.15s, border-color 0.15s;
  text-align: left;
}

.tgp-tool-btn:hover {
  color: var(--text-secondary);
  background: var(--bg-hover);
  border-color: var(--text-dim);
}

.tgp-tool-btn.on {
  color: var(--text-primary);
  border-color: var(--accent);
  background: var(--accent-bg);
}

.tgp-tool-icon {
  font-size: 16px;
  width: 20px;
  text-align: center;
  flex-shrink: 0;
}

.tgp-tool-icon.on { color: var(--accent); }

.tgp-tool-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.tgp-tool-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  line-height: 1.3;
}

.tgp-tool-name {
  font-size: 11px;
  color: var(--text-dim);
  font-family: var(--font-mono);
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tgp-tool-state {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-dim);
  flex-shrink: 0;
}

.tgp-tool-btn.on .tgp-tool-state { color: var(--accent); }
</style>
