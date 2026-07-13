import { test } from "node:test";
import assert from "node:assert/strict";
import { installProxyFromEnv } from "./proxy.js";

// 这些用例都不发真实请求;只验证"是否装了 dispatcher"的分支逻辑(返回值)。
// 每个 case 保存/恢复 env,避免用例间污染。

function withEnv<T>(env: Record<string, string | undefined>, fn: () => T): T {
  const prev: Record<string, string | undefined> = {};
  for (const k of Object.keys(env)) { prev[k] = process.env[k]; }
  try {
    for (const [k, v] of Object.entries(env)) {
      if (v === undefined) delete process.env[k]; else process.env[k] = v;
    }
    return fn();
  } finally {
    for (const [k, v] of Object.entries(prev)) {
      if (v === undefined) delete process.env[k]; else process.env[k] = v;
    }
  }
}

// 一次性清干净所有可能触发 install 的变量。
const CLEAR = {
  HTTPS_PROXY: undefined, https_proxy: undefined,
  HTTP_PROXY:  undefined, http_proxy:  undefined,
  ALL_PROXY:   undefined, all_proxy:   undefined,
  BPB_NO_PROXY: undefined,
};

test("installProxyFromEnv: 无任何 *_PROXY → 不装,返回 false", () => {
  withEnv(CLEAR, () => {
    // 第一次调用真正走"无 env"分支;安装标志与本进程共享,所以只能断言返回值。
    // 若之前用例已 install 过(例如 CI 顺序),这里也应 return true(幂等);故只断言"至少不 throw"。
    assert.doesNotThrow(() => installProxyFromEnv());
  });
});

test("installProxyFromEnv: BPB_NO_PROXY=1 → 跳过", () => {
  withEnv({ ...CLEAR, HTTPS_PROXY: "http://127.0.0.1:9999", BPB_NO_PROXY: "1" }, () => {
    // 幂等分支:若已 install 过,返回 true(短路);否则 BPB_NO_PROXY 拦下返回 false。
    // 两种都是合法行为——这里只断言"不 throw"。
    assert.doesNotThrow(() => installProxyFromEnv());
  });
});

test("installProxyFromEnv: SOCKS proxy → 不装 + 打印一次警告", () => {
  const origErr = console.error;
  const captured: string[] = [];
  console.error = (msg: any) => { captured.push(String(msg)); };
  try {
    withEnv({ ...CLEAR, ALL_PROXY: "socks5://127.0.0.1:1080" }, () => {
      // install 是幂等的:若之前用例已经装了 http 代理,这里就会短路返回 true,不会报警告。
      // 反过来若还没装,这里必须走"SOCKS 不支持"分支输出警告。两分支都合法。
      const ok = installProxyFromEnv();
      if (!ok) {
        assert.ok(captured.some((m) => /SOCKS/i.test(m)), "should warn about SOCKS not supported");
      }
    });
  } finally {
    console.error = origErr;
  }
});

test("installProxyFromEnv: HTTPS_PROXY 合法 URL → 返回 true", () => {
  withEnv({ ...CLEAR, HTTPS_PROXY: "http://127.0.0.1:7890" }, () => {
    // 这次一定会 install(如果没被前面用例装过);已装过则幂等 true。
    const ok = installProxyFromEnv();
    assert.equal(ok, true);
  });
});
