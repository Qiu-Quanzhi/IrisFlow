/** provide / inject 键 — 类型化 Symbol，防止拼写错误与类型不匹配。 */

import type { InjectionKey } from "vue";

export const ON_CONNECTION_LOST_KEY: InjectionKey<() => void> = Symbol("on-connection-lost");
export const REMOVE_SESSION_CACHE_KEY: InjectionKey<(id: string) => void> = Symbol("remove-session-cache");
export const REFRESH_CONVERSATION_LIST_KEY: InjectionKey<() => void> = Symbol("refresh-conversation-list");
export const REFRESH_DEFAULT_SETTINGS_KEY: InjectionKey<() => Promise<void>> = Symbol("refresh-default-settings");
