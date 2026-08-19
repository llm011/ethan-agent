import { getCompositions, renderFrames } from "@open-motion/renderer";
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ── CLI arguments (same contract as before: 5 positional args) ──
const [timelinePathArg, outputPathArg, coverPathArg, reportPathArg, publicDirArg] = process.argv.slice(2);
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

// ── 1. Ensure Playwright browsers are installed ──
process.stderr.write("[Step 1/5] Checking Playwright browsers...\n");
const configuredChromiumPath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH?.trim();
const isBrowserFile = (candidate) => {
  if (!candidate) return false;
  try {
    return fs.statSync(candidate).isFile();
  } catch {
    return false;
  }
};
let chromiumPath = configuredChromiumPath;
if (configuredChromiumPath) {
  if (!isBrowserFile(configuredChromiumPath)) {
    throw new Error(`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH is not a file: ${configuredChromiumPath}`);
  }
  process.stderr.write("[Step 1/5] Playwright OK (configured executable)\n");
} else {
  try {
    chromiumPath = chromium.executablePath();
  } catch {
    chromiumPath = null;
  }
  if (isBrowserFile(chromiumPath)) {
    process.stderr.write("[Step 1/5] Playwright OK (cached)\n");
  } else {
    process.stderr.write("[Step 1/5] Installing Playwright Chromium...\n");
    execFileSync("npx", ["playwright", "install", "chromium"], { cwd: __dirname, stdio: "inherit" });
    chromiumPath = chromium.executablePath();
    if (!isBrowserFile(chromiumPath)) {
      throw new Error(`Playwright Chromium install completed but executable is missing: ${chromiumPath}`);
    }
  }
}

// ── 2. Vite build ──
process.stderr.write("[Step 2/5] Building with Vite...\n");
fs.mkdirSync(distDir, { recursive: true });
execFileSync("npx", ["vite", "build", "--outDir", distDir], { cwd: __dirname, stdio: "inherit" });
process.stderr.write("[Step 2/5] Vite build done\n");

// ── 3. Serve dist/ on an OS-assigned loopback port ──
// A random fixed port can collide with an existing local process. Using port 0
// lets the kernel choose an available port, and avoids depending on http-server.
const MIME_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};
let server;
let url;

try {
  server = http.createServer((request, response) => {
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
    const isFile = (() => {
      try {
        return fs.statSync(filePath).isFile();
      } catch {
        return false;
      }
    })();
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
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      const address = server.address();
      if (!address || typeof address === "string") {
        reject(new Error("Unable to determine local render server port"));
        return;
      }
      url = `http://127.0.0.1:${address.port}`;
      resolve();
    });
  });

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

  if (audioEntries.length > 0) {
    const encodedDurationSec = config.durationInFrames / config.fps;
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
    const encodedDurationSec = config.durationInFrames / config.fps;
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
  const durationSec = Math.round((config.durationInFrames / config.fps) * 1000) / 1000;
  const expectedDurationSec = Math.round(
    ((timeline.totalDurationMs || config.durationInFrames * 1000 / config.fps) / 1000) * 1000,
  ) / 1000;
  const report = {
    status: "ok",
    composition: comp.id,
    width: config.width,
    height: config.height,
    fps: config.fps,
    durationInFrames: config.durationInFrames,
    expectedDurationMs: timeline.totalDurationMs,
    expectedDurationSec,
    sceneCount: timeline.scenes?.length || 0,
    durationSec,
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
