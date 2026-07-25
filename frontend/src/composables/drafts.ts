/** 会话草稿共享内存存储 —— 页面刷新后消失，不持久化到 localStorage。
 *  注意：会话参数（SessionSettings）不属于草稿，它由后端权威持久化。
 */

import { reactive } from "vue";
import type { FileAttachment } from "../types/api";

export interface DraftData {
  text?: string;
  files?: FileAttachment[];
  thinking?: boolean;
  enabledBuiltins?: string[];
}

/** 按 session_id（或 DRAFT_NEW）索引的草稿映射 */
export const draftStore = reactive<Record<string, DraftData>>({});
