---
name: nearby-search
display_name: 周边搜索 - 定位用户并搜索附近 POI
description: 当用户询问周边、附近、旁边有什么时，先定位用户位置，再调用 amap-lbs 技能搜索周边 POI
version: 1.0.0
trigger:
  - 周边
  - 附近
  - 旁边
  - 周围
  - 附近有什么
  - 周边有什么
  - 旁边有没有
  - 附近哪里有
---

# 周边搜索

当用户询问"周边"、"附近"、"旁边"有没有某类场所（如美食、咖啡、超市等）时，使用此技能定位用户并搜索周边信息。

**重要：不要使用 web search 来回答周边搜索类问题，始终走本技能的定位 + amap-lbs 流程。**

## 触发条件

用户消息中包含以下意图：
- "周边/附近/旁边有什么好吃的"
- "附近有没有咖啡店"
- "周围有什么餐厅"
- "旁边哪里有超市"
- 任何包含"周边"、"附近"、"旁边"、"周围"等词，且在询问某类场所/服务的表达

## 执行流程

### 第一步：确定用户位置

按以下优先级确定用户当前所在位置：

#### 优先级 1：用户已明确给出地址

如果用户消息中已包含具体地址（如"中关村附近有什么好吃的"、"南山科技园周边咖啡"），直接使用该地址，**跳过后续定位步骤**。

#### 优先级 2：工作日白天推断上班地址

判断当前是否为**工作日（周一至周五）且处于工作时间（9:00-18:00，注意使用用户所在时区）**：
- 如果是，从 memory（`context://memory/user_profile.md` 或 `context://memory/projects/` 下的相关文件）中查找用户的**上班地址/公司地址**
- 如果 memory 中有上班地址，使用该地址

#### 优先级 3：IP 地理定位（兜底）

如果以上都不可用，通过 IP 定位获取用户大致位置：

```bash
curl --noproxy "*" "http://ip-api.com/json?lang=zh-CN"
```

返回示例：
```json
{
  "status": "success",
  "country": "中国",
  "regionName": "广东",
  "city": "深圳",
  "lat": 22.5431,
  "lon": 114.0579,
  "query": "x.x.x.x"
}
```

从返回中提取 `city`（城市）和 `lat`/`lon`（经纬度）。

### 第二步：获取精确坐标

- 如果第一步得到的是**地址文本**（如"南山科技园"），需要先通过地理编码获取经纬度：

```bash
curl -s "https://restapi.amap.com/v3/geocode/geo?address={地址}&output=JSON&key=$(get_secret amap_webservice_key)"
```

从返回的 `geocodes[0].location` 获取 `经度,纬度`。

- 如果第一步得到的是 IP 定位的 `lat`/`lon`，直接使用（注意高德格式为 `经度,纬度`，即 `lon,lat`）。

### 第三步：调用 amap-lbs 技能搜索周边

使用 amap-lbs 技能的**场景四（POI 详细搜索）**进行周边搜索：

```bash
node scripts/poi-search.js --keywords={用户要搜的类别} --location={经度},{纬度} --radius=1000
```

脚本路径位于 amap-lbs 技能目录下：`ethan/defaults/skills/amap-lbs/scripts/poi-search.js`

参数说明：
- `--keywords`：用户要找的类别（美食、咖啡、超市等）
- `--location`：经度,纬度（高德格式，经度在前）
- `--radius`：搜索半径，默认 1000 米，可根据需要调整

### 第四步：整理结果返回

将搜索结果整理为用户友好的格式，包含：
- 地点名称
- 地址
- 距离
- 评分（如有）
- 电话（如有）

同时附上高德地图的可视化链接供用户查看更多：

```
https://ditu.amap.com/search?query={类别}&query_type=RQBXY&longitude={经度}&latitude={纬度}&range=1000
```

## 注意事项

- **不要使用 web search** 来回答周边搜索类问题，始终走本技能的定位 + amap-lbs 流程
- API Key 通过 `get_secret("amap_webservice_key")` 获取
- 高德坐标格式始终为 `经度,纬度`（lon,lat），IP 定位 API 返回的是 `lat,lon`，注意转换
- 如果 IP 定位失败或返回非中国地区，提示用户手动提供位置
- 搜索半径默认 1000 米，如果结果太少可扩大到 2000-3000 米
