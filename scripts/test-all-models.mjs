#!/usr/bin/env node
/**
 * BytePlus gateway smoke test（Seedance 2.0 实验配套）
 *
 * 端点与密钥一律来自 ~/.ethan/config.yaml 的 seedance 段（或 ETHAN_DATA_DIR 指向的
 * config.yaml），代码里绝不出现任何 endpoint ID / API key。环境变量可覆盖：
 *   BYTEPLUS_GATEWAY_URL / BYTEPLUS_GATEWAY_API_KEY / BYTEPLUS_EDGE_SECRET
 *
 * 测试 config 里配置的全部模型：chat 1 个、image 全部、video 全部。
 * 协议来源（BytePlus ModelArk 官方文档）：
 *   POST /chat/completions            https://docs.byteplus.com/en/docs/ModelArk/1494384
 *   POST /images/generations          https://docs.byteplus.com/en/docs/ModelArk/1541523
 *   POST /contents/generations/tasks  https://docs.byteplus.com/en/docs/ModelArk/1520757
 *   GET  /contents/generations/tasks/{id}  https://docs.byteplus.com/en/docs/ModelArk/1521309
 *
 * 这些是真实推理请求，会产生 BytePlus 费用。脚本永不打印密钥。
 *
 * Usage:
 *   node scripts/test-all-models.mjs --dry-run   只打印将要发出的请求，不联网
 *   node scripts/test-all-models.mjs             跑完提交类请求即算通过
 *   node scripts/test-all-models.mjs --poll      轮询视频任务到终态并下载 mp4
 */

import {createWriteStream, readFileSync} from "node:fs";
import {mkdir, writeFile} from "node:fs/promises";
import {homedir} from "node:os";
import {resolve} from "node:path";
import {Readable} from "node:stream";
import {pipeline} from "node:stream/promises";

const shouldPoll = process.argv.includes("--poll");
const dryRun = process.argv.includes("--dry-run");

// ── config.yaml 的 seedance 段（极简解析：一层 key:value + models 嵌套） ──

function parseSeedanceSection(text) {
  const section = {};
  let inSection = false;
  let sectionIndent = 0;
  let nestedKey = null;
  let nestedIndent = 0;
  for (const line of text.split("\n")) {
    if (!line.trim() || line.trim().startsWith("#")) continue;
    const indent = line.length - line.trimStart().length;
    const stripped = line.trim();
    if (!inSection) {
      if (stripped === "seedance:") {
        inSection = true;
        sectionIndent = indent;
      }
      continue;
    }
    if (indent <= sectionIndent) break;
    const sepIndex = stripped.indexOf(":");
    if (sepIndex < 0) continue;
    const key = stripped.slice(0, sepIndex).trim();
    let rest = stripped.slice(sepIndex + 1).trim();
    if (!key) continue;
    if (!rest) {
      nestedKey = key;
      nestedIndent = indent;
      section[key] = {};
      continue;
    }
    if (nestedKey !== null && indent > nestedIndent) {
      section[nestedKey][key] = stripValue(rest);
      continue;
    }
    nestedKey = null;
    section[key] = stripValue(rest);
  }
  return section;
}

function stripValue(raw) {
  let value = raw;
  const commentIndex = value.indexOf(" #");
  if (commentIndex >= 0) value = value.slice(0, commentIndex);
  value = value.trim();
  if (
    value.length >= 2 &&
    ((value.startsWith("'") && value.endsWith("'")) ||
      (value.startsWith('"') && value.endsWith('"')))
  ) {
    value = value.slice(1, -1);
  }
  return value.trim();
}

function loadConfig() {
  const dataDir = process.env.ETHAN_DATA_DIR;
  const configPath = resolve(dataDir || resolve(homedir(), ".ethan"), "config.yaml");
  let raw = {};
  try {
    raw = parseSeedanceSection(readFileSync(configPath, "utf8"));
  } catch {
    raw = {};
  }
  const gatewayUrl = (process.env.BYTEPLUS_GATEWAY_URL || raw.gateway_url || "").replace(/\/$/, "");
  const gatewayApiKey = process.env.BYTEPLUS_GATEWAY_API_KEY || raw.api_key || "";
  const edgeSecret = process.env.BYTEPLUS_EDGE_SECRET || raw.edge_secret || "";
  const models = raw.models || {};
  if (!gatewayUrl || !gatewayApiKey || !edgeSecret) {
    console.error("缺少网关配置：config.yaml 的 seedance 段需要 gateway_url/api_key/edge_secret（或用 BYTEPLUS_GATEWAY_URL / BYTEPLUS_GATEWAY_API_KEY / BYTEPLUS_EDGE_SECRET 环境变量覆盖）。");
    process.exit(2);
  }
  return {gatewayUrl, gatewayApiKey, edgeSecret, models};
}

// ── 测试定义：模型 endpoint 全部来自 config.models ──

const PROMPTS = {
  chat: "Reply with exactly: gateway chat ok",
  image: "A small red cube on a clean white studio background",
  imageAlt: "A small blue sphere on a clean white studio background",
  video: "A red ball slowly rolling across a clean white studio floor",
  videoFast: "A blue paper airplane gliding through a bright studio",
  videoMini: "A yellow toy car moving slowly across a wooden table",
};

function buildTests(models) {
  const tests = [];
  if (models.chat) {
    tests.push({
      name: "Chat", fileBase: "chat", kind: "chat", path: "/chat/completions", timeoutMs: 120_000,
      body: {
        model: models.chat,
        messages: [{role: "user", content: PROMPTS.chat}],
        max_tokens: 30, stream: false,
      },
    });
  }
  for (const [key, label] of [["image", "Image"], ["image_alt", "Image alt"]]) {
    if (!models[key]) continue;
    tests.push({
      name: `${label} (${key})`, fileBase: key, kind: "image", path: "/images/generations",
      timeoutMs: 300_000,
      body: {
        model: models[key],
        prompt: key === "image" ? PROMPTS.image : PROMPTS.imageAlt,
        size: "2K", response_format: "url", output_format: "png", watermark: false,
      },
    });
  }
  const videoBody = (model, prompt) => ({
    model, content: [{type: "text", text: prompt}], duration: 5, resolution: "720p",
    ratio: "16:9", generate_audio: false, watermark: false,
  });
  for (const [key, label] of [["video", "Video"], ["video_fast", "Video fast"], ["video_mini", "Video mini"]]) {
    if (!models[key]) continue;
    const prompt = key === "video" ? PROMPTS.video : key === "video_fast" ? PROMPTS.videoFast : PROMPTS.videoMini;
    tests.push({
      name: `${label} (${key})`, fileBase: key, kind: "video", path: "/contents/generations/tasks",
      timeoutMs: 120_000, body: videoBody(models[key], prompt),
    });
  }
  if (tests.length === 0) {
    console.error("config.yaml seedance.models 里一个模型都没配。");
    process.exit(2);
  }
  return tests;
}

// ── 网关请求 ──

const config = loadConfig();

function requestHeaders() {
  return {
    Authorization: `Bearer ${config.gatewayApiKey}`,
    "x-byteplus-gateway-secret": config.edgeSecret,
    "Content-Type": "application/json",
  };
}

async function gatewayRequest(path, options, timeoutMs) {
  const response = await fetch(`${config.gatewayUrl}${path}`, {
    ...options, headers: requestHeaders(), signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  return {response, data};
}

function resultLooksValid(kind, data) {
  if (!data || typeof data !== "object") return false;
  if (kind === "chat") return typeof data.choices?.[0]?.message?.content === "string";
  if (kind === "image") return Array.isArray(data.data) && data.data.length > 0;
  return typeof taskIdFrom(data) === "string";
}

function taskIdFrom(data) {
  return data?.id ?? data?.task_id ?? data?.data?.id ?? data?.data?.task_id;
}

function shortResult(data) {
  const serialized = typeof data === "string" ? data : JSON.stringify(data);
  return serialized.length > 600 ? `${serialized.slice(0, 600)}…` : serialized;
}

// ── 主流程 ──

const tests = buildTests(config.models);
const runId = new Date().toISOString().replace(/[:.]/g, "-");
const outputDir = resolve(process.env.BYTEPLUS_TEST_OUTPUT_DIR || "test-output", runId);
const videoTasks = [];
let failures = 0;

await mkdir(outputDir, {recursive: true});
console.log(`Gateway: ${config.gatewayUrl}`);
console.log(`Mode: ${dryRun ? "dry-run (不联网)" : shouldPoll ? "real + poll" : "real"}`);
console.log(`Output directory: ${outputDir}`);
console.log(`Starting model smoke tests (${tests.length} tests)...\n`);

for (const test of tests) {
  const startedAt = Date.now();
  if (dryRun) {
    console.log(`PLAN  ${test.name}  POST ${test.path}`);
    console.log(`      ${JSON.stringify(test.body)}`);
    continue;
  }
  try {
    const {response, data} = await gatewayRequest(test.path, {method: "POST", body: JSON.stringify(test.body)}, test.timeoutMs);
    const elapsedMs = Date.now() - startedAt;
    if (response.ok && resultLooksValid(test.kind, data)) {
      console.log(`PASS  ${test.name}  HTTP ${response.status}  ${elapsedMs}ms`);
      if (test.kind === "chat") {
        const content = data.choices[0].message.content;
        const outputPath = resolve(outputDir, `${test.fileBase}.txt`);
        await writeFile(outputPath, `${content}\n`, "utf8");
        console.log(`      ${content}`);
      } else if (test.kind === "image") {
        console.log(`      returned ${data.data.length} image result(s)`);
        for (const outputPath of await saveImages(data.data, test.fileBase)) console.log(`      saved ${outputPath}`);
      } else {
        const taskId = taskIdFrom(data);
        console.log(`      task=${taskId}`);
        videoTasks.push({name: test.name, fileBase: test.fileBase, taskId});
      }
    } else {
      failures += 1;
      console.error(`FAIL  ${test.name}  HTTP ${response.status}  ${elapsedMs}ms`);
      console.error(`      ${shortResult(data)}`);
    }
  } catch (error) {
    failures += 1;
    console.error(`FAIL  ${test.name}  ${error instanceof Error ? error.message : error}`);
  }
  console.log("");
}

if (dryRun) {
  console.log(`Dry run finished: ${tests.length} test(s) planned, no requests sent.`);
  process.exitCode = 0;
} else {
  if (shouldPoll && videoTasks.length > 0) {
    console.log("Polling submitted video tasks...\n");
    const pollResults = await Promise.all(videoTasks.map(pollVideoTask));
    failures += pollResults.filter((passed) => !passed).length;
  }
  console.log(`Finished: ${tests.length - failures}/${tests.length} model tests passed.`);
  console.log(`Files: ${outputDir}`);
  process.exitCode = failures === 0 ? 0 : 1;
}

async function pollVideoTask({name, fileBase, taskId}) {
  const deadline = Date.now() + 15 * 60_000;
  while (Date.now() < deadline) {
    try {
      const {response, data} = await gatewayRequest(
        `/contents/generations/tasks/${encodeURIComponent(taskId)}`, {method: "GET"}, 30_000,
      );
      if (!response.ok) {
        console.error(`FAIL  ${name} poll  HTTP ${response.status}: ${shortResult(data)}`);
        return false;
      }
      const status = String(data?.status ?? data?.data?.status ?? "").toLowerCase();
      console.log(`WAIT  ${name}  task=${taskId}  status=${status || "unknown"}`);
      if (["succeeded", "success", "completed", "complete", "done"].includes(status)) {
        const videoUrl = videoUrlFrom(data);
        if (!videoUrl) {
          console.error(`FAIL  ${name} completed but no video URL: ${shortResult(data)}\n`);
          return false;
        }
        const outputPath = resolve(outputDir, `${fileBase}.mp4`);
        await downloadFile(videoUrl, outputPath, 10 * 60_000);
        console.log(`PASS  ${name} completed`);
        console.log(`      saved ${outputPath}\n`);
        return true;
      }
      if (["failed", "error", "cancelled", "canceled", "expired"].includes(status)) {
        console.error(`FAIL  ${name} terminal status=${status}: ${shortResult(data)}\n`);
        return false;
      }
    } catch (error) {
      console.error(`FAIL  ${name} poll: ${error instanceof Error ? error.message : error}\n`);
      return false;
    }
    await new Promise((resolve_) => setTimeout(resolve_, 10_000));
  }
  console.error(`FAIL  ${name} poll timed out after 15 minutes\n`);
  return false;
}

async function saveImages(images, fileBase) {
  const outputPaths = [];
  for (let index = 0; index < images.length; index += 1) {
    const image = images[index];
    const suffix = images.length === 1 ? "" : `-${index + 1}`;
    const outputPath = resolve(outputDir, `${fileBase}${suffix}.png`);
    if (typeof image?.url === "string" && image.url) {
      await downloadFile(image.url, outputPath, 5 * 60_000);
    } else if (typeof image?.b64_json === "string" && image.b64_json) {
      await writeFile(outputPath, Buffer.from(image.b64_json, "base64"));
    } else {
      throw new Error(`Image ${index + 1} did not contain url or b64_json`);
    }
    outputPaths.push(outputPath);
  }
  return outputPaths;
}

function videoUrlFrom(data) {
  const root = data?.data ?? data?.task ?? data;
  const content = Array.isArray(root?.content) ? root.content : root?.content ? [root.content] : [];
  const candidates = [root, root?.video, root?.result, root?.result?.video, ...content];
  for (const candidate of candidates) {
    if (!candidate || typeof candidate !== "object") continue;
    for (const key of ["video_url", "output_video_url", "url"]) {
      if (typeof candidate[key] === "string" && candidate[key]) return candidate[key];
    }
  }
  return null;
}

async function downloadFile(url, outputPath, timeoutMs) {
  const response = await fetch(url, {signal: AbortSignal.timeout(timeoutMs)});
  if (!response.ok || !response.body) {
    throw new Error(`Download failed with HTTP ${response.status}`);
  }
  await pipeline(Readable.fromWeb(response.body), createWriteStream(outputPath));
}
