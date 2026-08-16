import { getCompositions, renderFrames } from "@open-motion/renderer";
import { chromium } from "playwright";
import { execSync, spawn } from "node:child_process";
import fs from "node:fs";
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

// ── 1. Ensure Playwright browsers are installed ──
try {
  chromium.executablePath();
} catch {
  process.stderr.write("Installing Playwright Chromium...\n");
  execSync("npx playwright install chromium", { cwd: __dirname, stdio: "inherit" });
}

// ── 2. Vite build ──
process.stderr.write("Building with Vite...\n");
fs.mkdirSync(distDir, { recursive: true });
execSync(`npx vite build --outDir "${distDir}"`, { cwd: __dirname, stdio: "inherit" });

// ── 3. Start http-server to serve dist/ ──
const PORT = 10000 + Math.floor(Math.random() * 5000);
const server = spawn("npx", ["http-server", distDir, "-p", String(PORT), "-a", "127.0.0.1", "--cors", "-s"],
  { cwd: __dirname, stdio: "ignore", detached: true });
server.unref();

// Wait for server to be ready
await new Promise((resolve) => {
  const check = async () => {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/`);
      if (res.ok) { resolve(); return; }
    } catch {}
    setTimeout(check, 200);
  };
  check();
});

const url = `http://127.0.0.1:${PORT}`;
const renderDir = path.dirname(outputPath);
const tmpDir = path.join(renderDir, "temp");
const distDir = path.join(tmpDir, "vite-dist");

try {
  // ── 4. Discover compositions ──
  process.stderr.write(`Fetching compositions from ${url}...\n`);
  process.stderr.write(`timeline scenes: ${timeline.scenes?.length}, totalDurationMs: ${timeline.totalDurationMs}\n`);
  const compositions = await getCompositions(url, { inputProps: timeline, timeout: 60000 });
  const comp = compositions.find((c) => c.id === "ArticleVideo") || compositions[0];
  if (!comp) throw new Error("No composition found — ArticleVideo not registered");

  // Use timeline.json values for config — getCompositions may return defaults if calculateMetadata isn't invoked
  const config = {
    width: comp.width || timeline.width || 1080,
    height: comp.height || timeline.height || 1920,
    fps: comp.fps || timeline.fps || 30,
    durationInFrames: Math.max(1, Math.ceil(((timeline.totalDurationMs || 3000) / 1000) * (timeline.fps || 30))),
  };
  process.stderr.write(`Rendering ${comp.id} (${config.width}x${config.height}, ${config.fps}fps, ${config.durationInFrames} frames)\n`);

  // ── 5. Render frames (Playwright screenshots) ──
  const { audioAssets } = await renderFrames({
    url,
    config,
    outputDir: tmpDir,
    compositionId: comp.id,
    inputProps: timeline,
    concurrency: Math.min(9, Math.max(1, Math.floor((require("os").cpus().length || 4) / 2))),
    publicDir,
    timeout: 600000,
    onProgress: (frame) => {
      const pct = Math.round((frame / config.durationInFrames) * 100);
      if (pct % 10 === 0) process.stderr.write(`Rendering frame ${frame}/${config.durationInFrames} (${pct}%)\n`);
    },
  });

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
    filterParts.push(`${mixInputs}amix=inputs=${audioEntries.length}:duration=longest[aout]`);
    const filterComplex = filterParts.join(";");

    process.stderr.write("Encoding MP4 with FFmpeg (video + audio)...\n");
    execSync(
      `ffmpeg -y -framerate ${config.fps} -i "${tmpDir}/frame-%05d.png" ${audioInputArgs.join(" ")} -filter_complex "${filterComplex}" -map 0:v -map "[aout]" -c:v libx264 -pix_fmt yuv420p -crf 20 -c:a aac -b:a 128k "${outputPath}"`,
      { stdio: "inherit" },
    );
  } else {
    process.stderr.write("Encoding MP4 with FFmpeg (video only, no audio files found)...\n");
    execSync(
      `ffmpeg -y -framerate ${config.fps} -i "${tmpDir}/frame-%05d.png" -c:v libx264 -pix_fmt yuv420p -crf 20 "${outputPath}"`,
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
  try { process.kill(-server.pid); } catch {}
  // Remove rendered frames
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch {}
  // Remove Vite build output
  try { fs.rmSync(distDir, { recursive: true, force: true }); } catch {}
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
