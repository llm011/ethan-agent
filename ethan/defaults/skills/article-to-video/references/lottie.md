# Lottie 动画素材

本技能内置了一批 `.lottie` 动画素材，位于 `assets/lottie/`（清单见 `assets/lottie/README.md`），可用于视频中的角色、插画、加载动画等元素。

## 素材格式：dotLottie

`.lottie` 是 Lottie 官方的 **dotLottie** 格式，本质是一个 zip 包：

```
xxx.lottie
  manifest.json                动画清单（含动画 id 与文件路径）
  <动画 json>                  Lottie 动画数据（lottie-web 消费的对象）
  images/*.png                 可选，含位图资源的动画才有
```

- **动画 json 的路径不固定**（可能在 `animations/` 或 `a/` 下，文件名还可能含空格），用前先 `unzip -p xxx.lottie manifest.json` 读 id 和实际路径，别写死。
- 纯矢量动画（如 `Sandy Loading.lottie`）只有 `manifest.json` + 一个 json。
- 含位图的动画（如 `大胡子正面头像眨眼.lottie`）额外带 `images/` 目录。
- **lottie-web 消费的是内部那个动画 json，不是 `.lottie` 包本身**，使用前先解压。

## 使用步骤

### 1. 解压到渲染项目的 public/

```bash
# 以「两同事讨论」为例，解压到渲染项目的 public 下
unzip -o assets/lottie/两同事讨论.lottie -d <项目>/public/
# 得到 <项目>/public/manifest.json
#       <项目>/public/animations/<uuid>.json
# 含位图的素材还会多出 <项目>/public/images/*.png
```

- 从 `manifest.json` 读动画 id 和实际文件路径（路径不固定，可能在 `animations/` 或 `a/` 下），那个 json 就是要加载的文件。
- **含位图的动画**必须把 `images/` 一起解压、保持与 json 的相对路径，否则渲染时图片缺失。
- 放 `public/` 下用相对路径引用；渲染环境无网络，不能外链 CDN。

### 2. 确认 lottie-web 依赖

`assets/open-motion-template/package.json` 已含 `lottie-web`（^5.13.0），首次渲染会自动安装，无需手动加。

### 3. 编写播放组件（lottie-web 直用）

用 `lottie-web` 的 `loadAnimation` + `delayRender` + `goToAndStop` 逐帧驱动，与 open-motion 的帧号对齐（该写法已在真实项目里跑通并产出成片）：

```tsx
import lottie from 'lottie-web';
import { useCurrentFrame, delayRender, continueRender } from '@open-motion/core';

const LottieScene: React.FC<{ style?: React.CSSProperties }> = ({ style }) => {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const animRef = React.useRef<any>(null);
  const frame = useCurrentFrame();

  React.useEffect(() => {
    const handle = delayRender('loading lottie');
    let cancelled = false;
    if (containerRef.current) {
      animRef.current = lottie.loadAnimation({
        container: containerRef.current,
        renderer: 'svg',
        loop: false,
        autoplay: false,
        path: '/animations/<id>.json', // 解压后的 json 相对路径
      });
      animRef.current.addEventListener('DOMLoaded', () => {
        if (!cancelled) continueRender(handle);
      });
    } else {
      continueRender(handle);
    }
    return () => {
      cancelled = true;
      if (animRef.current) animRef.current.destroy();
    };
  }, []);

  React.useEffect(() => {
    if (animRef.current) {
      // 按视频帧号驱动动画帧（% 循环）；TOTAL_FRAMES 从 json 的 op 字段读
      animRef.current.goToAndStop(frame % TOTAL_FRAMES, true);
    }
  }, [frame]);

  return <div ref={containerRef} style={{ width: '100%', height: '100%', ...style }} />;
};
```

要点：

- `loop: false` + `autoplay: false`，完全交给 `goToAndStop` 手动逐帧驱动，保证与视频帧号同步。
- 动画总帧数读 json 的 `op` 字段（out point，最后一帧 + 1），如 `op: 81` 表示 0–80 共 81 帧。
- `delayRender` 等 `DOMLoaded` 事件再 `continueRender`，否则首帧可能截到空白。
- 卸载时 `destroy()` 释放实例，避免多场景重复挂载泄漏。

## 素材清单速览

| 素材 | 用途 |
|------|------|
| `大胡子正面头像眨眼.lottie` | 真人感头像 + 眨眼（含位图） |
| `两同事讨论.lottie` | 双人对话 |
| `Teacher of Mathematics.lottie` / `woman teacher.lottie` | 教师角色 |
| `a talking man.lottie` | 口播男人 |
| `Robot-Bot 3D.lottie` | 3D 机器人 |
| `Sandy Loading.lottie` | 加载动画（纯矢量） |
| `Books drop to stack.lottie` | 书本叠放 |
| `右侧站着的说话的女人.lottie` | 站姿说话的女人（纯矢量） |
| `戴眼镜的说话男孩.lottie` | 戴眼镜说话的男孩（纯矢量） |
| `有疑问的男孩，最终想出了答案.lottie` | 疑惑→想通答案的男孩（纯矢量） |

> 完整清单与场景建议见 `assets/lottie/README.md`。
