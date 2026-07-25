/** start 模式 — 构建前端 + 启动后端（单端口 serve） */

const { spawn } = require("child_process");
const path = require("path");
const { findPort } = require("./find-port");

const ROOT = path.join(__dirname, "..");
const PORTS_FILE = path.join(ROOT, ".ports.json");

// ── 行缓冲前缀输出 ──────────────────────────────

function prefixStream(stream, dest, label, colorCode) {
  const p = `\x1b[${colorCode}m[${label}]\x1b[0m `;
  let buf = "";
  stream.on("data", (chunk) => {
    buf += chunk.toString();
    const lines = buf.split("\n");
    buf = lines.pop();
    for (const line of lines) dest.write(p + line + "\n");
  });
  stream.on("end", () => {
    if (buf) dest.write(p + buf + "\n");
  });
}

// ── 就绪轮询 ────────────────────────────────────

async function waitForBackend(port, timeoutMs = 30000) {
  const url = `http://127.0.0.1:${port}/api/ping`;
  const deadline = Date.now() + timeoutMs;
  let lastError = "";

  while (Date.now() < deadline) {
    try {
      const resp = await fetch(url, { signal: AbortSignal.timeout(2000) });
      const data = await resp.json();
      if (data && data.ok === true) return;
      lastError = `HTTP ${resp.status}`;
    } catch (e) {
      lastError = e.message || String(e);
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`后端未在 ${timeoutMs}ms 内就绪\n最后错误: ${lastError}`);
}

// ── 主函数 ──────────────────────────────────────

async function start() {
  // 1. 构建前端
  console.log("\n🔨 构建前端…");
  const build = spawn("pnpm build", { cwd: path.join(ROOT, "frontend"), stdio: "inherit", shell: true });
  await new Promise((resolve, reject) => {
    build.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`前端构建失败 (exit ${code})`))));
  });
  console.log("✅ 前端构建完成");

  // 2. 找到空闲端口
  const backendPort = await findPort(8000, { host: "0.0.0.0" });
  console.log(`✅ 后端端口: ${backendPort}`);

  // 写入 .ports.json
  const fs = require("fs");
  let portsData = {};
  try { portsData = JSON.parse(fs.readFileSync(PORTS_FILE, "utf-8")); } catch {}
  portsData.backend = backendPort;
  fs.writeFileSync(PORTS_FILE, JSON.stringify(portsData, null, 2) + "\n");

  // 3. 启动后端
  const backend = spawn(
    "uv", ["run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", String(backendPort)],
    { cwd: path.join(ROOT, "backend"), stdio: "pipe" }
  );
  prefixStream(backend.stdout, process.stdout, "backend", "34");
  prefixStream(backend.stderr, process.stderr, "backend", "34");

  // 4. 等待就绪
  console.log("⏳ 等待后端就绪…");
  await waitForBackend(backendPort, 30000);
  console.log(`✅ IrisFlow 已就绪 → http://localhost:${backendPort}`);

  // 5. 生命周期管理
  let exiting = false;
  const cleanup = () => {
    if (exiting) return;
    exiting = true;
    console.log("\n🛑 正在关闭…");
    try { backend.kill(); } catch {}
    setTimeout(() => process.exit(0), 500);
  };

  process.on("SIGINT", cleanup);
  process.on("SIGTERM", cleanup);
  if (process.platform === "win32") {
    const rl = require("readline").createInterface({ input: process.stdin, output: process.stdout });
    rl.on("SIGINT", () => process.emit("SIGINT", "SIGINT"));
  }
  process.on("exit", () => { try { backend.kill(); } catch {} });

  backend.on("exit", (code) => {
    if (!exiting) cleanup();
  });
}

start().catch((err) => { console.error(err); process.exit(1); });
