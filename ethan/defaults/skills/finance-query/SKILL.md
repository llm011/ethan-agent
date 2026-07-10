---
name: finance-query
description: 股票/指数实时行情、K线历史、估值PE/PB、财务三表、技术指标、板块排名、公司信息。覆盖 A股/港股/美股，直接 curl 免费 API，不依赖 web_search。
trigger: "A股|股票|上证|深证|指数|行情|大盘|涨跌|收盘|开盘|基金净值|港股|美股|K线|PE|PB|估值|市值|财报|ROE|市盈率|板块|涨幅榜|茅台|腾讯|苹果|AAPL|TSLA|利润表|资产负债|现金流|EPS|技术指标|MA|RSI|MACD|KDJ|均线|成交量|ETF"
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

### 查财务数据（东财，A股）

```bash
# A股主要财务指标（近10期，含净利润/营收/EPS/ROE）
curl -s "https://datacenter.eastmoney.com/securities/api/data/get?type=RPT_F10_FINANCE_MAINFINADATA&sty=APP_F10_MAINFINADATA&filter=(SECUCODE=%22{代码}.{SH或SZ}%22)&p=1&ps=10&sr=-1&st=REPORT_DATE&source=HSF10&client=PC" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: https://emweb.securities.eastmoney.com/"

# A股资产负债表（归母权益/总资产）
curl -s "https://datacenter.eastmoney.com/securities/api/data/get?type=RPT_F10_FINANCE_GBALANCE&sty=APP_F10_GBALANCE&filter=(SECUCODE=%22{代码}.SH%22)&p=1&ps=10&sr=-1&st=REPORT_DATE&source=HSF10&client=PC" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: https://emweb.securities.eastmoney.com/"
```

### 查财务数据（东财，美股三表）

```bash
# 美股利润表（持续经营利润）
curl -s "https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_USF10_FN_INCOME&columns=SECUCODE,SECURITY_NAME_ABBR,REPORT_DATE,REPORT_TYPE,STD_ITEM_CODE,AMOUNT&filter=(SECUCODE=%22{TICKER}.O%22)(STD_ITEM_CODE%20in%20(%22004013003%22,%22004013005%22))&pageNumber=1&pageSize=20&sortTypes=-1,1&sortColumns=REPORT_DATE,STD_ITEM_CODE&source=SECURITIES&client=PC" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: https://emweb.securities.eastmoney.com/"

# 美股资产负债表（归母权益）
curl -s "https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_USF10_FN_BALANCE&columns=SECUCODE,SECURITY_NAME_ABBR,REPORT_DATE,REPORT_TYPE,STD_ITEM_CODE,AMOUNT&filter=(SECUCODE=%22{TICKER}.O%22)(STD_ITEM_CODE%20in%20(%22002005999%22,%22002005097%22))&pageNumber=1&pageSize=20&sortTypes=-1,1&sortColumns=REPORT_DATE,STD_ITEM_CODE&source=SECURITIES&client=PC" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: https://emweb.securities.eastmoney.com/"

# 美股现金流量表（经营/投资/筹资现金流）
curl -s "https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_USSK_FN_CASHFLOW&columns=SECUCODE,SECURITY_NAME_ABBR,REPORT_DATE,REPORT_TYPE,STD_ITEM_CODE,AMOUNT&filter=(SECUCODE=%22{TICKER}.O%22)&pageNumber=1&pageSize=20&sortTypes=-1,1&sortColumns=REPORT_DATE,STD_ITEM_CODE&source=SECURITIES&client=PC" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: https://emweb.securities.eastmoney.com/"
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
| 查 A股财报/ROE/利润 | 东财主财务 | datacenter.eastmoney |
| 查 A股资产负债/净资产 | 东财资产负债表 | datacenter.eastmoney |
| 查 美股利润/净利 | 东财美股利润表 | datacenter.eastmoney |
| 查 美股资产/权益 | 东财美股资产负债表 | datacenter.eastmoney |
| 查 美股现金流 | 东财美股现金流量表 | datacenter.eastmoney |
| 查涨幅榜/板块 | 东财全市场排名 | 82.push2.eastmoney |
| 查板块成分股 | 东财板块成分 | 82.push2.eastmoney |
| 查技术指标(MA/RSI/MACD) | 先拉K线，再计算（见技术指标章节） | push2his → 计算 |
| 查美股板块ETF动量 | shell python yfinance | Yahoo Finance |
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

### 东财 SECID（K线用）

| 市场 | 格式 | 示例 |
|------|------|------|
| A股沪(6/9开头) | `1.代码` | `1.600519` |
| A股深(0/3开头) | `0.代码` | `0.000001` |
| 美股 | `105.TICKER` | `105.AAPL` |
| 港股 | `116.代码` | `116.00700` |

### 东财估值/财务代码格式

| 市场 | 格式 | 示例 |
|------|------|------|
| A股沪市 | `{code}.SH` | `600519.SH` |
| A股深市 | `{code}.SZ` | `000001.SZ` |
| A股北交所(4/8/920开头) | `{code}.BJ` | `430047.BJ` |
| 美股纳斯达克 | `{TICKER}.O` | `AAPL.O` |
| 美股纽交所 | `{TICKER}.N` | `JPM.N` |
| 美股AMEX | `{TICKER}.A` | `GOLD.A` |
| 港股 | 5位代码 | `00700` |

**美股交易所判断**：大部分科技股在纳斯达克(`.O`)，金融/工业在纽交所(`.N`)。不确定时先用 `.O` 试，无数据再试 `.N`。

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

参数：`klt=101`(日) / `102`(周) / `103`(月) / `klt=5`(5分钟) / `klt=15`(15分钟) / `klt=60`(60分钟)
复权：`fqt=1`(前复权) / `2`(后复权)；条数：`lmt=N`(最近N条)

### A股主要财务

响应 JSON → `result.data` 数组，关键字段：
- `REPORT_DATE`: 报告期
- `PARENTNETPROFIT`: 归母净利润
- `KCFJCXSYJLR`: 扣非净利润
- `TOTALOPERATEREVE`: 营业总收入
- `BASIC_EPS`: 基本每股收益
- `WEIGHTAVG_ROE`: 加权平均ROE
- `MGJZC`: 每股净资产
- `YSTZ`: 营收同比增长率
- `SJLTZ`: 净利润同比增长率

### A股资产负债表

- `TOTAL_ASSETS`: 总资产
- `TOTAL_PARENT_EQUITY`: 归属母公司股东权益
- `TOTAL_EQUITY`: 所有者权益合计
- `TOTAL_LIABILITIES`: 负债合计

### 美股财务三表

响应 JSON → `result.data` 数组，字段含义：
- `REPORT_DATE`: 报告期
- `REPORT_TYPE`: `年报` / `中报` / `季报`
- `STD_ITEM_CODE`: 科目代码（见下方映射）
- `AMOUNT`: 金额（美元）

**利润表关键科目**：
| STD_ITEM_CODE | 含义 |
|------|------|
| `004013003` | 持续经营净利润(年报) |
| `004013005` | 持续经营净利润(季报) |
| `001013003` | 营业总收入(年报) |
| `001013005` | 营业总收入(季报) |

**资产负债表关键科目**：
| STD_ITEM_CODE | 含义 |
|------|------|
| `002005999` | 归母股东权益(年报) |
| `002005097` | 归母股东权益(季报) |
| `002009003` | 总资产(年报) |
| `002009005` | 总资产(季报) |

---

## 板块与市场概览

### A股全市场涨跌幅排名

```bash
# 涨幅前20（改 pz 控制数量，po=1 降序 / po=0 升序看跌幅）
curl -s "http://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=20&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14,f3,f24,f25" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: http://quote.eastmoney.com/center/gridlist.html"
```

字段：`f12`=代码, `f14`=名称, `f3`=今日涨跌%, `f24`=60日涨幅%, `f25`=年初至今%

### 行业板块列表

```bash
curl -s "http://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m:90+t:2&fields=f12,f14,f3" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: http://quote.eastmoney.com/"
```

返回：`f12`=板块代码(BK0xxx), `f14`=板块名, `f3`=涨跌幅%

### 板块成分股（查某板块下有哪些股票）

```bash
# 把 fs 改为 b:{板块代码}
curl -s "http://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=50&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=b:{BK0xxx}&fields=f12,f14,f3" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: http://quote.eastmoney.com/"
```

### 美股板块 ETF 动量（需 python + yfinance）

```bash
# 一行 python 查 11 大板块 ETF 近期涨跌
python3 -c "
import yfinance as yf
etfs = {'XLK':'科技','XLV':'医疗','XLF':'金融','XLY':'消费','XLC':'通信','XLI':'工业','XLE':'能源','XLP':'必需','XLU':'公用','XLRE':'地产','XLB':'材料'}
for sym,name in etfs.items():
    t = yf.Ticker(sym)
    h = t.history(period='5d')
    if len(h)>=2:
        chg = (h['Close'].iloc[-1]/h['Close'].iloc[0]-1)*100
        print(f'{name}({sym}): {chg:.1f}%')
"
```

> 注意：需要 `pip install yfinance`，首次使用可能需安装。如果 yfinance 不可用，改用东财美股 K线接口查 ETF。

---

## 技术指标（基于 K 线数据计算）

用户问 MA/RSI/KDJ/MACD 等技术指标时，**先拉 K 线数据，再用 python 计算**：

```bash
# 步骤 1：拉取 K 线（至少 60 条用于计算 MA60）
curl -s "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={SECID}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&beg=0&end=20500000&lmt=120" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  -H "Referer: https://quote.eastmoney.com/"

# 步骤 2：python 计算（一次性输出所有指标）
python3 -c "
import json, sys

# 假设 klines 是上面 curl 拿到的 JSON 解析后的 data.klines 数组
# 每条格式: '日期,开,收,高,低,量'
data = json.loads(sys.stdin.read())
klines = [k.split(',') for k in data['data']['klines']]
closes = [float(k[2]) for k in klines]
highs = [float(k[3]) for k in klines]
lows = [float(k[4]) for k in klines]
volumes = [float(k[5]) for k in klines]

# MA（移动平均线）
def ma(arr, n): return sum(arr[-n:])/n if len(arr)>=n else None
print(f'MA5={ma(closes,5):.2f}, MA10={ma(closes,10):.2f}, MA20={ma(closes,20):.2f}, MA60={ma(closes,60):.2f}')

# RSI（相对强弱指标，14日）
gains, losses = [], []
for i in range(1, min(15, len(closes))):
    diff = closes[-i] - closes[-i-1]
    gains.append(max(diff, 0))
    losses.append(max(-diff, 0))
avg_gain = sum(gains)/14 if gains else 0
avg_loss = sum(losses)/14 if losses else 1
rsi = 100 - 100/(1+avg_gain/avg_loss) if avg_loss else 100
print(f'RSI14={rsi:.1f}')

# MACD（12/26/9）
def ema(arr, n):
    k = 2/(n+1)
    result = arr[0]
    for v in arr[1:]: result = v*k + result*(1-k)
    return result
ema12 = ema(closes[-26:], 12)
ema26 = ema(closes[-26:], 26)
dif = ema12 - ema26
print(f'MACD_DIF={dif:.3f}')

print(f'当前价={closes[-1]:.2f}, 最新量={volumes[-1]:.0f}')
"
```

**常见技术信号判断**：
- MA5 > MA10 > MA20 → 多头排列（看涨）
- RSI > 70 → 超买区；RSI < 30 → 超卖区
- MACD DIF 由负转正 → 金叉（买入信号）
- 量比 > 2 → 放量（注意：量比 = 当日量 / 过去 5 日均量）

---

## 分钟 K 线（腾讯，日内交易分析）

```bash
# 5分钟K线（A股/港股）
curl -s "http://ifzq.gtimg.cn/appstock/app/kline/mkline?param=sh600519,m5,,320" \
  -H "User-Agent: Mozilla/5.0" -H "Referer: http://stockhtm.finance.qq.com"
```

参数：`m5`(5分钟) / `m15`(15分钟) / `m30`(30分钟) / `m60`(60分钟)，末尾数字为条数

---

## 附加能力

### 代码搜索（不确定 ticker 时先查）

```bash
curl -s "https://searchapi.eastmoney.com/api/suggest/get?input={关键词}&type=14&token=D43BF722C8E33BDC906FB84D85E326E8"
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
1. 判断用户要什么（行情/K线/估值/财务/板块/技术指标）
2. 按「路由逻辑」表选对应 API
3. 一次 shell(curl) 搞定（技术指标额外加一步 python 计算）
4. 解析响应，直接回答

❌ 绕路（禁止）：
1. web_search("茅台股价")（搜索引擎拿不到实时行情）
2. web_fetch("https://finance.sina.com.cn/...")（网页需 JS 渲染）
3. 多次 curl 同一个 API（批量查询用逗号拼接一次搞定）
4. 忘记 iconv 导致乱码后再重试（第一次就要带）
5. 安装大型库来查数据（能 curl 的就不要 pip install）
```

**铁律**：
- 实时行情 → 腾讯（一个接口覆盖 A/港/美，含 PE/PB/市值）
- K线/估值/财务/板块 → 东财（全免费，无需 key）
- 技术指标 → 拉K线 + python 计算（不要调第三方库）
- 美股板块 → yfinance 或东财 K 线查 ETF
- 腾讯行情已含 PE/PB（字段 39、43），**简单估值查询不用单独调东财**
- 东财 `ut` 和 `token` 是公开固定值，直接用
- 非交易时段返回最近一个交易日收盘数据，正常返回即可
- 美股交易所后缀不确定时先 `.O`(纳斯达克)，无数据再试 `.N`(纽交所)

activate_tools: shell, generate_chart
