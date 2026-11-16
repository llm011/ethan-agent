import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchKernels } from "@/lib/api-settings";

describe("fetchKernels", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    localStorage.clear();
  });

  it("throws clear message when server URL is missing", async () => {
    await expect(fetchKernels()).rejects.toThrow("未配置后端 Server 地址");
  });

  it("throws clear message when server URL lacks scheme", async () => {
    localStorage.setItem("ethan_api_url", "127.0.0.1:8900");
    await expect(fetchKernels()).rejects.toThrow("请以 http:// 或 https:// 开头");
  });

  it("throws clear message when server returns 200 HTML instead of JSON", async () => {
    localStorage.setItem("ethan_api_url", "http://127.0.0.1:8900");
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response("<!doctype html><html><body>SPA</body></html>", {
        status: 200,
        headers: { "Content-Type": "text/html" },
      }),
    );
    await expect(fetchKernels()).rejects.toThrow("接口返回了网页而非 JSON");
  });

  it("returns parsed kernels on valid JSON", async () => {
    localStorage.setItem("ethan_api_url", "http://127.0.0.1:8900");
    const payload = {
      kernels: [{ kind: "ethan", name: "Ethan 原生", available: true, reason: "", capabilities: {}, install_command: "", install_hint: "" }],
      default: "ethan",
      task_rules: {},
      last_install: null,
    };
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const out = await fetchKernels();
    expect(out.default).toBe("ethan");
    expect(out.kernels).toHaveLength(1);
  });
});
