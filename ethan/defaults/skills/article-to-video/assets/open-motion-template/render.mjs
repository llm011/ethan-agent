import { getCompositions, renderFrames } from "@open-motion/renderer";
import { chromium } from "playwright";
import { execFileSync, execSync, spawn } from "node:child_process";
import fs from "node:fs";
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

// ── Derive output paths ──
const renderDir = path.dirname(outputPath);
const tmpDir = path.join(renderDir, "temp");
const distDir = path.join(tmpDir, "vite-dist");

// ── 1. Ensure Playwright browsers are installed ──
process.stderr.write("[Step 1/5] Checking Playwright browsers...\n");
try {
  chromium.executablePath();
  process.stderr.write("[Step 1/5] Playwright OK\n");
} catch {
  process.stderr.write("[Step 1/5] Installing Playwright Chromium...\n");
  execSync("npx playwright install chromium", { cwd: __dirname, stdio: "inherit" });
}

// ── 2. Vite build ──
process.stderr.write("[Step 2/5] Building with Vite...\n");
fs.mkdirSync(distDir, { recursive: true });
execSync(`npx vite build --outDir "${distDir}"`, { cwd: __dirname, stdio: "inherit" });
process.stderr.write("[Step 2/5] Vite build done\n");

// ── 3. Start http-server to serve dist/ ──
const PORT = 10000 + Math.floor(Math.random() * 5000);
const url = `http://127.0.0.1:${PORT}`;
let server;

try {
  server = spawn("npx", ["http-server", distDir, "-p", String(PORT), "-a", "127.0.0.1", "--cors", "-s"],
    { cwd: __dirname, stdio: "ignore", detached: true });
  server.unref();

  // Wait for server to be ready
  await new Promise((resolve, reject) => {
    const deadline = Date.now() + 10_000;
    const check = async () => {
      if (Date.now() > deadline) {
        reject(new Error(`http-server not ready on port ${PORT} within 10s`));
        return;
      }
      try {
        const res = await fetch(url);
        if (res.ok) { resolve(); return; }
      } catch {}
      setTimeout(check, 200);
    };
    check();
  });

  // ── 4. Discover compositions ──
  process.stderr.write(`[Step 3/5] Discovering compositions from ${url}...\n`);
  process.stderr.write(`timeline scenes: ${timeline.scenes?.length}, totalDurationMs: ${timeline.totalDurationMs}\n`);
  const compositions = await getCompositions(url, { inputProps: timeline, timeout: 60000 });
  const comp = compositions.find((c) => c.id === "ArticleVideo");
  if (!comp) throw new Error(`No composition "ArticleVideo" found (got: ${compositions.map(c=>c.id).join(", ")})`);

  // Use timeline.json values for config — getCompositions may return defaults if calculateMetadata isn't invoked
  const fps = comp.fps || timeline.fps || 30;
  const config = {
    width: comp.width || timeline.width || 1080,
    height: comp.height || timeline.height || 1920,
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
  const audioAssets = result?.audioAssets || [];
  process.stderr.write(`[Step 4/5] Frames complete: ${config.durationInFrames}/${config.durationInFrames} (100%)\n`);

  // ── 6. Encode frames → MP4 with audio mixing ──
  const scenes = timeline.scenes || [];
  const audioEntries = []; // { inputIdx, path, delayMs }
  const filterParts = [];
  scenes.forEach((scene) => {
    const audioPath = path.join(publicDir, scene.audio);
    if (fs.existsSync(audioPath)) {
      // inputIdx starts at 1 because input 0 is the image sequence (no audio)
      const inputIdx = audioEntries.length + 1;
      const delayMs = Math.round(scene.startMs);
      filterParts.push(`[${inputIdx}:a]adelay=${delayMs}|${delayMs},asetpts=PTS-STARTPTS[a${audioEntries.length}]`);
      audioEntries.push({ inputIdx, path: audioPath, delayMs });
    }
  });

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
    audioAssets,
  };
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  process.stdout.write(JSON.stringify(report) + "\n");

} finally {
  // ── Cleanup: kill http-server + remove all temp files ──
  try { if (server?.pid) process.kill(-server.pid); } catch {}
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
