---
name: finance-query
description: 股票/指数实时行情、K线历史、估值PE/PB、财务数据、板块排名。覆盖 A股/港股/美股，直接 curl 免费 API，不依赖 web_search。
trigger: "A股|股票|上证|深证|指数|行情|大盘|涨跌|收盘|开盘|基金净值|港股|美股|K线|PE|PB|估值|市值|财报|ROE|市盈率|板块|涨幅榜|茅台|腾讯|苹果|AAPL|TSLA"
---

# 金融行情查询

## ⚡ 快速调用（直接看这里）

**一条 curl 命令搞定，不要绕路去 web_search。**

### 查实时行情（腾讯财经，A/港/美统一）

```bash
curl -s "http://qt.gtimg.cn/q={代码}" -H "User-Agent: Mozilla/5.0" | iconv -f GBK -t UTF-8
```

代码前缀：`sh600519`(A股沪) / `sz000001`(A股深) / `hk00700`(港股) / `usAAPL`(美股)

批量：`q=sh600519,hk00700,usAAPL`

### 查K线（东财，全市场）

```bash
curl -s "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={SECID}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&beg=0&end=20500000&lmt=60" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  -H "Referer: https://quote.eastmoney.com/"
```

SECID：`1.600519`(沪) / `0.000001`(深) / `105.AAPL`(美) / `116.00700`(港)

### 查估值 PE/PB（东财）

```bash
# A股
curl -s "https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_DMSK_NEWINDICATOR&columns=SECURITY_CODE,SECUCODE&quoteColumns=f115~01~SECURITY_CODE~PE_TTM,f23~01~SECURITY_CODE~PB_NEW_NOTICE&filter=(SECUCODE=%22{代码}.{SH或SZ}%22)&pageNumber=1&pageSize=1&source=HSF10&client=PC" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: https://data.eastmoney.com/"

# 美股
curl -s "https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_USF10_DATA_MAININDICATOR&columns=ALL&filter=(SECURITY_CODE=%22{TICKER}%22)&pageNumber=1&pageSize=1&sortTypes=-1&sortColumns=REPORT_DATE&source=INTLSECURITIES&client=PC" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: https://data.eastmoney.com/"

# 港股
curl -s "https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_CUSTOM_HKF10_FN_MAININDICATORMAX&columns=ALL&filter=(SECURITY_CODE=%22{5位代码}%22)&pageNumber=1&pageSize=1&sortTypes=-1&sortColumns=REPORT_DATE&source=F10&client=PC" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: https://data.eastmoney.com/"
```

---

## 三条纪律

1. **严禁用 web_search 查行情/K线/估值**——搜索引擎对实时金融数据结果极差，直接 curl API
2. **所有腾讯/新浪接口必须 `iconv -f GBK -t UTF-8`**——否则中文乱码
3. **连续请求间隔至少 1 秒**——避免被限速封 IP

---

## 路由逻辑（用户问什么 → 做什么）

| 用户意图 | 调用方式 | 数据源 |
|---------|---------|--------|
| 查某股票现价/涨跌 | 腾讯行情（1 次 curl） | qt.gtimg.cn |
| 查 PE/PB/市盈率 | 先试腾讯行情（字段39=PE, 43=PB），不够再用东财估值 | qt.gtimg.cn → datacenter.eastmoney |
| 查 K线/走势/历史 | 东财 K线 + generate_chart | push2his.eastmoney |
| 查财报/ROE/利润 | 东财财务数据 | datacenter.eastmoney |
| 查涨幅榜/板块 | 东财全市场排名 | 82.push2.eastmoney |
| 不确定代码 | 东财代码搜索 → 再查 | searchapi.eastmoney |

---

## 代码映射规则

### 腾讯行情前缀

| 市场 | 前缀 | 示例 |
|------|------|------|
| A股沪市(6/9开头) | `sh` | `sh600519` |
| A股深市(0/3开头) | `sz` | `sz000001` |
| 上证指数 | `sh000001` | 深证成指 `sz399001`，创业板 `sz399006` |
| 港股 | `hk` + 5位 | `hk00700`(腾讯) |
| 美股 | `us` + TICKER | `usAAPL`(苹果), `usTSLA`(特斯拉) |

### 东财 SECID

| 市场 | 格式 | 示例 |
|------|------|------|
| A股沪(6/9开头) | `1.代码` | `1.600519` |
| A股深(0/3开头) | `0.代码` | `0.000001` |
| 美股 | `105.TICKER` | `105.AAPL` |
| 港股 | `116.代码` | `116.00700` |

### 东财估值代码格式

- A股沪市：`{code}.SH`（如 `600519.SH`）
- A股深市：`{code}.SZ`（如 `000001.SZ`）
- 美股：直接 TICKER（如 `AAPL`）
- 港股：5 位代码（如 `00700`）

---

## 响应解析

### 腾讯行情（`~` 分隔，按索引取值）

| 索引 | 含义 | 索引 | 含义 |
|------|------|------|------|
| 1 | 名称 | 3 | 现价 |
| 4 | 昨收 | 5 | 开盘 |
| 31 | 涨跌额 | 32 | 涨跌幅% |
| 33 | 最高 | 34 | 最低 |
| 38 | 换手率% | 39 | PE(TTM) |
| 43 | PB | 44 | 总市值(元) |

### 东财 K线

响应 JSON → `data.klines` 数组，每条：`"日期,开,收,高,低,量"`

参数：`klt=101`(日) / `102`(周) / `103`(月)；`fqt=1`(前复权) / `2`(后复权)；`lmt=N`(最近N条)

### 东财财务

响应 JSON → `result.data` 数组，关键字段：
- `PARENTNETPROFIT`: 归母净利润
- `TOTALOPERATEREVE`: 营业总收入
- `BASIC_EPS`: 每股收益
- `WEIGHTAVG_ROE`: 加权ROE

---

## 附加能力

### 代码搜索（不确定 ticker 时先查）

```bash
curl -s "https://searchapi.eastmoney.com/api/suggest/get?input={关键词}&type=14&token=D43BF722C8E33BDC906FB84D85E326E8"
```

### 全市场涨幅排名

```bash
# 涨幅前20（改 pz 控制数量，po=1 降序 / po=0 升序）
curl -s "http://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=20&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14,f3,f24,f25" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: http://quote.eastmoney.com/center/gridlist.html"
```

字段：`f12`=代码, `f14`=名称, `f3`=今日涨跌%, `f24`=60日涨幅%, `f25`=年初至今%

### 行业板块列表

```bash
curl -s "http://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m:90+t:2&fields=f12,f14,f3" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: http://quote.eastmoney.com/"
```

### 生成走势图

拿到 K 线数据后，调 `generate_chart`：

```json
{
  "type": "line",
  "data": {
    "labels": ["日期1", "日期2", "..."],
    "datasets": [{"label": "股票名", "data": [价格1, 价格2], "borderColor": "rgb(255,99,132)", "fill": false}]
  },
  "options": {"plugins": {"title": {"display": true, "text": "XXX 近N日走势"}}}
}
```

### 新浪财经（A股行情备选）

```bash
curl -s -H "Referer: http://finance.sina.com.cn" "http://hq.sinajs.cn/list=sh000001" | iconv -f GBK -t UTF-8
```

---

## ⚠️ 关键纪律（避免绕路）

```
✅ 正确流程：
1. 判断用户要什么（行情/K线/估值/财务/板块）
2. 按「路由逻辑」表选对应 API
3. 一次 shell(curl) 搞定
4. 解析响应，直接回答

❌ 绕路（禁止）：
1. web_search("茅台股价")（搜索引擎拿不到实时行情）
2. web_fetch("https://finance.sina.com.cn/...")（网页需 JS 渲染）
3. 多次 curl 同一个 API（批量查询用逗号拼接一次搞定）
4. 忘记 iconv 导致乱码后再重试（第一次就要带）
```

**铁律**：
- 实时行情 → 腾讯（一个接口覆盖 A/港/美）
- K线/估值/财务 → 东财
- 腾讯行情已含 PE/PB（字段 39、43），**简单估值查询不用单独调东财**
- 东财 `ut` 和 `token` 是公开固定值，直接用
- 非交易时段返回最近一个交易日收盘数据，正常返回即可

activate_tools: shell, generate_chart
