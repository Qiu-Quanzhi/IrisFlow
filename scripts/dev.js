/** dev 模式 — 灵活端口 + 前后端并行启动 + 健康检查 */

const { spawn } = require("child_process");
const path = require("path");
const { findPort } = require("./find-port");

const ROOT = path.join(__dirname, "..");
const PORTS_FILE = path.join(ROOT, ".ports.json");
const BACKEND_READY_TIMEOUT = 30000;  // 30s
const BACKEND_POLL_INTERVAL = 300;   // ms

// ── 行缓冲前缀输出 ──────────────────────────────

/**
 * 将可读流的输出逐行加上彩色前缀，写入目标流。
 * 处理跨 chunk 的行分割，避免前缀插入行中间导致输出乱码。
 */
function prefixStream(stream, dest, label, colorCode) {
  const p = `\x1b[${colorCode}m[${label}]\x1b[0m `;
  let buf = "";
  stream.on("data", (chunk) => {
    buf += chunk.toString();
    const lines = buf.split("\n");
    buf = lines.pop();  // 最后一行可能不完整，保留待下一 chunk 拼接
    for (const line of lines) dest.write(p + line + "\n");
  });
  stream.on("end", () => {
    if (buf) dest.write(p + buf + "\n");
  });
}

// ── 就绪轮询 ────────────────────────────────────

async function waitForBackend(port, timeoutMs) {
  const url = `http://127.0.0.1:${port}/api/ping`;
  const deadline = Date.now() + timeoutMs;
  let lastError = "";

  while (Date.now() < deadline) {
    try {
      const resp = await fetch(url, { signal: AbortSignal.timeout(2000) });
      const data = await resp.json();
      if (data && data.ok === true) return;
      lastError = `HTTP ${resp.status}: ${JSON.stringify(data)}`;
    } catch (e) {
      lastError = e.message || String(e);
    }
    await new Promise((r) => setTimeout(r, BACKEND_POLL_INTERVAL));
  }
  throw new Error(`后端 ${url} 未在 ${timeoutMs}ms 内就绪\n最后错误: ${lastError}`);
}

// ── 进程管理 ────────────────────────────────────

function spawnBackend(port) {
  const child = spawn(
    `uv run uvicorn main:app --reload --host 0.0.0.0 --port ${port}`,
    { cwd: path.join(ROOT, "backend"), stdio: "pipe", shell: true }
  );
  child.on("error", (err) => { console.error(`\n❌ 后端进程启动失败: ${err.message}`); process.exit(1); });
  return child;
}

function spawnFrontend(port) {
  const child = spawn(
    "pnpm dev",
    { cwd: path.join(ROOT, "frontend"), stdio: "pipe", shell: true }
  );
  child.on("error", (err) => { console.error(`\n❌ 前端进程启动失败: ${err.message}`); process.exit(1); });
  return child;
}

// ── 主函数 ──────────────────────────────────────

async function dev() {
  // 1. 找空闲端口
  console.log("\n🔍 探测可用端口…");
  const backendPort = await findPort(8000, { host: "0.0.0.0" });
  console.log(`✅ 后端端口: ${backendPort}`);

  // 写入 .ports.json 供 vite.config.ts 读取
  const fs = require("fs");
  let portsData = {};
  try { portsData = JSON.parse(fs.readFileSync(PORTS_FILE, "utf-8")); } catch {}
  portsData.backend = backendPort;
  fs.writeFileSync(PORTS_FILE, JSON.stringify(portsData, null, 2) + "\n");

  // 2. 启动后端
  let backend = spawnBackend(backendPort);
  prefixStream(backend.stdout, process.stdout, "backend", "34");
  prefixStream(backend.stderr, process.stderr, "backend", "34");

  // 3. 等待后端就绪（健康检查轮询）
  console.log("⏳ 等待后端就绪…");
  await waitForBackend(backendPort, BACKEND_READY_TIMEOUT);
  console.log("✅ 后端就绪");

  // 4. 启动前端
  const frontend = spawnFrontend(3000);
  prefixStream(frontend.stdout, process.stdout, "frontend", "32");
  prefixStream(frontend.stderr, process.stderr, "frontend", "32");

  // 5. 生命周期管理
  let exiting = false;
  const cleanup = () => {
    if (exiting) return;
    exiting = true;
    console.log("\n🛑 正在关闭…");
    try { backend.kill(); } catch {}
    try { frontend.kill(); } catch {}
    setTimeout(() => process.exit(0), 500);
  };

  // Unix 信号
  process.on("SIGINT", cleanup);
  process.on("SIGTERM", cleanup);
  // Windows: Ctrl+C 在 cmd/PowerShell 中可能不发送 SIGINT
  if (process.platform === "win32") {
    const rl = require("readline").createInterface({ input: process.stdin, output: process.stdout });
    rl.on("SIGINT", () => process.emit("SIGINT", "SIGINT"));
  }
  // 兜底：进程退出时强制清理
  process.on("exit", () => {
    try { backend.kill(); } catch {}
    try { frontend.kill(); } catch {}
  });

  // 子进程异常退出处理
  backend.on("exit", (code) => {
    if (!exiting) {
      console.error(`\n❌ 后端意外退出 (exit code: ${code})`);
      cleanup();
    }
  });
  frontend.on("exit", (code) => {
    if (!exiting) {
      console.error(`\n❌ 前端意外退出 (exit code: ${code})`);
      cleanup();
    }
  });
}

dev().catch((err) => { console.error(err); process.exit(1); });
