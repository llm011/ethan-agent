# 读书笔记 → 动态视频（Book to Video）

把已生成的**深度听书交付物**（飞书笔记 + MP3 + 字幕）进一步升级成**动态视频**。核心是：**用音频旁白驱动字幕 + 章节洞察标题 + 简约背景动效**，做成可播放、可分享的横版视频。

> 目标场景：用户想要「把读书笔记做成视频」，而非静态文档。输入是 book-audio-digest 已产出的 `final.mp3` + `subtitles.srt`。

---

## 一、素材准备（全链路复用）

做视频**不需要重新采集**书籍信息，直接用 book-audio-digest 的产物：

| 素材 | 来源 | 用途 |
|------|------|------|
| 配音 | `final.mp3` | 视频音轨（旁白） |
| 字幕 | `subtitles.srt` | 逐句显示当前旁白 |
| 章节标题 | `manifest.json` 的 `sections[]` | 每个章节的大标题/副标题/关键词 |
| 补充 | book-info（简介/章节/点评）+ 知识库 | 提炼核心洞察，做标题文案 |

**关键顺序**：先用 `book-audio-digest` 跑出 MP3 和 SRT（这一步稳定、快），再做视频。视频只是把已有音频「可视化」，不重新发明内容。

---

## 二、open-motion 视频设计（已验证可行的骨架）

### 1. 双容器结构（必须）
- **音频旁白**：`<Audio src="/audio.mp3" />`——open-motion 会自动把它混进成片音轨（见「三、坑点」）
- **字幕**：`parseSrt()` 解析 SRT，按秒匹配当前段落
- **章节标题**：一个 `SECTIONS[]` 数组 + `SECTION_WINDOWS[]`（每章的起止秒），用当前秒 `frame/fps` 找当前章节

### 2. 核心代码骨架（只列关键逻辑）

```tsx
// 异步加载字幕（截图前必须就绪）
const useSubtitles = () => {
  const [subs, setSubs] = React.useState(null);
  React.useEffect(() => {
    const handle = delayRender('loading srt');
    fetch('/subs.srt')
      .then(r => r.text())
      .then(text => { setSubs(parseSrt(text)); continueRender(handle); });
    return () => continueRender(handle);
  }, []);
  return subs;
};

// 当前章节：按当前秒找 window
const currentSectionIndex = (t) => {
  for (let i = 0; i < SECTION_WINDOWS.length; i++)
    if (t >= SECTION_WINDOWS[i].start && t < SECTION_WINDOWS[i].end) return i;
  return SECTION_WINDOWS.length - 1;
};

// 主组件：frame/fps = 当前秒，驱动一切
const t = frame / fps;
const secIdx = currentSectionIndex(t);
const currentSub = subs?.find(s => t >= s.start && t < s.end);
```

### 3. 视觉原则
- **单一焦点**：每个场景只突出「一个章节标题」，字幕在下、标题居中，别堆砌
- **标题动画**：`spring()` 弹入 + `interpolate()` 淡入，避免 CSS transition（逐帧截图不认）
- **背景**：深色渐变 + 中心光晕呼吸（`sin(frame/60)` 脉动），保证字幕可读
- **字体**：必须用 Noto Sans CJK SC（`fontFamily` 不设也行——系统有中文字体时默认就能渲染中文）

---

## 三、坑点记录（通用，与 Chromium 环境无关）

### 1. ⭐ ffmpeg 音频混流会失败（CLI bug）
**现象**：`open-motion render` 帧渲染成功（`Frame rendering complete`），但 `FFmpeg exited with code 234: Conversion failed`。

**根因**：CLI 的 `encodeVideo` 把音频用 `-c:a libvorbis` 编码后塞进 **MP4 容器**。`vorbis` 是 WebM/OGG 标准编码，**MP4 不兼容 vorbis**，导致 ffmpeg 报错。

**解法（两步绕开）**：
1. 先渲一段**不带音频**的无声视频：写组件时**先注释掉 `<Audio>`**，渲染出 `video_noaudio.mp4`
2. 用 ffmpeg 单独把 MP3 叠上去（AAC 兼容 MP4）：
   ```bash
   ffmpeg -y -i video_noaudio.mp4 -i final.mp3 \
     -c:v copy -c:a aac -b:a 192k -shortest video_final.mp4
   ```

**验证帧是否正常的方法**：手动拿帧目录里的 PNG 编一次（证明帧没问题）：
```bash
ffmpeg -y -framerate 30 -i .open-motion-tmp/frame-%05d.png -c:v libx264 -pix_fmt yuv420p /tmp/test.mp4
```
如果这一步成功而 open-motion 自带渲染失败，100% 是音频 vorbis 问题。

> 备选：也可以让 open-motion 输出 `.webm`（vorbis 兼容 webm），但那不一定好分享。

### 2. ⭐ Composition 发现与分辨率
- CLI 用 `getCompositions()` 枚举页面上的 `<Composition>`。**必须**把 `<Composition id="main" component={...} {...config}>` 用 `registerComposition` 或显式放在可枚举的位置，否则 CLI fallback 到默认 1280×720。
- 显式传参最稳：`open-motion render ... --composition main`，并且 `main.tsx` 里的 `config`（width/height/fps/durationInFrames）要和视频一致。

### 3. ⭐ 中文字体是硬的（缺了变方块）
- 无 GUI Linux 服务器默认**没有中文字体**（`fc-list :lang=zh` 返回 0）。headless Chromium 渲染中文会全变方块。
- 解法：安装 `fonts-noto-cjk`：
  ```bash
  apt-get install -y fonts-noto-cjk
  fc-cache -f
  ```
- **验证**：`fc-list :lang=zh` 能看到 Noto Sans CJK SC 才算 OK。

### 4. ⭐ 时长对齐
- `parseSrt` 返回 `{id, startInSeconds, endInSeconds, text}`，**单位是秒**（不是帧）。
- composition 的 `durationInFrames = 音频总秒数 × fps`。用 `getAudioDuration('/audio.mp3')` 动态算最稳（`calculateMetadata`）。
- 字幕匹配用 `frame/fps` 得当前秒，再找 `t >= start && t < end` 的段落。

### 5. 字幕组件不在 core 里
- `parseSrt()` 在 `@open-motion/core` 里，但 `Captions`/`TikTokCaption` 在 `@open-motion/components` 里，**那个包不一定能装上**（registry 可能没有）。
- 解法：**自己写字幕渲染**——`parseSrt` 拿数组，按当前秒 `find()` 出当前段，用 `interpolate` 做淡入即可，不需要 Captions 组件。

---

## 四、视频产出流程（标准步骤）

```
1. 确认 book-audio-digest 已产出 final.mp3 + subtitles.srt + manifest.json
2. open-motion init <项目名> && npm install
3. 拷贝素材进 public/（audio.mp3, subs.srt）
4. 写 src/scenes/BookVideo.tsx（字幕 + 章节标题 + 背景动效 + <Audio>）
5. 注册到 main.tsx（<Composition id="main" ...>，config 与视频一致）
6. 启动 vite dev server（npx vite --port 5173）
7. 渲染：
   open-motion render -u http://127.0.0.1:5173 -o out_noaudio.mp4 -c main --concurrency 2
   # 若音频混流失败 → 按「三.1」用 ffmpeg 叠加 final.mp3
8. 交付：deliver_file(out.mp4)
```

## 五、约束

- **不在 Docker 里跑**：headless Chromium 在无 GUI Docker 里跑渲染，环境坑（字体/系统库/编码）成本远高于收益。优先在本机 macOS 上跑（有 Chromium + 中文字体 + GUI），或用用户已备好的渲染环境。
- 视频只是音频的「可视化增强」，不改变听书内容本身；标题/关键词从章节洞察提炼，不编造书中没有的观点。
- 渲染时长 ≈ 帧数/10 帧/秒；5 分钟视频（9000+ 帧）需十几分钟到几十分钟，先渲一小段（如 300 帧）验证效果，别一上来全渲。
