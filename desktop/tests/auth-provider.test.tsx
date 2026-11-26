import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Both providers import this alias. Bind it to each platform's real api-base,
// so the assertions exercise the actual storage/cookie/asset URL implementation.
const binding = vi.hoisted(() => ({ api: {} as Record<string, unknown> }));
vi.mock("@/lib/api", () => ({
  getAuthToken: () => (binding.api.getAuthToken as () => string)(),
  setAuthToken: (token: string) => (binding.api.setAuthToken as (token: string) => void)(token),
  verifyAuth: (token: string) => (binding.api.verifyAuth as (token: string) => Promise<boolean>)(token),
}));

for (const platform of ["Web", "Desktop"] as const) {
  describe(`${platform} verified auth restore`, () => {
    let provider: typeof import("../src/lib/auth-context");
    let api: Pick<typeof import("../src/lib/api-base"), "getAuthToken" | "setAuthToken" | "verifyAuth" | "assetUrl">;
    let cookieWrite: ReturnType<typeof vi.spyOn>;
    let request: ReturnType<typeof vi.fn>;
    const token = "test-valid/with+reserved=characters";
    const encodedCookie = `ethan_token=${encodeURIComponent(token)}`;
    const assetSnapshots: { cookie: string; url: string }[] = [];

    beforeEach(async () => {
      vi.resetModules();
      localStorage.clear();
      document.cookie = "ethan_token=; max-age=0; path=/";
      assetSnapshots.length = 0;
      if (platform === "Web") {
        vi.stubEnv("NEXT_PUBLIC_API_URL", `${window.location.origin}/api`);
        api = await import("../../web/lib/api-base");
        provider = await import("../../web/lib/auth-context");
      } else {
        api = await import("../src/lib/api-base");
        provider = await import("../src/lib/auth-context");
      }
      binding.api = api;
      cookieWrite = vi.spyOn(document, "cookie", "set");
      request = vi.fn().mockResolvedValue({ ok: true });
      vi.stubGlobal("fetch", request);
    });

    afterEach(() => {
      cleanup();
      vi.restoreAllMocks();
      vi.unstubAllGlobals();
      vi.unstubAllEnvs();
    });

    function ProtectedChild() {
      const { authenticated, loading, logout } = provider.useAuth();
      if (loading) return <span>loading</span>;
      if (!authenticated) return <span>logged out</span>;
      const url = api.assetUrl("assets/images/test-session/image.jpg");
      assetSnapshots.push({ cookie: document.cookie, url });
      return <><img src={url} alt="protected asset" /><button onClick={logout}>logout</button></>;
    }

    let auth: ReturnType<typeof provider.useAuth>;
    function AuthControls() {
      auth = provider.useAuth();
      return <ProtectedChild />;
    }

    function mount() {
      const { AuthProvider } = provider;
      render(<AuthProvider><AuthControls /></AuthProvider>);
    }

    it.each(["missing", "expired", "stale"] as const)(
      "repairs a %s cookie only after verification, before protected assets render",
      async (state) => {
        localStorage.setItem("ethan_token", token);
        if (state === "expired") document.cookie = "ethan_token=old; max-age=0; path=/";
        if (state === "stale") document.cookie = "ethan_token=old; max-age=2592000; path=/";
        cookieWrite.mockClear();
        let resolve!: (value: { ok: boolean }) => void;
        request.mockReturnValue(new Promise<{ ok: boolean }>((r) => { resolve = r; }));
        mount();
        expect(screen.getByText("loading")).toBeTruthy();
        expect(request).toHaveBeenCalledWith(expect.stringMatching(/\/auth$/), expect.objectContaining({
          method: "POST", body: JSON.stringify({ token }),
        }));
        expect(cookieWrite).not.toHaveBeenCalled();
        expect(assetSnapshots).toHaveLength(0);
        await act(async () => { resolve({ ok: true }); });
        expect(screen.getByAltText("protected asset")).toBeTruthy();
        expect(cookieWrite).toHaveBeenCalledWith(`${encodedCookie}; max-age=2592000; path=/`);
        expect(assetSnapshots.length).toBeGreaterThan(0);
        expect(assetSnapshots.every(({ cookie }) => cookie === encodedCookie)).toBe(true);
        for (const { url } of assetSnapshots) {
          expect(url).not.toContain(token);
          if (platform === "Web") expect(new URL(url, window.location.href).search).toBe("");
          else expect(new URL(url, window.location.href).searchParams.get("token")).toBe(token);
        }
      },
    );

    it("does not write an unverified stored token", async () => {
      localStorage.setItem("ethan_token", token);
      request.mockResolvedValue({ ok: false });
      mount();
      await screen.findByText("logged out");
      expect(cookieWrite).not.toHaveBeenCalled();
      expect(document.cookie).toBe("");
      expect(assetSnapshots).toHaveLength(0);
    });

    it("does not mint a cookie when empty-token verification succeeds", async () => {
      mount();
      await screen.findByAltText("protected asset");
      expect(request).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ body: JSON.stringify({ token: "" }) }));
      expect(cookieWrite).not.toHaveBeenCalled();
      expect(localStorage.getItem("ethan_token")).toBeNull();
      expect(document.cookie).toBe("");
    });

    it("does not resurrect a logout while initial verification is pending", async () => {
      localStorage.setItem("ethan_token", token);
      let resolve!: (value: { ok: boolean }) => void;
      request.mockReturnValue(new Promise<{ ok: boolean }>((r) => { resolve = r; }));
      mount();
      act(() => auth.logout());
      cookieWrite.mockClear();
      await act(async () => { resolve({ ok: true }); });
      expect(screen.getByText("logged out")).toBeTruthy();
      expect(cookieWrite).not.toHaveBeenCalled();
      expect(localStorage.getItem("ethan_token")).toBeNull();
      expect(document.cookie).toBe("");
      expect(assetSnapshots).toHaveLength(0);
    });

    it.each([true, false])("does not overwrite a newer login when old restore resolves %s", async (ok) => {
      localStorage.setItem("ethan_token", token);
      const newerToken = "test-newer/login+token=";
      let resolve!: (value: { ok: boolean }) => void;
      request.mockReturnValueOnce(new Promise<{ ok: boolean }>((r) => { resolve = r; }));
      mount();
      await act(async () => { expect(await auth.login(newerToken)).toBe(true); });
      cookieWrite.mockClear();
      await act(async () => { resolve({ ok }); });
      expect(screen.getByAltText("protected asset")).toBeTruthy();
      expect(cookieWrite).not.toHaveBeenCalled();
      expect(localStorage.getItem("ethan_token")).toBe(newerToken);
      expect(document.cookie).toBe(`ethan_token=${encodeURIComponent(newerToken)}`);
      expect(api.getAuthToken()).toBe(newerToken);
    });

    it("logout clears restored storage, cookie and in-memory authentication", async () => {
      localStorage.setItem("ethan_token", token);
      mount();
      await screen.findByAltText("protected asset");
      fireEvent.click(screen.getByText("logout"));
      await waitFor(() => expect(screen.getByText("logged out")).toBeTruthy());
      expect(localStorage.getItem("ethan_token")).toBeNull();
      expect(document.cookie).toBe("");
      expect(api.getAuthToken()).toBe("");
      expect(screen.queryByAltText("protected asset")).toBeNull();
    });
  });
}
