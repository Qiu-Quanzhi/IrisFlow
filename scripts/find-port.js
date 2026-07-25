/** 端口探测工具 — 检查端口是否可用，被占自动递增。 */

const net = require("net");

/**
 * 检查指定端口是否空闲
 * @param {number} port
 * @param {string} [host="0.0.0.0"]
 * @returns {Promise<boolean>}
 */
function isFree(port, host = "0.0.0.0") {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(false));
    server.listen(port, host, () => {
      server.close(() => resolve(true));
    });
  });
}

/**
 * 从 preferred 开始找到第一个空闲端口
 * @param {number} preferred 首选端口
 * @param {object} [opts]
 * @param {string} [opts.host="0.0.0.0"]
 * @param {number} [opts.maxRetries=100]
 * @returns {Promise<number>}
 */
async function findPort(preferred, opts = {}) {
  const { host = "0.0.0.0", maxRetries = 100 } = opts;
  for (let port = preferred; port < preferred + maxRetries; port++) {
    if (await isFree(port, host)) return port;
  }
  throw new Error(`No free port found in range ${preferred}–${preferred + maxRetries}`);
}

/**
 * 找到可用端口并写入指定文件
 * @param {number} preferred
 * @param {string} filePath 写入的 JSON 文件路径
 * @param {string} key 在 JSON 中的键名
 * @param {object} [opts] 透传 findPort 的选项
 * @returns {Promise<number>} 找到的端口号
 */
async function findAndSave(preferred, filePath, key, opts = {}) {
  const fs = require("fs");
  const port = await findPort(preferred, opts);

  let data = {};
  try {
    data = JSON.parse(fs.readFileSync(filePath, "utf-8"));
  } catch {
    // 文件不存在或为空，从头创建
  }
  data[key] = port;
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2) + "\n");

  return port;
}

// CLI 用法: node scripts/find-port.js 8000 [--host 0.0.0.0] [--save .ports.json backend]
if (require.main === module) {
  const preferred = parseInt(process.argv[2], 10) || 8000;
  const hostIdx = process.argv.indexOf("--host");
  const host = hostIdx !== -1 ? process.argv[hostIdx + 1] : "0.0.0.0";
  const saveFlagIdx = process.argv.indexOf("--save");
  const filePath = saveFlagIdx !== -1 ? process.argv[saveFlagIdx + 1] : null;
  const key = saveFlagIdx !== -1 ? process.argv[saveFlagIdx + 2] || "port" : "port";

  if (filePath) {
    findAndSave(preferred, filePath, key, { host }).then((port) => process.stdout.write(String(port)));
  } else {
    findPort(preferred, { host }).then((port) => process.stdout.write(String(port)));
  }
}

module.exports = { isFree, findPort, findAndSave };
