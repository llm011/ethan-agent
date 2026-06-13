---
name: home-assistant
description: "控制智能家居设备：灯光、空调、窗帘、插座、传感器等。通过 Home Assistant REST API 或 CLI 执行操作。"
trigger: "home assistant|homeassistant|HA|智能家居|开灯|关灯|开空调|关空调|开窗帘|关窗帘|调光|调温|灯光|暖气|插座|传感器|设备控制"
fast_path: true
---

# Home Assistant 技能

用于控制通过 Home Assistant 管理的所有智能家居设备。

## 安装状态检查

首先确认 HA skill 是否已完整安装：

```bash
ls ~/.ethan/skills/home-assistant/
```

如果只有这个 SKILL.md 而没有完整的配置和 references，请参考 [references/setup.md](references/setup.md) 完成安装。

## 快速使用

安装完成后，通过 shell 工具调用 HA REST API：

```bash
# 查询设备状态
curl -s -H "Authorization: Bearer $HA_TOKEN" $HA_URL/api/states/<entity_id>

# 控制设备
curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "<entity_id>"}' \
  $HA_URL/api/services/<domain>/<service>
```

常用 domain/service 对照：
- 开灯：`light/turn_on`
- 关灯：`light/turn_off`
- 开空调：`climate/turn_on`
- 关空调：`climate/turn_off`
- 开窗帘：`cover/open_cover`
- 关窗帘：`cover/close_cover`

环境变量 `HA_URL` 和 `HA_TOKEN` 应在 shell 配置或 tools.md 中定义。
