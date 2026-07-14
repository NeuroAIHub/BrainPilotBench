/**
 * proxy.ts — 让 Node 的全局 fetch 认 HTTPS_PROXY / HTTP_PROXY 环境变量。
 *
 * 背景:Node 内置的 undici fetch 默认不读 *_PROXY 环境变量(与 curl/pip/gh 等 CLI 相反),
 * 导致在中国大陆等需要代理的开发机上,bp-bench fetch 通不了 hf://,而 curl 同 URL 是通的。
 * 解决:模块加载时读环境变量、装 undici ProxyAgent 为全局 dispatcher。CLI 入口 import 一次即可。
 *
 * 优先级:HTTPS_PROXY > HTTP_PROXY > ALL_PROXY(小写等价,后写覆盖前写)。
 * NO_PROXY 由 undici 内部尊重(逗号分隔的主机/网段白名单)。
 * SOCKS proxy(socks5://) undici 不支持;此时保留 direct fetch + 给一次性提示。
 * 显式设置 BPB_NO_PROXY=1 → 跳过安装(测试/离线场景),Node 保持默认行为。
 */
import { EnvHttpProxyAgent, setGlobalDispatcher } from "undici";

let installed = false;

/** 尝试从环境变量安装全局代理 dispatcher。幂等;可重复调用。返回是否装成功。 */
export function installProxyFromEnv(): boolean {
  if (installed) return true;
  if (process.env.BPB_NO_PROXY) return false;

  const httpsProxy = (process.env.HTTPS_PROXY || process.env.https_proxy || "").trim();
  const httpProxy = (process.env.HTTP_PROXY || process.env.http_proxy || "").trim();
  const allProxy = (process.env.ALL_PROXY || process.env.all_proxy || "").trim();
  const url = httpsProxy || httpProxy || allProxy;
  if (!url) return false;

  // undici 不支持 socks:直连,提示一次(不阻塞主流程,curl 走 SOCKS 通 ≠ Node 走 SOCKS 通)。
  if (/^socks[45]?h?:\/\//i.test(url)) {
    console.error(`⚠  undici 不支持 SOCKS proxy(${url});Node fetch 走直连,可能会超时。`);
    console.error("   如需走 SOCKS,配置一个前置 HTTP 代理指向它,再设 HTTPS_PROXY。");
    return false;
  }

  try {
    // EnvHttpProxyAgent chooses HTTP vs HTTPS per request and respects
    // NO_PROXY. Always bypass loopback so a remote-data proxy cannot break a
    // local BrainPilot health check.
    const existingNoProxy = process.env.NO_PROXY || process.env.no_proxy || "";
    const noProxy = [existingNoProxy, "localhost", "127.0.0.1", "::1"].filter(Boolean).join(",");
    setGlobalDispatcher(new EnvHttpProxyAgent({
      httpsProxy: httpsProxy || (allProxy && !/^socks/i.test(allProxy) ? allProxy : undefined),
      httpProxy: httpProxy || (allProxy && !/^socks/i.test(allProxy) ? allProxy : undefined),
      noProxy,
    }));
    installed = true;
    return true;
  } catch (e) {
    console.error(`⚠  安装 proxy dispatcher 失败(${url}): ${(e as Error).message}`);
    return false;
  }
}
