/** FloatingWindow z-index 管理层 — 四档活跃 + 不活跃 + 全局 Escape 仅关顶层 */

const Z = [204, 203, 202, 201, 200];

interface PanelEntry {
  tick: number;
  setZ: (z: number) => void;
  close: () => void;
  visible: boolean;
}

const _registry = new Map<symbol, PanelEntry>();
let _tick = 0;
let _keydownInited = false;

function syncAllZ() {
  const sorted = [..._registry.entries()]
    .sort((a, b) => b[1].tick - a[1].tick);
  sorted.forEach(([, p], i) => p.setZ(i < 4 ? Z[i] : Z[4]));
}

/** 返回当前最高 tick 的可见条目，用于 Escape 关闭 */
function topEntry(): PanelEntry | undefined {
  let best: PanelEntry | undefined;
  let bestTick = -1;
  for (const [, e] of _registry) {
    if (e.visible && e.tick > bestTick) { best = e; bestTick = e.tick; }
  }
  return best;
}

function initKeydown() {
  if (_keydownInited) return;
  _keydownInited = true;
  window.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.key !== "Escape") return;
    const top = topEntry();
    if (top) top.close();
  });
}

export function register(key: symbol, setZ: (z: number) => void, close: () => void) {
  _registry.set(key, { tick: 0, setZ, close, visible: false });
  initKeydown();
}

export function setVisible(key: symbol, visible: boolean) {
  const entry = _registry.get(key);
  if (!entry) return;
  entry.visible = visible;
}

export function unregister(key: symbol) {
  _registry.delete(key);
  syncAllZ();
}

export function focusWindow(key: symbol) {
  const entry = _registry.get(key);
  if (!entry) return;
  entry.tick = ++_tick;
  syncAllZ();
}
