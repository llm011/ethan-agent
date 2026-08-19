# 资产库（Asset Library）

article-to-video 的可复用资产统一存放在资产库中，跨项目共享。

## 目录布局

```
~/.ethan/assets/library/                    （尊重 ETHAN_DATA_DIR 环境变量）
  presenters/<id>/                          虚拟人角色包（presenter_gen.py 管理）
    character.json                          角色元数据（状态/音色/姿势清单）
    poses/<pose>.png                        各姿势立绘（透明背景 PNG）
  broll/<slug>-<hash8>/                     B-roll 素材（broll_fetch.py 管理，P2）
    clip.mp4
    meta.json                               来源/作者/授权信息
  clips/manim-<hash>.mp4                    Manim 渲染片段（manim_render.py 管理，P3）
```

## 角色包（presenters/<id>/character.json）

```jsonc
{
  "id": "xiaoyu",                    // kebab-case，与目录名一致
  "name": "晓玉",
  "status": "ready",                 // pending（已出 prompt 未导图）→ ready（可用）
  "createdAt": "2026-08-19T10:00:00",
  "voice": {"name": "zh-CN-XiaoyiNeural", "rate": "+5%", "volume": "+0%", "pitch": "+0Hz"},
  "poses": {"standing": "poses/standing.png", "pointing": "poses/pointing.png"},
  "cutout": true,                    // false = 未抠图，前端用圆角卡片框降级
  "source": "manual"                 // manual（用户 GPT image 2 出图）| api
}
```

- manifest 的 `presenter.id` 引用此处的目录名；validate 时要求 `status == "ready"` 且所有姿势文件存在
- manifest 未写 `voice` 时自动继承角色包的 `voice`
- 路径必须是相对角色目录的安全路径（不允许绝对路径或 `..`）

## 生命周期

- 资产一旦入库即被内容哈希/角色 id 寻址，可安全复用；渲染时 pipeline 硬链接（跨盘回退复制）到 `work/public/` 下，不修改库文件
- 清理：直接删除对应目录即可；渲染产物不含库资产的引用计数
