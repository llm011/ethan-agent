---
name: amap-lbs
display_name: Gaode Map LBS - 高德官方地图综合服务 Skill
description: 高德地图综合服务，支持POI搜索、路径规划、旅游规划、周边搜索和热力图数据可视化
version: 2.0.1
trigger:
  - 地图
  - 导航
  - 路线规划
  - POI
  - 周边搜索
  - 旅游规划
  - 高德
metadata:
  openclaw:
    requires:
      env:
        - AMAP_WEBSERVICE_KEY
      bins:
        - node
    primaryEnv: AMAP_WEBSERVICE_KEY
    homepage: https://lbs.amap.com/api/webservice/summary
    install:
      - kind: node
        package: axios
        bins: []
---

# 高德地图综合服务 Skill

高德地图综合服务向开发者提供完整的地图数据服务，包括地点搜索、路径规划、旅游规划和数据可视化等功能。

## 功能特性

- 🔍 POI（地点）搜索功能
- 🏙️ 支持关键词搜索、城市限定、类型筛选
- 📍 支持周边搜索（基于坐标和半径）
- 🛣️ 路径规划（步行、驾车、骑行、公交）
- 🗺️ 智能旅游规划助手
- 🔥 热力图数据可视化
- 🔗 地图可视化链接生成

## 首次配置

首次使用时需要配置高德 Web Service Key：

1. 访问 [高德开放平台](https://lbs.amap.com/api/webservice/create-project-and-key) 创建应用并获取 Key
2. 让 Ethan 保存密钥：`set_secret("amap_webservice_key", "你的key")`
3. 密钥将存储在 `~/.ethan/.secrets/amap_webservice_key`

当用户想要搜索地址、地点、周边信息（如美食、酒店、景点等）、规划路线或可视化数据时，使用此 skill。

## 触发条件

用户表达了以下意图之一：
- 搜索某类地点或某个确定地点（如"搜美食"、"找酒店"、"天安门在哪"）
- 基于某个位置搜索周边（如"西直门周边美食"、"北京南站附近酒店"）
- 规划路线（如"从天安门到故宫怎么走"、"规划驾车路线"）
- 旅游规划（如"帮我规划北京一日游"、"杭州西湖游览路线"）
- 包含"搜"、"找"、"查"、"附近"、"周边"、"路线"、"规划"等关键词
- 希望将地理数据可视化为热力图（如"生成热力图"、"用这份数据做热力图展示"）

## 场景判断

收到用户请求后，先判断属于哪个场景：

- **场景一**：用户搜索一个**明确的类别**（美食、酒店）或**确定的地点**（天安门、西湖），没有指定"在哪个位置附近"
- **场景二**：用户搜索**某个位置周边**的某类地点，输入中同时包含「位置」和「搜索类别」两个要素（如"西直门周边美食"、"北京南站附近酒店"）
- **场景三**：热力图数据可视化
- **场景四**：POI 详细搜索（使用 Web 服务 API）
- **场景五**：路径规划
- **场景六**：智能旅游规划

---

## 场景一：明确关键词搜索

直接搜索一个类别或地点，不涉及特定位置的周边搜索。

**URL 格式：**

```
https://www.amap.com/search?query={关键词}
```

- **域名**：`www.amap.com`
- **路由**：`/search`
- **参数**：`query` = 搜索关键词

### 执行步骤

1. **提取关键词**：从用户输入中识别出核心搜索词，去掉"搜"、"找"等修饰词
2. **生成 URL**：拼接 `https://www.amap.com/search?query={关键词}`
3. **返回链接给用户**

### 示例

| 用户输入 | 提取关键词 | 生成 URL |
|---------|-----------|---------|
| 搜美食 | 美食 | `https://www.amap.com/search?query=美食` |
| 找酒店 | 酒店 | `https://www.amap.com/search?query=酒店` |
| 天安门在哪 | 天安门 | `https://www.amap.com/search?query=天安门` |
| 找个加油站 | 加油站 | `https://www.amap.com/search?query=加油站` |

### 回复模板

```
已为你生成高德地图搜索链接：

https://www.amap.com/search?query={关键词}

点击链接即可查看搜索结果。
```

---

## 场景二：基于位置的周边搜索

用户想搜索**某个位置周边**的某类地点。需要先通过地理编码 API 获取该位置的经纬度，再拼接带坐标的搜索链接。

### 执行步骤

#### 第一步：解析用户输入

从用户输入中拆分出两个要素：
- **位置**：用户指定的中心位置（如"西直门"、"北京南站"）
- **搜索类别**：要搜索的内容（如"美食"、"酒店"）

| 用户输入 | 位置 | 搜索类别 |
|---------|------|---------|
| 西直门周边美食 | 西直门 | 美食 |
| 北京南站附近酒店 | 北京南站 | 酒店 |
| 天坛周边有什么好吃的 | 天坛 | 美食 |

#### 第二步：调用地理编码 API 获取经纬度

使用 `get_secret("amap_webservice_key")` 获取 key，然后：

```bash
curl -s "https://restapi.amap.com/v3/geocode/geo?address={位置}&output=JSON&key={key}"
```

从返回结果中提取 `geocodes[0].location`，格式为 `经度,纬度`。

#### 第三步：拼接带坐标的搜索链接

```
https://ditu.amap.com/search?query={搜索类别}&query_type=RQBXY&longitude={经度}&latitude={纬度}&range=1000
```

### 回复模板

```
已查询到「{位置}」的坐标（{经度},{纬度}），为你生成周边{搜索类别}的搜索链接：

https://ditu.amap.com/search?query={搜索类别}&query_type=RQBXY&longitude={经度}&latitude={纬度}&range=1000

点击链接即可查看「{位置}」周边 1 公里内的{搜索类别}。
```

---

## 场景三：热力图展示

用户有一份包含地理坐标的数据，希望在地图上以热力图的形式可视化展示。

### 触发条件

用户提到"热力图"、"数据可视化"、"地图上展示数据"等意图，并提供了数据地址。

### URL 格式

```
http://a.amap.com/jsapi_demo_show/static/openclaw/heatmap.html?mapStyle={地图风格}&dataUrl={数据地址(URL编码)}
```

- `mapStyle` = `grey`（暗黑）或 `light`（浅色）
- `dataUrl` = 用户数据的 URL 地址（**必须进行 URL 编码**）

---

## 场景四：POI 详细搜索

使用高德 Web 服务 API 进行更详细的 POI 搜索，支持更多参数和筛选条件。

### 使用方法

```bash
# 基础搜索
node scripts/poi-search.js --keywords=肯德基 --city=北京

# 搜索更多结果
node scripts/poi-search.js --keywords=餐厅 --city=上海 --page=1 --offset=20

# 周边搜索（需要提供中心点坐标和搜索半径）
node scripts/poi-search.js --keywords=酒店 --location=116.397428,39.90923 --radius=1000
```

### 参数说明

| 参数 | 说明 | 必填 | 示例 |
|------|------|------|------|
| `--keywords` | 搜索关键词 | 是 | `--keywords=肯德基` |
| `--city` | 城市名称或编码 | 否 | `--city=北京` |
| `--types` | POI 类型编码 | 否 | `--types=050000` |
| `--location` | 中心点坐标（经度,纬度） | 否 | `--location=116.397428,39.90923` |
| `--radius` | 搜索半径（米） | 否 | `--radius=1000` |
| `--page` | 页码 | 否 | `--page=1` |
| `--offset` | 每页数量（最大25） | 否 | `--offset=10` |

---

## 场景五：路径规划

规划不同出行方式的路线。

### 使用方法

```bash
# 步行路线
node scripts/route-planning.js --type=walking --origin=116.397428,39.90923 --destination=116.427281,39.903719

# 驾车路线
node scripts/route-planning.js --type=driving --origin=116.397428,39.90923 --destination=116.427281,39.903719

# 公交路线
node scripts/route-planning.js --type=transfer --origin=116.397428,39.90923 --destination=116.427281,39.903719 --city=北京
```

### 路线类型

- `walking` - 步行路线
- `driving` - 驾车路线
- `riding` - 骑行路线
- `transfer` - 公交路线（需要指定城市）

---

## 场景六：智能旅游规划

自动搜索兴趣点并规划游览路线。

### 使用方法

```bash
# 基础旅游规划
node scripts/travel-planner.js --city=北京 --interests=景点,美食,酒店

# 指定路线类型
node scripts/travel-planner.js --city=杭州 --interests=西湖,美食,茶馆 --routeType=walking

# 驾车游览
node scripts/travel-planner.js --city=上海 --interests=外滩,南京路,城隍庙 --routeType=driving
```

---

## 注意事项

- 场景二、四、五、六需要高德 API Key，**必须先通过 `get_secret("amap_webservice_key")` 获取 Key 后再发起请求**
- 如果 Key 不存在，提示用户在高德开放平台创建应用获取，然后用 `set_secret` 保存
- API 返回的 `location` 格式为 `经度,纬度`（经度在前，纬度在后）
- 高德 Web 服务 API 有调用频率限制，请合理使用

## 相关链接

- [高德开放平台](https://lbs.amap.com/)
- [创建应用和获取 Key](https://lbs.amap.com/api/webservice/create-project-and-key)
- [POI 搜索 API 文档](https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch)
- [Web 服务 API 总览](https://lbs.amap.com/api/webservice/summary)
