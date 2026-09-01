# Lottie 动画素材库

本目录存放 dotLottie（`.lottie`）动画素材，供视频生成时作为角色 / 插画元素嵌入。

## 素材清单

| 文件名 | 用途 | 建议场景 |
|--------|------|----------|
| `大胡子正面头像眨眼.lottie` | 正面头像 + 眨眼循环（含位图） | 人物出镜、讲解员、真人感角色 |
| `两同事讨论.lottie` | 双人对话 | 会议、协作、讨论场景 |
| `Teacher of Mathematics.lottie` | 数学老师角色 | 教学、知识讲解 |
| `woman teacher.lottie` | 女教师角色 | 教学、课程视频 |
| `a talking man.lottie` | 正在说话的男人 | 口播、旁白、演讲 |
| `Robot-Bot 3D.lottie` | 3D 机器人 | 科技、AI、未来感场景 |
| `Sandy Loading.lottie` | 加载动画（纯矢量） | 加载态、转场、进度 |
| `Books drop to stack.lottie` | 书本叠放 | 学习、阅读、知识主题 |
| `右侧站着的说话的女人.lottie` | 站姿说话的女人（纯矢量） | 口播、讲解员、真人感角色 |
| `戴眼镜的说话男孩.lottie` | 戴眼镜说话的男孩（纯矢量） | 口播、旁白、年轻角色 |
| `有疑问的男孩，最终想出了答案.lottie` | 疑惑→想通答案的男孩（纯矢量） | 思考、答疑、顿悟情节 |

## 格式说明

- `.lottie` 是 Lottie 官方的 **dotLottie** 格式：本质是一个 zip 包，内含 `manifest.json` + 动画 json + 可选 `images/*.png`。
- **动画 json 的路径不固定**（可能在 `animations/` 下，也可能在 `a/` 下，文件名还可能含空格），所以用前先 `unzip -p xxx.lottie manifest.json` 读动画 id 和实际路径，别写死。
- 纯矢量动画只有 `manifest.json` + 一个 json；含位图的动画（如 `大胡子正面头像眨眼.lottie`）额外带 `images/` 目录。
- lottie-web 消费的是内部那个动画 json，不是 `.lottie` 包本身，使用前需先解压。

## 使用方式

参考技能根目录的 `references/lottie.md`，核心三步：

1. `unzip` 解压出内部 `animations/*.json`（含位图的还要把 `images/` 一起解压，保持相对路径）
2. 解压产物放渲染项目的 `public/` 下，用相对路径引用
3. 用 `lottie-web` 的 `loadAnimation` + `delayRender` + `goToAndStop` 逐帧驱动，与视频帧号对齐

> 依赖 `lottie-web` 已加入 `assets/open-motion-template/package.json`，首次渲染会自动安装。
