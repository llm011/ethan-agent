import {bundle} from "@remotion/bundler";
import {renderMedia, renderStill, selectComposition} from "@remotion/renderer";
import {readFile, stat, writeFile} from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import {fileURLToPath} from "node:url";

const [timelinePathArg, outputPathArg, coverPathArg, reportPathArg, publicDirArg] = process.argv.slice(2);
if (!timelinePathArg || !outputPathArg || !coverPathArg || !reportPathArg || !publicDirArg) {
  throw new Error("Usage: node render.mjs <timeline.json> <output.mp4> <cover.png> <report.json> <public-dir>");
}

const timelinePath = path.resolve(timelinePathArg);
const outputPath = path.resolve(outputPathArg);
const coverPath = path.resolve(coverPathArg);
const reportPath = path.resolve(reportPathArg);
const publicDir = path.resolve(publicDirArg);
const timeline = JSON.parse(await readFile(timelinePath, "utf8"));
const entryPoint = path.join(path.dirname(fileURLToPath(import.meta.url)), "src", "index.tsx");

const serveUrl = await bundle({
  entryPoint,
  publicDir,
  onProgress: (progress) => {
    // progress 是 0-1 的浮点数，直接 % 25 只有 0% 会触发；换算成整数百分比再取模。
    const percent = Math.round(progress * 100);
    if (percent % 25 === 0) process.stderr.write(`Bundling ${percent}%\n`);
  },
});

const composition = await selectComposition({
  serveUrl,
  id: "ArticleVideo",
  inputProps: timeline,
});

await renderMedia({
  composition,
  serveUrl,
  codec: "h264",
  audioCodec: "aac",
  outputLocation: outputPath,
  inputProps: timeline,
  pixelFormat: "yuv420p",
  crf: 20,
  overwrite: true,
  onProgress: ({progress}) => {
    const percent = Math.round(progress * 100);
    if (percent % 10 === 0) process.stderr.write(`Rendering ${percent}%\n`);
  },
});

const coverFrame = Math.min(composition.durationInFrames - 1, Math.max(0, Math.round(composition.fps * 1.2)));
await renderStill({
  composition,
  serveUrl,
  output: coverPath,
  inputProps: timeline,
  frame: coverFrame,
  imageFormat: "png",
  overwrite: true,
});

const video = await stat(outputPath);
const cover = await stat(coverPath);
const report = {
  status: "ok",
  composition: composition.id,
  width: composition.width,
  height: composition.height,
  fps: composition.fps,
  durationInFrames: composition.durationInFrames,
  expectedDurationMs: timeline.totalDurationMs,
  sceneCount: timeline.scenes.length,
  videoBytes: video.size,
  coverBytes: cover.size,
};
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
process.stdout.write(`${JSON.stringify(report)}\n`);
