import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { readFileSync } from "fs";
import { resolve } from "path";

const pkg = JSON.parse(readFileSync("./package.json", "utf-8"));

// 读取后端端口（由 scripts/dev.js 写入），未找到则回退默认值
function getBackendPort(): number {
  try {
    const raw = readFileSync(resolve(__dirname, "..", ".ports.json"), "utf-8");
    const ports = JSON.parse(raw);
    return ports.backend || 8000;
  } catch {
    return 8000;
  }
}

const backendPort = getBackendPort();
const backendTarget = `http://localhost:${backendPort}`;

export default defineConfig({
  plugins: [vue()],
  appType: "spa", // history 模式 SPA 回退
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  server: {
    host: "0.0.0.0",
    port: 3000,
    strictPort: false,  // 端口被占时自动 +1
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: true,
        // SSE 长连接：禁用缓冲以支持流式响应
      },
      // 根端点（/version、/status）不在 /api 下，需单独代理
      "/version": { target: backendTarget, changeOrigin: true },
      "/status":  { target: backendTarget, changeOrigin: true },
    },
  },
});
