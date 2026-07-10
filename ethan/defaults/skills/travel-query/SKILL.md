---
name: travel-query
description: 火车票/高铁时刻查询。直接调 12306 官方 API，免登录、免验证码，一次 curl 获取车次/时间/历时/票价。
trigger: "12306|高铁|火车|动车|车次|列车|北京到|上海到|广州到|深圳到|车票|时刻表|G\\d+|D\\d+|K\\d+"
---

# 出行查询（12306 火车票）

## ⚡ 快速调用（直接看这里）

**两步 curl 搞定，不要用 web_search 搜时刻表。**

### 步骤 1：获取 Cookie + 动态接口

```bash
# 获取 cookie 并发现动态查询路径
COOKIE_FILE=/tmp/12306_cookie.txt
curl -s -c "$COOKIE_FILE" "https://kyfw.12306.cn/otn/leftTicket/init" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" -o /dev/null

# 获取动态 endpoint（12306 定期变更查询路径）
QUERY_URL=$(curl -s -b "$COOKIE_FILE" "https://kyfw.12306.cn/otn/leftTicket/queryZ?leftTicketDTO.train_date={日期}&leftTicketDTO.from_station={出发站编码}&leftTicketDTO.to_station={到达站编码}&purpose_codes=ADULT" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  -H "Referer: https://kyfw.12306.cn/otn/leftTicket/init" | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('c_url','leftTicket/queryG'))")
```

### 步骤 2：查询车次

```bash
curl -s -b "$COOKIE_FILE" "https://kyfw.12306.cn/otn/$QUERY_URL?leftTicketDTO.train_date={日期}&leftTicketDTO.from_station={出发站编码}&leftTicketDTO.to_station={到达站编码}&purpose_codes=ADULT" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  -H "Referer: https://kyfw.12306.cn/otn/leftTicket/init" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
results = data.get('data', {}).get('result', [])
print(f'共 {len(results)} 趟车')
print(f'{\"车次\":<8}{\"出发\":<8}{\"到达\":<8}{\"历时\":<8}{\"商务/特\":<6}{\"一等\":<6}{\"二等\":<6}')
for r in results[:15]:
    p = r.split('|')
    if len(p) > 30:
        # 3=车次, 8=出发时间, 9=到达时间, 10=历时, 25=商务座, 31=一等座, 30=二等座
        print(f'{p[3]:<8}{p[8]:<8}{p[9]:<8}{p[10]:<8}{p[25] or \"-\":<6}{p[31] or \"-\":<6}{p[30] or \"-\":<6}')
"
```

### 一步合并版（推荐）

```bash
COOKIE_FILE=/tmp/12306_cookie.txt && \
curl -s -c "$COOKIE_FILE" "https://kyfw.12306.cn/otn/leftTicket/init" -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" -o /dev/null && \
QURL=$(curl -s -b "$COOKIE_FILE" "https://kyfw.12306.cn/otn/leftTicket/queryZ?leftTicketDTO.train_date={日期}&leftTicketDTO.from_station={出发站编码}&leftTicketDTO.to_station={到达站编码}&purpose_codes=ADULT" -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" -H "Referer: https://kyfw.12306.cn/otn/leftTicket/init" | python3 -c "import json,sys;d=json.loads(sys.stdin.read());print(d.get('c_url','leftTicket/queryG'))") && \
curl -s -b "$COOKIE_FILE" "https://kyfw.12306.cn/otn/$QURL?leftTicketDTO.train_date={日期}&leftTicketDTO.from_station={出发站编码}&leftTicketDTO.to_station={到达站编码}&purpose_codes=ADULT" -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" -H "Referer: https://kyfw.12306.cn/otn/leftTicket/init" | python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
results = data.get('data', {}).get('result', [])
print(f'共 {len(results)} 趟车')
print(f'{\"车次\":<8}{\"出发\":<8}{\"到达\":<8}{\"历时\":<8}{\"商务/特\":<6}{\"一等\":<6}{\"二等\":<6}')
for r in results:
    p = r.split('|')
    if len(p) > 31:
        print(f'{p[3]:<8}{p[8]:<8}{p[9]:<8}{p[10]:<8}{p[25] or \"-\":<6}{p[31] or \"-\":<6}{p[30] or \"-\":<6}')
"
```

---

## 三条纪律

1. **严禁用 web_search 查车次/时刻**——12306 官方 API 数据最准，搜索引擎时效性差
2. **日期格式必须为 `YYYY-MM-DD`**——如 `2026-07-11`
3. **站名必须转为三字母站码**——见下方映射表

---

## 常用站码映射

| 站名 | 编码 | 站名 | 编码 |
|------|------|------|------|
| 北京南 | VNP | 上海虹桥 | AOH |
| 北京 | BJP | 上海 | SHH |
| 广州南 | IZQ | 深圳北 | IOQ |
| 杭州东 | HGH | 南京南 | NKH |
| 武汉 | WHN | 成都东 | ICW |
| 重庆北 | CUW | 长沙南 | CWQ |
| 天津 | TJP | 西安北 | EAY |
| 郑州东 | FEF | 合肥南 | ENH |
| 苏州 | SZH | 无锡 | WXH |
| 济南 | JNK | 青岛 | QDK |
| 厦门北 | XKS | 福州南 | FYS |
| 昆明南 | KMM | 贵阳北 | KQW |
| 石家庄 | SJP | 太原南 | TNV |

> 不确定站码时，使用 12306 站名查询 API：
> ```bash
> curl -s "https://kyfw.12306.cn/otn/resources/js/framework/station_name.js" | grep -oP "'[A-Z]{3}'" | head
> ```
> 或直接搜索：`curl -s "https://search.12306.cn/search/v1/station/search?keyword={站名}" -H "User-Agent: Mozilla/5.0"`

---

## 路由逻辑

| 用户意图 | 做什么 |
|---------|--------|
| 查某日A到B的车次 | 直接调 12306 API（合并版） |
| 查最早/最晚一班 | 调 API → 按出发时间排序取首/尾 |
| 查某车次详情 | 搜索 API：`https://search.12306.cn/search/v1/train/search?keyword={车次}&date={YYYYMMDD}` |
| 对比两个方案 | 分别查两条线路，表格对比 |

---

## 响应字段解析（`|` 分隔）

| 索引 | 含义 | 索引 | 含义 |
|------|------|------|------|
| 3 | 车次 | 6 | 出发站 |
| 7 | 到达站 | 8 | 出发时间 |
| 9 | 到达时间 | 10 | 历时 |
| 25 | 商务座/特等座 | 31 | 一等座 |
| 30 | 二等座 | 26 | 软卧/一等卧 |
| 28 | 硬卧/二等卧 | 29 | 硬座 |

票量值：数字=有票，`有`=充足，`无`=售罄，空=不支持

---

## ⚠️ 关键纪律

```
✅ 正确流程：
1. 确定日期、出发站、到达站
2. 查站码映射（常用站码表直接查）
3. 一次 shell 合并命令搞定
4. 按需求排序/筛选，直接回答

❌ 绕路（禁止）：
1. web_search("北京到上海高铁")（搜索引擎时效差）
2. web_fetch("https://www.12306.cn/...")（12306 需 JS 渲染）
3. 多次重试同一个错误的 endpoint（拿到 c_url 后直接用）
4. 使用 browser_session 打开 12306（太慢，API 更快）
```

activate_tools: shell
