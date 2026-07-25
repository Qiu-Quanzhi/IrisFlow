/** 工具元数据响应式存储。

后端是工具信息的唯一权威来源（GET /api/tools）。
前端不做任何硬编码，所有图标、标签、排序均从 API 获取。
MCP 工具在后端注册时获得默认元数据，前端无需区分来源。

同时提供 discoverTools() 模块级函数，供 ChatPanel（挂载时）、
SettingsPanel（MCP 重载后）等跨兄弟组件调用，解决 provide/inject
在 Teleport 兄弟组件间无法传递的问题。
*/

import { ref } from "vue";
import { getServerUrl, BASE, PATH_TOOLS } from "../api/client";
import type { ToolInfo } from "../types/api";

/** 名称 → 元数据映射，由 discoverTools() 填充 */
export const toolMetaMap = ref<Record<string, ToolInfo>>({});

/** MCP 服务器 → 工具名列表（供前端分组渲染工具按钮） */
export const toolGroups = ref<Record<string, string[]>>({});

/** 从后端获取工具列表并更新 toolMetaMap 和 toolGroups。 */
export async function discoverTools(): Promise<void> {
  try {
    const resp = await fetch(`${getServerUrl()}${BASE}${PATH_TOOLS}`);
    if (!resp.ok) return;
    const data: {
      tools: ToolInfo[];
      groups: Record<string, string[]>;
    } = await resp.json();
    const map: Record<string, ToolInfo> = {};
    for (const t of data.tools) {
      map[t.name] = t;
    }
    toolMetaMap.value = map;
    toolGroups.value = data.groups || {};
  } catch {
    /* 后端未运行或接口不存在时静默忽略 */
  }
}

export function getToolInfo(name: string): ToolInfo | undefined {
  return toolMetaMap.value[name];
}

export function getToolIcon(name: string): string {
  return toolMetaMap.value[name]?.icon ?? "fa-solid fa-wrench";
}

export function getToolLabel(name: string): string {
  return toolMetaMap.value[name]?.label ?? name;
}

export function getToolDisplay(name: string): { icon: string; label: string } {
  const info = getToolInfo(name);
  if (info) return { icon: info.icon, label: info.label };
  return { icon: "fa-solid fa-puzzle-piece", label: name };
}
