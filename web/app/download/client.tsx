"use client";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import Image from "next/image";
import {
  Apple,
  AppWindow,
  Check,
  Container,
  Copy,
  Download,
  ExternalLink,
  Sparkles,
  Terminal,
} from "lucide-react";

const REPO = "llm011/ethan-agent";
const FALLBACK_VERSION = "0.5.151";
const GITHUB = `https://github.com/${REPO}`;

/* ── 类型 ────────────────────────────────────────────── */

type AssetKey = "macArmDmg" | "macX64Dmg" | "winSetup" | "winMsi";

interface Asset {
  url: string;
  size?: number; // 字节
}

interface ReleaseInfo {
  tag: string; // "v0.5.151"
  assets: Partial<Record<AssetKey, Asset>>;
}

type Os = "mac-arm" | "mac-intel" | "win" | "linux" | "other";

/* ── 工具函数 ────────────────────────────────────────── */

/** GitHub API 不可用时的兜底：按已知命名规则拼出下载地址 */
function fallbackRelease(): ReleaseInfo {
  const tag = `v${FALLBACK_VERSION}`;
  const u = (name: string) => `${GITHUB}/releases/download/${tag}/${name}`;
  return {
    tag,
    assets: {
      macArmDmg: { url: u(`Ethan.Agent_${FALLBACK_VERSION}_aarch64.dmg`) },
      macX64Dmg: { url: u(`Ethan.Agent_${FALLBACK_VERSION}_x64.dmg`) },
      winSetup: { url: u(`Ethan.Agent_${FALLBACK_VERSION}_x64-setup.exe`) },
      winMsi: { url: u(`Ethan.Agent_${FALLBACK_VERSION}_x64_en-US.msi`) },
    },
  };
}

/** 通过 WebGL 渲染器字符串区分 Apple Silicon / Intel Mac（Intel/AMD 独显为 x64） */
function isAppleSilicon(): boolean {
  try {
    const gl = document.createElement("canvas").getContext("webgl");
    if (!gl) return true; // 拿不到 WebGL 时按主流情况假设 Apple Silicon
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    const renderer = ext
      ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL))
      : String(gl.getParameter(gl.RENDERER));
    return !/intel|amd|radeon|nvidia/i.test(renderer);
  } catch {
    return true;
  }
}

function detectOs(): Os {
  if (typeof navigator === "undefined") return "other";
  const ua = navigator.userAgent;
  if (/Windows/i.test(ua)) return "win";
  if (/Macintosh|Mac OS X/i.test(ua)) return isAppleSilicon() ? "mac-arm" : "mac-intel";
  if (/Linux/i.test(ua) && !/Android/i.test(ua)) return "linux";
  return "other";
}

/** 检测结果只需算一次（WebGL 探测有开销），缓存在模块级 */
let cachedOs: Os | null = null;
function getClientOs(): Os {
  if (cachedOs === null) cachedOs = detectOs();
  return cachedOs;
}

/** 水合安全的客户端系统检测：服务端快照恒为 "other"，客户端取真实值 */
function useOs(): Os {
  return useSyncExternalStore(
    () => () => {},
    getClientOs,
    () => "other" as Os,
  );
}

function fmtSize(bytes?: number): string {
  if (!bytes || bytes <= 0) return "";
  const mb = bytes / 1024 / 1024;
  if (mb < 1) return `${Math.round(bytes / 1024)} KB`;
  return `约 ${mb >= 10 ? Math.round(mb) : mb.toFixed(1)} MB`;
}

/* ── 小组件 ──────────────────────────────────────────── */

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      aria-label={label ?? "复制"}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1600);
        } catch {
          /* 忽略剪贴板权限失败 */
        }
      }}
      className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
    >
      {copied ? <Check className="size-3.5 text-primary" /> : <Copy className="size-3.5" />}
      {copied ? "已复制" : "复制"}
    </button>
  );
}

function CommandLine({ cmd, hint }: { cmd: string; hint?: string }) {
  return (
    <div className="group flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/60 px-3.5 py-2.5">
      <code className="min-w-0 flex-1 truncate font-mono text-[13px] text-foreground" title={cmd}>
        <span className="mr-2 select-none text-muted-foreground/60">$</span>
        {cmd}
      </code>
      <CopyButton text={cmd} />
      {hint ? <span className="hidden shrink-0 text-xs text-muted-foreground sm:block">{hint}</span> : null}
    </div>
  );
}

function PrimaryDownloadButton({ asset, children }: { asset?: Asset; children: React.ReactNode }) {
  return (
    <a
      href={asset?.url ?? "#"}
      className="group inline-flex h-12 items-center gap-2.5 rounded-xl bg-primary px-6 text-[15px] font-semibold text-primary-foreground shadow-lg shadow-primary/25 transition-all hover:brightness-110 hover:shadow-xl hover:shadow-primary/30 active:scale-[0.98]"
    >
      <Download className="size-5 transition-transform group-hover:translate-y-0.5" />
      {children}
    </a>
  );
}

function FormatLink({ asset, label }: { asset?: Asset; label: string }) {
  const size = fmtSize(asset?.size);
  return (
    <a
      href={asset?.url ?? "#"}
      className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground transition-all hover:border-primary/50 hover:bg-primary/5 hover:text-primary"
    >
      <Download className="size-3.5" />
      {label}
      {size ? <span className="text-xs font-normal text-muted-foreground">· {size}</span> : null}
    </a>
  );
}

/* ── 页面 ────────────────────────────────────────────── */

export default function DownloadClient() {
  const os = useOs();
  const [release, setRelease] = useState<ReleaseInfo>(fallbackRelease);

  // 拉取最新 release，拿到真实下载地址和文件大小；失败则继续用兜底版本
  useEffect(() => {
    let cancelled = false;
    fetch(`https://api.github.com/repos/${REPO}/releases/latest`, {
      headers: { Accept: "application/vnd.github+json" },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled || !d?.tag_name || !Array.isArray(d?.assets)) return;
        const pick = (pred: (name: string) => boolean): Asset | undefined => {
          const a = d.assets.find((x: { name: string }) => pred(x.name));
          return a ? { url: a.browser_download_url, size: a.size } : undefined;
        };
        setRelease({
          tag: d.tag_name,
          assets: {
            macArmDmg: pick((n) => /aarch64\.dmg$/.test(n)),
            macX64Dmg: pick((n) => /_x64\.dmg$/.test(n)),
            winSetup: pick((n) => /x64-setup\.exe$/.test(n)),
            winMsi: pick((n) => /_x64_en-US\.msi$/.test(n)),
          },
        });
      })
      .catch(() => {
        /* 网络失败保持兜底 */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const { assets, tag } = release;

  // 检测结果对应的推荐条目
  const recommended = useMemo(() => {
    switch (os) {
      case "mac-arm":
        return {
          icon: Apple,
          platform: "macOS · Apple Silicon",
          asset: assets.macArmDmg,
          cta: "下载 macOS 版",
          hint: "M 系列芯片的 Mac",
        };
      case "mac-intel":
        return {
          icon: Apple,
          platform: "macOS · Intel",
          asset: assets.macX64Dmg,
          cta: "下载 macOS 版",
          hint: "Intel 芯片的 Mac",
        };
      case "win":
        return {
          icon: AppWindow,
          platform: "Windows · x64",
          asset: assets.winSetup,
          cta: "下载 Windows 版",
          hint: "Windows 10 / 11（64 位）",
        };
      default:
        return null;
    }
  }, [os, assets]);

  const version = tag.replace(/^v/, "");

  return (
    <div className="relative min-h-screen overflow-hidden bg-background text-foreground">
      {/* 装饰性渐变光斑 */}
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[420px]">
        <div className="absolute left-1/2 top-[-220px] size-[560px] -translate-x-[70%] rounded-full bg-primary/15 blur-3xl" />
        <div className="absolute left-1/2 top-[-180px] size-[420px] translate-x-[35%] rounded-full bg-chart-2/15 blur-3xl" />
      </div>

      {/* 顶栏 */}
      <header className="mx-auto flex w-full max-w-5xl items-center justify-between px-6 py-5">
        <Link href="/" className="flex items-center gap-2.5 font-semibold">
          <Image
            src={`${process.env.NEXT_PUBLIC_BASE_PATH || ""}/logo-sidebar.png`}
            alt="Ethan Agent"
            width={28}
            height={28}
            className="rounded-full"
          />
          Ethan Agent
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          <Link
            href="/docs"
            className="rounded-lg px-3 py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            文档
          </Link>
          <a
            href={GITHUB}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            GitHub
            <ExternalLink className="size-3.5" />
          </a>
        </nav>
      </header>

      <main className="mx-auto w-full max-w-5xl px-6 pb-20">
        {/* 标题 */}
        <section className="py-12 text-center sm:py-16">
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">选择你的平台</h1>
          <p className="mx-auto mt-4 max-w-xl text-balance text-muted-foreground">
            桌面端安装包开箱即用；服务器端一行命令即可部署。所有平台共享同一个 Agent 后端。
          </p>
        </section>

        {/* 检测到系统后的推荐卡片 */}
        {recommended ? (
          <div className="animate-in fade-in slide-in-from-bottom-4 mx-auto max-w-2xl duration-500">
            <div className="relative overflow-hidden rounded-2xl border border-primary/30 bg-card p-6 shadow-lg shadow-primary/10 sm:p-8">
              <div className="flex items-center gap-2 text-sm font-medium text-primary">
                <Sparkles className="size-4" />
                已为你检测到系统
              </div>
              <div className="mt-4 flex flex-col items-start gap-5 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-3.5">
                  <span className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <recommended.icon className="size-6" />
                  </span>
                  <div>
                    <div className="text-lg font-semibold">{recommended.platform}</div>
                    <div className="text-sm text-muted-foreground">{recommended.hint}</div>
                  </div>
                </div>
                <PrimaryDownloadButton asset={recommended.asset}>
                  {recommended.cta}
                  {recommended.asset ? (
                    <span className="font-normal opacity-80">
                      · dmg · {fmtSize(recommended.asset.size) || `${version}`}
                    </span>
                  ) : null}
                </PrimaryDownloadButton>
              </div>
            </div>
          </div>
        ) : os === "linux" || os === "other" ? (
          <div className="animate-in fade-in slide-in-from-bottom-4 mx-auto max-w-2xl duration-500">
            <div className="rounded-2xl border border-border bg-card p-6 sm:p-8">
              <div className="flex items-center gap-3.5">
                <span className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Terminal className="size-6" />
                </span>
                <div>
                  <div className="text-lg font-semibold">
                    {os === "linux" ? "检测到 Linux · 用命令行安装" : "没有找到适配的桌面安装包？"}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    服务器、NAS、远程开发机都可以用 pip 部署，见下方「服务器部署」。
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {/* 所有平台 */}
        <section className="mt-14">
          <h2 className="text-xl font-semibold">所有平台</h2>
          <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {/* macOS Apple Silicon */}
            <div className="rounded-2xl border border-border bg-card p-5 transition-all hover:border-primary/40 hover:shadow-md">
              <div className="flex items-center gap-3">
                <span className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Apple className="size-5" />
                </span>
                <div>
                  <div className="font-semibold">macOS · Apple Silicon</div>
                  <div className="text-xs text-muted-foreground">M1 / M2 / M3 / M4 芯片</div>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <FormatLink asset={assets.macArmDmg} label=".dmg" />
              </div>
            </div>

            {/* macOS Intel */}
            <div className="rounded-2xl border border-border bg-card p-5 transition-all hover:border-primary/40 hover:shadow-md">
              <div className="flex items-center gap-3">
                <span className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Apple className="size-5" />
                </span>
                <div>
                  <div className="font-semibold">macOS · Intel</div>
                  <div className="text-xs text-muted-foreground">Intel 芯片的 Mac</div>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <FormatLink asset={assets.macX64Dmg} label=".dmg" />
              </div>
            </div>

            {/* Windows x64 */}
            <div className="rounded-2xl border border-border bg-card p-5 transition-all hover:border-primary/40 hover:shadow-md sm:col-span-2 lg:col-span-1">
              <div className="flex items-center gap-3">
                <span className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <AppWindow className="size-5" />
                </span>
                <div>
                  <div className="font-semibold">Windows · x64</div>
                  <div className="text-xs text-muted-foreground">Windows 10 / 11（64 位）</div>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <FormatLink asset={assets.winSetup} label=".exe 安装版" />
                <FormatLink asset={assets.winMsi} label=".msi" />
              </div>
            </div>
          </div>
          <p className="mt-4 text-sm text-muted-foreground">
            不确定 Mac 的芯片型号？点击左上角  →「关于本机」即可查看。
          </p>
        </section>

        {/* 服务器部署 */}
        <section className="mt-14">
          <h2 className="text-xl font-semibold">想在服务器上运行？</h2>
          <p className="mt-1.5 text-sm text-muted-foreground">
            适合 NAS、家庭主机、远程开发机等无图形界面的环境——底层与桌面端完全相同。
          </p>
          <div className="mt-5 space-y-3 rounded-2xl border border-border bg-card p-5 sm:p-6">
            <div className="text-sm font-medium text-muted-foreground">1. 安装（需要 Python 3.12+）</div>
            <CommandLine cmd="pip3 install ethan-agent" />
            <div className="pt-2 text-sm font-medium text-muted-foreground">2. 配置模型 API</div>
            <CommandLine cmd="ethan provider set openai_compat --api-key sk-xxx --base-url https://api.openai.com/v1" />
            <div className="pt-2 text-sm font-medium text-muted-foreground">3. 启动</div>
            <CommandLine cmd="ethan serve" />
            <p className="pt-1 text-xs text-muted-foreground">
              支持 OpenAI / Gemini / DeepSeek / Ollama 等任何兼容 API。已经在服务器上？通过 SSH 执行同样的命令即可。
            </p>

            <div className="mt-5 border-t border-border pt-5">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Container className="size-4 text-primary" />
                或使用 Docker Compose
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <a
                  href={`${GITHUB}/releases/latest/download/docker-compose.yml`}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm font-medium transition-all hover:border-primary/50 hover:bg-primary/5 hover:text-primary"
                >
                  <Download className="size-3.5" />
                  docker-compose.yml
                </a>
                <a
                  href={`${GITHUB}/releases/latest/download/default.env.example`}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-1.5 text-sm font-medium transition-all hover:border-primary/50 hover:bg-primary/5 hover:text-primary"
                >
                  <Download className="size-3.5" />
                  default.env.example
                </a>
              </div>
            </div>
          </div>
        </section>

        {/* 版本信息 */}
        <footer className="mt-14 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-center text-sm text-muted-foreground">
          <span>当前版本：{tag}</span>
          <span aria-hidden>·</span>
          <a
            href={`${GITHUB}/releases/tag/${tag}`}
            target="_blank"
            rel="noreferrer"
            className="underline-offset-4 transition-colors hover:text-primary hover:underline"
          >
            更新内容
          </a>
          <span aria-hidden>·</span>
          <a
            href={`${GITHUB}/releases`}
            target="_blank"
            rel="noreferrer"
            className="underline-offset-4 transition-colors hover:text-primary hover:underline"
          >
            查看所有版本
          </a>
        </footer>
      </main>
    </div>
  );
}
