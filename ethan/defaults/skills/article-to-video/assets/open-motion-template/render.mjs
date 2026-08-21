import { getCompositions, renderFrames } from "@open-motion/renderer";
import { getTimeHijackScript } from "@open-motion/core";
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// 与 video_pipeline.py 的 ID_RE 一致：kebab-case。stills 会把 scene.id 拼进输出
// 文件名，非法 id 可逃逸 stillsDir，重复 id 会静默互相覆盖。
// 必须定义在模块顶部：stills 分支在顶层 await exportStills()，此时文件底部的
// const 尚未初始化（TDZ），引用会直接 ReferenceError。
const SCENE_ID_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

// ── CLI arguments ──
// 视频模式:  node render.mjs <timeline.json> <output.mp4> <cover.png> <report.json> <public-dir>
// 静帧模式:  node render.mjs stills <timeline.json> <stills-dir> <public-dir> [--first-frame]
//            （H3 流水线用：每个场景导出 presenter 开/关两张 PNG，见文件底部 exportStills）
//            --first-frame：取场景起点帧而非 2/3 帧（Seedance 图生视频需要首帧作起点，
//            2/3 帧会让成片场景开头瞬移到"动画已稳定"状态）。
const argv = process.argv.slice(2);
if (argv[0] === "stills") {
  const [, timelineArg, stillsDirArg, publicArg] = argv;
  if (!timelineArg || !stillsDirArg || !publicArg) {
    throw new Error("Usage: node render.mjs stills <timeline.json> <stills-dir> <public-dir> [--first-frame]");
  }
  const firstFrameMode = argv.includes("--first-frame");
  await exportStills(path.resolve(timelineArg), path.resolve(stillsDirArg), path.resolve(publicArg), {firstFrameMode});
  // ESM 禁止顶层 return，不显式退出会落入下方视频模式的参数解析（stills 只带 4 个
  // 参数，必然 Usage 报错、exit 1）。POSIX 下 stdout 管道/TTY 写是同步的，
  // process.exit 不会截断报告。
  process.exit(0);
}

const [timelinePathArg, outputPathArg, coverPathArg, reportPathArg, publicDirArg] = argv;
if (!timelinePathArg || !outputPathArg || !coverPathArg || !reportPathArg || !publicDirArg) {
  throw new Error("Usage: node render.mjs <timeline.json> <output.mp4> <cover.png> <report.json> <public-dir>");
}

const timelinePath = path.resolve(timelinePathArg);
const outputPath = path.resolve(outputPathArg);
const coverPath = path.resolve(coverPathArg);
const reportPath = path.resolve(reportPathArg);
const publicDir = path.resolve(publicDirArg);
const timeline = JSON.parse(fs.readFileSync(timelinePath, "utf8"));
const scenes = Array.isArray(timeline.scenes) ? timeline.scenes : [];
if (scenes.length === 0) {
  throw new Error("Timeline must contain at least one scene");
}

// Validate every deterministic audio input before Vite/Playwright performs any
// expensive work. Timelines produced by video_pipeline always require one audio
// file per scene; silently dropping one would publish a successful silent video.
let publicRoot;
try {
  publicRoot = fs.realpathSync(path.resolve(publicDir));
} catch {
  throw new Error(`Public directory does not exist: ${publicDir}`);
}
const sceneAudioInputs = scenes.map((scene, index) => {
  if (!scene || typeof scene.audio !== "string" || !scene.audio.trim()) {
    throw new Error(`Scene ${scene?.id || index} is missing a non-empty audio path`);
  }
  // startMs feeds the adelay fallback. A non-numeric value only surfaces as
  // `adelay=NaN|NaN` once every frame has already been rendered, so reject it
  // here instead of after a ten-minute render.
  if (!Number.isFinite(scene.startMs) || scene.startMs < 0) {
    throw new Error(`Scene ${scene?.id || index} has an invalid startMs: ${scene.startMs}`);
  }
  const relativeAudio = scene.audio.trim().replace(/^[\\/]+/, "");
  const requestedAudioPath = path.resolve(publicRoot, relativeAudio);
  if (requestedAudioPath !== publicRoot && !requestedAudioPath.startsWith(`${publicRoot}${path.sep}`)) {
    throw new Error(`Audio path escapes public directory: ${scene.audio}`);
  }
  let audioPath;
  let audioStat;
  try {
    // Resolve symlinks before the containment check: a seemingly local audio
    // file must not be able to point outside the supplied public directory.
    audioPath = fs.realpathSync(requestedAudioPath);
    audioStat = fs.statSync(audioPath);
  } catch {
    throw new Error(`Missing audio asset: ${requestedAudioPath}`);
  }
  if (audioPath !== publicRoot && !audioPath.startsWith(`${publicRoot}${path.sep}`)) {
    throw new Error(`Audio path escapes public directory: ${scene.audio}`);
  }
  if (!audioStat.isFile() || audioStat.size === 0) {
    throw new Error(`Invalid audio asset: ${audioPath}`);
  }
  return {
    scene,
    path: audioPath,
    src: `/${relativeAudio.split(path.sep).join("/")}`,
  };
});

// ── Derive output paths ──
const renderDir = path.dirname(outputPath);
const tmpDir = path.join(renderDir, "temp");
const distDir = path.join(tmpDir, "vite-dist");

// ── 1./2./3. 都放进 try：vite build / Chromium 安装半途失败也要清掉 tmpDir 半成品 ──
let server;
let url;

try {
  process.stderr.write("[Step 1/5] Checking Playwright browsers...\n");
  ensureChromiumPath();

  process.stderr.write("[Step 2/5] Building with Vite...\n");
  buildRenderer(distDir);
  process.stderr.write("[Step 2/5] Vite build done\n");

  // Serve dist/ on an OS-assigned loopback port.
  // A random fixed port can collide with an existing local process. Using port 0
  // lets the kernel choose an available port, and avoids depending on http-server.
  ({server, url} = await startAssetServer(distDir, publicRoot));

  // ── 4. Discover compositions ──
  process.stderr.write(`[Step 3/5] Discovering compositions from ${url}...\n`);
  process.stderr.write(`timeline scenes: ${timeline.scenes?.length}, totalDurationMs: ${timeline.totalDurationMs}\n`);
  const compositions = await getCompositions(url, { inputProps: timeline, timeout: 60000 });
  const comp = compositions.find((c) => c.id === "ArticleVideo");
  if (!comp) throw new Error(`No composition "ArticleVideo" found (got: ${compositions.map(c=>c.id).join(", ")})`);

  // Use timeline.json values for config — getCompositions may return defaults if calculateMetadata isn't invoked
  const fps = timeline.fps || comp.fps || 30;
  const config = {
    width: timeline.width || comp.width || 1080,
    height: timeline.height || comp.height || 1920,
    fps,
    durationInFrames: Math.max(1, Math.ceil(((timeline.totalDurationMs || 3000) / 1000) * fps)),
  };
  process.stderr.write(`[Step 3/5] Rendering ${comp.id} (${config.width}x${config.height}, ${config.fps}fps, ${config.durationInFrames} frames)\n`);

  // ── 5. Render frames (Playwright screenshots) ──
  process.stderr.write(`[Step 4/5] Capturing frames (0/${config.durationInFrames})...\n`);
  const result = await renderFrames({
    url,
    config,
    outputDir: tmpDir,
    compositionId: comp.id,
    inputProps: timeline,
    concurrency: Math.min(9, Math.max(1, Math.floor((os.cpus().length || 4) / 2))),
    publicDir,
    timeout: 600000,
    onProgress: (frame) => {
      const pct = Math.round((frame / config.durationInFrames) * 100);
      if (pct % 10 === 0) process.stderr.write(`[Step 4/5] Frames: ${frame}/${config.durationInFrames} (${pct}%)\n`);
    },
  });
  process.stderr.write(`[Step 4/5] Frames complete: ${config.durationInFrames}/${config.durationInFrames} (100%)\n`);

  // ── 6. Encode frames → MP4 with audio mixing ──
  // renderFrames records every visible <Audio> on every frame. Collapse those
  // observations back to one start frame per scene before building FFmpeg inputs.
  // @open-motion/core's <Audio> registers itself with useAbsoluteFrame(), i.e. the
  // frame being screenshotted, and the renderer's dedup key includes startFrame.
  // A scene therefore contributes one observation per frame it stays visible, and
  // the observations for one src are the frame numbers that src was audible on.
  // Taking the minimum per src would hand two scenes sharing one audio file the
  // earlier scene's offset — the clip gets mixed twice at the same instant and the
  // later scene plays silent. Match each scene to the observation nearest its own
  // timeline position instead.
  const audioAssetsFromRenderer = result?.audioAssets || [];
  const framesBySrc = new Map();
  audioAssetsFromRenderer.forEach((asset) => {
    if (!asset || typeof asset.src !== "string" || !Number.isFinite(asset.startFrame)) return;
    const src = `/${asset.src.replace(/^\/+/, "")}`;
    if (!framesBySrc.has(src)) framesBySrc.set(src, []);
    framesBySrc.get(src).push(asset.startFrame);
  });

  const nearestObservedStartFrame = (publicSrc, expectedStartFrame) => {
    const observed = framesBySrc.get(publicSrc);
    if (!observed || observed.length === 0) return expectedStartFrame;
    return observed.reduce((best, frame) =>
      Math.abs(frame - expectedStartFrame) < Math.abs(best - expectedStartFrame) ? frame : best,
    );
  };

  const audioEntries = sceneAudioInputs.map(({scene, path: audioPath, src: publicSrc}, index) => {
    const fallbackStartFrame = Math.round((scene.startMs / 1000) * fps);
    const startFrame = nearestObservedStartFrame(publicSrc, fallbackStartFrame);
    return {
      inputIdx: index + 1, // input 0 is the image sequence
      path: audioPath,
      src: publicSrc,
      startFrame,
      delayMs: Math.round((startFrame / fps) * 1000),
    };
  });

  const filterParts = [];
  audioEntries.forEach((entry, i) => {
    filterParts.push(`[${entry.inputIdx}:a]adelay=${entry.delayMs}|${entry.delayMs},asetpts=PTS-STARTPTS[a${i}]`);
  });

  const encodedDurationSec = config.durationInFrames / config.fps;
  if (audioEntries.length > 0) {
    const audioInputArgs = audioEntries.flatMap((e) => ["-i", e.path]);
    const mixInputs = audioEntries.map((e, i) => `[a${i}]`).join("");
    filterParts.push(`${mixInputs}amix=inputs=${audioEntries.length}:duration=longest:normalize=0[aout]`);
    const filterComplex = filterParts.join(";");

    process.stderr.write("[Step 5/5] Encoding MP4 with FFmpeg (video + audio)...\n");
    // execFileSync 数组传参，不经 shell：路径含空格/特殊字符时不会断裂
    execFileSync(
      "ffmpeg",
      [
        "-y", "-framerate", String(config.fps),
        "-i", `${tmpDir}/frame-%05d.png`,
        ...audioInputArgs,
        "-filter_complex", filterComplex,
        "-map", "0:v", "-map", "[aout]",
        "-t", String(encodedDurationSec),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        outputPath,
      ],
      { stdio: "inherit" },
    );
  } else {
    process.stderr.write("[Step 5/5] Encoding MP4 with FFmpeg (video only)...\n");
    execFileSync(
      "ffmpeg",
      [
        "-y", "-framerate", String(config.fps),
        "-i", `${tmpDir}/frame-%05d.png`,
        "-t", String(encodedDurationSec),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
        outputPath,
      ],
      { stdio: "inherit" },
    );
  }

  // ── 7. Extract cover frame (~1.2s) ──
  const coverFrame = Math.min(config.durationInFrames - 1, Math.max(0, Math.round(config.fps * 1.2)));
  const coverFrameFile = path.join(tmpDir, `frame-${String(coverFrame).padStart(5, "0")}.png`);
  if (fs.existsSync(coverFrameFile)) {
    fs.copyFileSync(coverFrameFile, coverPath);
  } else {
    const fallback = path.join(tmpDir, "frame-00000.png");
    if (fs.existsSync(fallback)) fs.copyFileSync(fallback, coverPath);
  }

  // ── 8. Write render-report.json (compatible with video_pipeline.py) ──
  const videoBytes = fs.existsSync(outputPath) ? fs.statSync(outputPath).size : 0;
  const coverBytes = fs.existsSync(coverPath) ? fs.statSync(coverPath).size : 0;
  const report = {
    status: "ok",
    composition: comp.id,
    width: config.width,
    height: config.height,
    fps: config.fps,
    durationInFrames: config.durationInFrames,
    expectedDurationMs: timeline.totalDurationMs,
    sceneCount: timeline.scenes?.length || 0,
    videoBytes,
    coverBytes,
    audioAssets: audioEntries.map(({src, startFrame, delayMs}) => ({src, startFrame, delayMs})),
  };
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  process.stdout.write(JSON.stringify(report) + "\n");

} finally {
  // ── Cleanup: stop local server + remove all temp files ──
  // Never await close(): its callback only fires once every client socket is
  // gone, and a Chromium left alive by a mid-render throw can hold a request
  // in flight forever — that would hang this finally block and swallow the real
  // error. Destroy the sockets outright, then close without waiting.
  try {
    server?.closeAllConnections?.();
    server?.close();
  } catch {}
  // Remove rendered frames + Vite build output (distDir is child of tmpDir)
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch {}
  // Remove debug screenshots
  try {
    for (const f of fs.readdirSync(__dirname)) {
      if (f.startsWith("debug-") && f.endsWith(".png")) {
        fs.unlinkSync(path.join(__dirname, f));
      }
    }
  } catch {}
  process.stderr.write("Temp files cleaned up.\n");
}

// ─── Shared helpers（视频模式与 stills 模式共用）───

function isBrowserFile(candidate) {
  if (!candidate) return false;
  try {
    return fs.statSync(candidate).isFile();
  } catch {
    return false;
  }
}

function ensureChromiumPath() {
  const configuredChromiumPath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH?.trim();
  let chromiumPath = configuredChromiumPath;
  if (configuredChromiumPath) {
    if (!isBrowserFile(configuredChromiumPath)) {
      throw new Error(`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH is not a file: ${configuredChromiumPath}`);
    }
    process.stderr.write("[Step 1/5] Playwright OK (configured executable)\n");
    return chromiumPath;
  }
  try {
    chromiumPath = chromium.executablePath();
  } catch {
    chromiumPath = null;
  }
  if (isBrowserFile(chromiumPath)) {
    process.stderr.write("[Step 1/5] Playwright OK (cached)\n");
    return chromiumPath;
  }
  process.stderr.write("[Step 1/5] Installing Playwright Chromium...\n");
  execFileSync("npx", ["playwright", "install", "chromium"], { cwd: __dirname, stdio: "inherit" });
  chromiumPath = chromium.executablePath();
  if (!isBrowserFile(chromiumPath)) {
    throw new Error(`Playwright Chromium install completed but executable is missing: ${chromiumPath}`);
  }
  return chromiumPath;
}

function buildRenderer(distDir) {
  fs.mkdirSync(distDir, { recursive: true });
  execFileSync("npx", ["vite", "build", "--outDir", distDir], { cwd: __dirname, stdio: "inherit" });
}

// dist/ 优先、publicDir 兜底的静态 server，监听 127.0.0.1 的 OS 分配端口。
async function startAssetServer(distDir, publicRoot) {
  // 注意必须留在函数体内：stills 模式在模块顶层 await 本函数，顶层 const 尚未初始化（TDZ）。
  const MIME_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    // 资产库回退：presenter 立绘 / b-roll 素材由 video_pipeline stage 到 publicDir，
    // 不在 vite dist 里，需要 server 兜底服务
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
  };
  const server = http.createServer((request, response) => {
    let requestPath;
    try {
      requestPath = decodeURIComponent(new URL(request.url || "/", "http://127.0.0.1").pathname);
    } catch {
      response.writeHead(400).end("Invalid request path");
      return;
    }
    const candidate = path.resolve(distDir, `.${requestPath}`);
    if (candidate !== distDir && !candidate.startsWith(`${distDir}${path.sep}`)) {
      response.writeHead(403).end("Forbidden");
      return;
    }
    let filePath = candidate;
    let isFile = (() => {
      try {
        return fs.statSync(filePath).isFile();
      } catch {
        return false;
      }
    })();
    if (!isFile && path.extname(requestPath)) {
      // dist miss → 回退到 publicDir（presenter 立绘 / 音频 / b-roll 等 stage 资产）。
      // 同样的 containment 检查，防路径逃逸。
      const publicCandidate = path.resolve(publicRoot, `.${requestPath}`);
      if (publicCandidate !== publicRoot && publicCandidate.startsWith(`${publicRoot}${path.sep}`)) {
        try {
          const resolved = fs.realpathSync(publicCandidate);
          if ((resolved === publicRoot || resolved.startsWith(`${publicRoot}${path.sep}`)) && fs.statSync(resolved).isFile()) {
            filePath = resolved;
            isFile = true;
          }
        } catch {
          // fall through to 404
        }
      }
    }
    if (!isFile) {
      // Only extension-less paths are SPA routes worth rewriting to index.html.
      // A missing .js/.css/.png means the Vite build is stale or partial; answering
      // 200 + index.html there turns that into an opaque "no composition found"
      // or a 600s frame-capture timeout instead of a diagnosable 404.
      if (path.extname(requestPath)) {
        response.writeHead(404).end(`Not found: ${requestPath}`);
        return;
      }
      filePath = path.join(distDir, "index.html");
      if (!fs.existsSync(filePath)) {
        response.writeHead(404).end("Vite build output is missing index.html");
        return;
      }
    }
    response.writeHead(200, {"Content-Type": MIME_TYPES[path.extname(filePath)] || "application/octet-stream"});
    // Both halves of the pipe need an error listener: the read stream can fail on
    // a truncated build, and the response emits errors when Chromium aborts a
    // request mid-stream. An unhandled one there would take down the renderer.
    const body = fs.createReadStream(filePath);
    response.on("error", () => body.destroy());
    body.on("error", () => response.destroy()).pipe(response);
  });
  const url = await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("Unable to determine local render server port"));
        return;
      }
      resolve(`http://127.0.0.1:${address.port}`);
    });
  });
  return {server, url};
}

// ─── Stills 导出（H3 流水线）───
// 每个场景导出 presenter 开/关两张 PNG：
//   <scene-id>-combined.png     立绘 + 舞台（给 H3 做构图参考 Picture 1）
//   <scene-id>-clean-plate.png  同一舞台无立绘（最终合成的确定性底）
// clean-plate 通过 presenter.forceHidden 只藏立绘图层、不动硬车道布局，
// 两张图的文字/数据位置才逐像素对齐（h3-presenter-pipeline.md 的镜头包契约）。

async function exportStills(timelinePath, stillsDir, publicDir, {firstFrameMode = false} = {}) {
  const timeline = JSON.parse(fs.readFileSync(timelinePath, "utf8"));
  const scenes = Array.isArray(timeline.scenes) ? timeline.scenes : [];
  if (scenes.length === 0) {
    throw new Error("Timeline must contain at least one scene");
  }
  // 输入校验前置（对齐视频模式对 startMs 的姿态）：非数值 startMs/durationMs 会算出
  // NaN 帧号，所有 Sequence 在 NaN 帧上隐形 —— 截出一堆空白底图还报告 ok。
  const seenIds = new Set();
  scenes.forEach((scene, index) => {
    if (!scene || typeof scene.id !== "string" || !SCENE_ID_RE.test(scene.id)) {
      throw new Error(`Scene ${index} has an invalid id (expected kebab-case): ${scene?.id}`);
    }
    if (seenIds.has(scene.id)) {
      throw new Error(`Duplicate scene.id: ${scene.id}`);
    }
    seenIds.add(scene.id);
    if (!Number.isFinite(scene.startMs) || scene.startMs < 0) {
      throw new Error(`Scene ${scene.id} has an invalid startMs: ${scene.startMs}`);
    }
    if (!Number.isFinite(scene.durationMs) || scene.durationMs <= 0) {
      throw new Error(`Scene ${scene.id} has an invalid durationMs: ${scene.durationMs}`);
    }
  });
  let publicRoot;
  try {
    publicRoot = fs.realpathSync(path.resolve(publicDir));
  } catch {
    throw new Error(`Public directory does not exist: ${publicDir}`);
  }
  if (!timeline.presenter) {
    process.stderr.write("[stills] timeline has no presenter; combined and clean-plate will be identical\n");
  }
  const fps = timeline.fps || 30;
  const config = {width: timeline.width || 1080, height: timeline.height || 1920, fps};
  // 手写时间线的 totalDurationMs 可能与末场景终点不齐：把帧号钳进总时长，越界帧上同样所有图层隐形。
  const maxFrame = Number.isFinite(timeline.totalDurationMs) && timeline.totalDurationMs > 0
    ? Math.max(0, Math.ceil((timeline.totalDurationMs / 1000) * fps) - 1)
    : Infinity;
  // 取场景 2/3 处的帧：揭示动画（前 40%）与 marker 弹簧已稳定，场景淡出（末 9 帧）未开始。
  // --first-frame（Seedance 图生视频）：Seedance 会把整段画面冻结在首帧布局上，
  // 因此必须喂"揭示完成后"的稳定帧（50% 处）。起点帧上标题/图表还在入场动画中
  // （甚至 opacity 0），生成视频里 UI 会整段不完整。
  const frameForScene = (scene) => {
    const atMs = firstFrameMode
      ? scene.startMs + scene.durationMs / 2
      : scene.startMs + (scene.durationMs * 2) / 3;
    return Math.min(maxFrame, Math.max(0, Math.round((atMs / 1000) * fps)));
  };
  const tmpDir = path.join(stillsDir, "temp");
  const distDir = path.join(tmpDir, "vite-dist");
  let server;
  let url;
  const stills = [];
  try {
    fs.mkdirSync(stillsDir, { recursive: true });
    ensureChromiumPath();
    buildRenderer(distDir);
    ({server, url} = await startAssetServer(distDir, publicRoot));
    const browser = await chromium.launch({
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
      args: ["--disable-dev-shm-usage", "--disable-setuid-sandbox", "--no-sandbox"],
    });
    try {
      // 页面复用：同一 variant 的 inputProps 跨场景完全相同、只有帧号变，
      // 按 renderFrames 的换帧路径（frame-update 事件）切换，省掉每张静帧一次完整页面加载。
      for (const variant of ["combined", "clean-plate"]) {
        const inputProps =
          variant === "clean-plate" && timeline.presenter
            ? {...timeline, presenter: {...timeline.presenter, forceHidden: true}}
            : timeline;
        const page = await openStillPage({browser, url, config, frame: frameForScene(scenes[0]), inputProps});
        let currentFrame = frameForScene(scenes[0]);
        try {
          for (const scene of scenes) {
            const frame = frameForScene(scene);
            // 帧号与页面当前帧相同就不能派发 frame-update：React 对相同值的 setState
            // 会 bail out 且不重跑 effect，READY 永远回不到 true → waitForFunction
            // 60s 超时。库的 renderFrames 同样只对首帧之后的帧走换帧路径。
            if (frame !== currentFrame) {
              await seekStillFrame({page, config, frame});
              currentFrame = frame;
            }
            const file = path.join(stillsDir, `${scene.id}-${variant}.png`);
            await page.screenshot({path: file, type: "png"});
            stills.push({sceneId: scene.id, variant, frame, path: file});
            process.stderr.write(`[stills] ${scene.id} ${variant} (frame ${frame}) -> ${file}\n`);
          }
        } finally {
          // close 失败（浏览器已崩溃等）不应掩盖渲染的真实错误
          await page.close().catch(() => {});
        }
      }
    } finally {
      await browser.close().catch(() => {});
    }
  } finally {
    // 同主流程：不 await close()，直接断连后关闭，避免悬挂请求拖死清理。
    try {
      server?.closeAllConnections?.();
      server?.close();
    } catch {}
    try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch {}
  }
  const report = {status: "ok", width: config.width, height: config.height, fps, stills};
  process.stdout.write(JSON.stringify(report, null, 2) + "\n");
}

// 打开一个 stills 页面：首帧走完整加载（init script 注入时间劫持 + inputProps，
// 等 READY 且 delayRender 清零）。inputProps 不同的渲染必须开新 page。
async function openStillPage({browser, url, config, frame, inputProps}) {
  const page = await browser.newPage({viewport: {width: config.width, height: config.height}});
  page.setDefaultTimeout(60000);
  page.setDefaultNavigationTimeout(60000);
  try {
    await page.addInitScript(({frame, fps, hijackScript, inputProps}) => {
      window.__OPEN_MOTION_FRAME__ = frame;
      window.__OPEN_MOTION_COMPOSITION_ID__ = "ArticleVideo";
      window.__OPEN_MOTION_INPUT_PROPS__ = inputProps;
      window.__OPEN_MOTION_READY__ = false;
      window.__OPEN_MOTION_VIDEO_FRAMES__ = {};
      const script = document.createElement("script");
      script.textContent = hijackScript;
      document.documentElement.appendChild(script);
      script.remove();
      // 保证 #root 占满整个视口，但不添加 flex center 避免影响内部组件布局
      const style = document.createElement("style");
      style.textContent = "body, html { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; } #root { width: 100%; height: 100%; display: block; }";
      document.head.appendChild(style);
    }, {frame, fps: config.fps, hijackScript: getTimeHijackScript(frame, config.fps), inputProps});
    await page.goto(url);
    await page.waitForFunction(() => {
      const ready = window.__OPEN_MOTION_READY__ === true;
      const delayCount = window.__OPEN_MOTION_DELAY_RENDER_COUNT__ || 0;
      return ready && delayCount === 0;
    }, undefined, {timeout: 60000});
    await page.waitForLoadState("networkidle");
    // 首帧不走 seekStillFrame（同帧重复派发会挂死，见调用方注释），稳定等待放在这里。
    await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 150)));
    await new Promise((resolve) => setTimeout(resolve, 100));
    return page;
  } catch (error) {
    await page.close().catch(() => {});
    throw error;
  }
}

// 换帧：复刻 @open-motion/renderer 的 frame-update 路径（READY 置否 → 重设帧 →
// 重放时间劫持 → 派发事件），等 ready + delayRender 清零后再交给调用方截图。
async function seekStillFrame({page, config, frame}) {
  await page.evaluate(({frame, fps, hijackScript}) => {
    window.__OPEN_MOTION_READY__ = false;
    window.__OPEN_MOTION_FRAME__ = frame;
    window.__OPEN_MOTION_VIDEO_ASSETS__ = [];
    eval(hijackScript);
    window.dispatchEvent(new CustomEvent("open-motion-frame-update", { detail: { frame } }));
  }, {frame, fps: config.fps, hijackScript: getTimeHijackScript(frame, config.fps)});
  await page.waitForFunction(() => {
    const ready = window.__OPEN_MOTION_READY__ === true;
    const delayCount = window.__OPEN_MOTION_DELAY_RENDER_COUNT__ || 0;
    return ready && delayCount === 0;
  }, undefined, {timeout: 60000});
  // 换到新场景可能首次触发该场景的懒加载资产：有界等待网络静默，超时不致命。
  await page.waitForLoadState("networkidle", {timeout: 5000}).catch(() => {});
  // 与 renderFrames 相同的稳定等待，避免字体/布局未收敛就截图
  await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 150)));
  await new Promise((resolve) => setTimeout(resolve, 100));
}
