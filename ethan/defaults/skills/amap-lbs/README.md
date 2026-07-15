# amap-lbs (高德地图综合服务)

## 来源

- OpenClaw 社区 skill: `amap-lbs-skill`
- 原始版本: 2.0.1
- 许可证: MIT
- 高德开放平台: https://lbs.amap.com/

## 修改说明

- 添加了 `trigger` 字段用于 Ethan skill 路由匹配
- 修改 Key 读取逻辑，支持从 `~/.ethan/.secrets/amap_webservice_key` 读取
- 移除了 `gaode_skill.py`（依赖本地 Electron 应用，不适用于 Ethan 场景）
- 修复了 `travelPlanner` 返回值缺少 `mapTaskData` 的问题

## 密钥配置

```
set_secret("amap_webservice_key", "你的高德Web服务Key")
```

Key 申请地址: https://lbs.amap.com/api/webservice/create-project-and-key

## 目录结构

```
amap-lbs/
├── SKILL.md              # 技能主文件（含场景说明）
├── index.js              # 核心模块（POI搜索、路径规划、旅游规划）
├── package.json          # Node.js 依赖
├── scripts/
│   ├── poi-search.js     # POI 搜索脚本
│   ├── route-planning.js # 路径规划脚本
│   └── travel-planner.js # 旅游规划脚本
└── README.md             # 本文件
```
