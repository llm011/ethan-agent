---
name: book-audio-digest
trigger: 深度听书|听书笔记|读书音频|通勤听书|音频解读|书解读音频|听书摘要|book audio digest|audio digest
description: 深度听书 — 融合微信读书素材（书籍信息、目录、热门划线）与个人知识库，生成飞书深度读书笔记 + 可通勤收听的高质量音频（MP3）。
version: 0.1.0
metadata:
  requires:
    bins: ["uv", "ffmpeg", "ffprobe"]
    secrets:
      - path: "~/.ethan/.secrets/wechat-reading.env"
        fields: ["WEREAD_API_KEY"]
        description: "微信读书 Agent API Key，见 wechat-reading 技能。"
  relates:
    - skill: wechat-reading
      scope: "书籍信息/目录/热门划线采集规范与限流避坑，本技能复用其 API 调用纪律。"
    - skill: feishu-writer
      scope: "飞书文档写作规范（黄金开局、去 AI 味、视觉节奏），本技能产出文档遵循其铁律。"
    - skill: article-to-video
      scope: "Edge TTS 合成纪律同源；本技能只要音频，不需要视频渲染。"
---

# 深度听书（Book Audio Digest）

给一本书名，产出两件交付物：**飞书深度读书笔记**（深度整合 + 个人感悟）和**高质量音频**（通勤/排队收听，默认 8–15 分钟）。素材来自微信读书（书籍信息、目录、热门划线），关联用户知识库里最相关的内容（少而精）。详细方法见 references/audio-script-guide.md 与 references/feishu-note-guide.md，动笔前先用 skill_read 读完。

## 工作流

### 1. 项目目录

```bash
PROJECT="$HOME/.ethan/output/book-audio-digest/$(date +%Y%m%d-%H%M%S)-<书名拼音>"
mkdir -p "$PROJECT/weread"
```

### 2. 素材采集（shell + curl，遵循 wechat-reading 技能规范）

- `/store/search`（scope=10）→ bookId；`/book/info` → 详情；`/book/chapterinfo` → 章节
- **同名书必须消歧**：用"书名 + 作者"搜索并核对作者与出版社，别拿搜索第一个结果就跑（如《格局》有月夜生凉/王志纲等多个版本，内容完全不同）
- **可用性预检（先做再写稿）**：拿到 bookId 后先调一次 `/book/bestbookmarks`（chapterUid=0），若返回 `{"synckey":0}` 空响应，说明这本书拿不到划线数据（多见于付费书/冷门版本，如吴军《态度》的推广版 bookId=3001121336），换版本或换书，不要硬写
- 热门划线**按章节批量拉取再合并**（单次 `/book/bestbookmarks` 只回 top 20）：逐 chapterUid 调用、按 markText 去重、按 totalCount 降序。限流纪律：请求间 sleep 1–2s；`errcode:-2010` 是限流不是 key 失效，指数退避重试；连续失败先拉 chapterUid=0 兜底；偶发 HTTP 499 直接跳过该章、下轮补拉
- 原始 JSON 落盘 `$PROJECT/weread/`，别只留在内存

### 3. 知识库关联（少而精）

knowledge_search 做 2–3 个查询（书名/作者/核心主题），limit 2–3；只对**最有价值的 1–2 条** knowledge_read 精读，让解读带个人上下文。搜不到就跳过，不硬凑。

### 4. 写两个产出

**a. 飞书深度读书笔记**：按 `references/feishu-note-guide.md` 的结构，用 `lark-cli docs +create --as user` 创建（遵循 feishu-writer 铁律：黄金开局、去 AI 味、Callout 节制、正文 ≥ 2500 字）。注意：user token 过期时报 `need_user_authorization`，需要用户在场跑 `lark-cli auth login`（交互式）；无人值守时段可先完成音频交付，把笔记 XML 存 `$PROJECT/feishu-note.xml` 待授权后补建。`--content` 用 `@./file.xml` 相对路径（绝对路径与 `~` 都会被 CLI 拒绝）。

**b. 音频脚本**：按 `references/audio-script-guide.md` 把笔记**口语化改写**（不是照念文档），写入 `$PROJECT/manifest.json`：

```json
{"title": "《态度》深度听书", "voice": {"name": "zh-CN-YunxiNeural", "rate": "+0%", "volume": "+0%", "pitch": "+0Hz"}, "gapMs": 700, "targetDurationSec": 600,
 "sections": [{"id": "opening", "narration": "..."}, {"id": "insight-1", "narration": "..."}]}
```

### 5. 音频合成

```bash
# 先校验（无网络）
python3 ~/.ethan/skills/book-audio-digest/scripts/audio_pipeline.py validate --manifest "$PROJECT/manifest.json"
# 后台合成（uv 临时注入 edge-tts；env -u 是本机代理未运行时的直连兜底）
nohup env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
  uv run --isolated --no-project --with 'edge-tts>=7,<8' python \
  ~/.ethan/skills/book-audio-digest/scripts/audio_pipeline.py run \
  --manifest "$PROJECT/manifest.json" --output-dir "$PROJECT" \
  > "$PROJECT/render.log" 2>&1 &
```

合成 1–3 分钟，轮询 render.log。脚本按 narration+voice 内容哈希缓存，重跑只重做变化章节。

### 6. 复核与交付

- `run-status.json` 的 `status` 是 `ok`，`final.mp3` 与 `subtitles.srt` 存在
- 必须调用 `deliver_file(path="<PROJECT>/final.mp3", title="《书名》深度听书笔记")`，正文附飞书文档链接
- 实际时长超出 target ±40% 时调整脚本重跑（保持章节 id 不变则命中缓存）

## 约束

- 音频脚本必须口语化改写；直接引用划线原文 ≤ 15% 篇幅且口语引入
- 不虚构书中没有的内容；知识库关联 ≤ 2 条，宁缺毋滥
- 不自动发布、不外传给 Edge TTS 以外的服务；单节 narration ≤ 3000 字、节数 ≤ 40

activate_tools: shell, file_write, knowledge_search, knowledge_read, deliver_file
