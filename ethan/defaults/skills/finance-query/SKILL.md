# 金融行情查询

## 触发关键词
A股, 股票, 上证, 深证, 指数, 行情, 大盘, 涨跌, 基金, 净值, 港股, 美股, 收盘, 开盘, K线, PE, PB, 估值, 市值, 财报, ROE, 板块, 涨幅榜, 市盈率, 茅台, 腾讯, 苹果, AAPL, TSLA

## 核心原则

查询股票/指数行情时，**优先使用以下免费 API**，不要依赖 web_search（搜索引擎对实时行情结果极差）。

---

## 一、实时行情（腾讯财经 + 新浪）

### 1.1 腾讯财经（推荐，A/港/美统一接口）

```bash
# A股（沪：sh+代码，深：sz+代码）
curl -s "http://qt.gtimg.cn/q=sh600519" -H "User-Agent: Mozilla/5.0" | iconv -f GBK -t UTF-8

# 港股（hk+5位代码）
curl -s "http://qt.gtimg.cn/q=hk00700" -H "User-Agent: Mozilla/5.0" | iconv -f GBK -t UTF-8

# 美股（us+ticker小写）
curl -s "http://qt.gtimg.cn/q=usAAPL" -H "User-Agent: Mozilla/5.0" | iconv -f GBK -t UTF-8

# 批量查询
curl -s "http://qt.gtimg.cn/q=sh600519,hk00700,usAAPL" -H "User-Agent: Mozilla/5.0" | iconv -f GBK -t UTF-8
```

**代码前缀规则**：
- A股沪市（6/9开头）: `sh` + 代码
- A股深市（0/3开头）: `sz` + 代码
- 上证指数: `sh000001`，深证成指: `sz399001`，创业板指: `sz399006`
- 港股: `hk` + 5位代码（如 `hk00700` = 腾讯）
- 美股: `us` + ticker大写（如 `usAAPL`, `usTSLA`, `usGOOGL`）

**响应格式**：`v_sh600519="字段0~字段1~字段2~...";`，以 `~` 分隔

**关键字段索引**：
| 索引 | 含义 | 索引 | 含义 |
|------|------|------|------|
| 1 | 名称 | 3 | 现价 |
| 4 | 昨收 | 5 | 开盘 |
| 6 | 成交量(手) | 30 | 更新时间 |
| 31 | 涨跌额 | 32 | 涨跌幅% |
| 33 | 最高 | 34 | 最低 |
| 38 | 换手率% | 39 | PE(TTM) |
| 43 | PB | 44 | 总市值(元) |

### 1.2 新浪财经（A股备选）

```bash
curl -s -H "Referer: http://finance.sina.com.cn" "http://hq.sinajs.cn/list=sh000001" | iconv -f GBK -t UTF-8
```

字段：名称,今开,昨收,当前价,最高,最低,买一,卖一,成交量(股),成交额(元)...

---

## 二、K线历史数据

### 2.1 腾讯日K线（A股/美股，支持复权）

```bash
# A股日K（后复权，最近260天）
curl -s "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600519,day,,,260,hfq" \
  -H "User-Agent: Mozilla/5.0" \
  -H "Referer: http://stockhtm.finance.qq.com"
```

- 复权参数：`qfq`(前复权) / `hfq`(后复权) / 空(不复权)
- 响应是 JSONP，解析方式：`text.split("=", 1)[-1].rstrip(";")`
- K线数据格式：`[日期, 开盘, 收盘, 最高, 最低, 成交量]`
- 美股代码需加后缀：纳斯达克 `.OQ`，纽交所 `.N`（如 `usAAPL.OQ`）

### 2.2 东方财富日K线（全市场，推荐美股/港股）

```bash
# A股（secid=1.代码 沪市 / 0.代码 深市）
curl -s "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.600519&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&beg=0&end=20500000&lmt=60" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  -H "Referer: https://quote.eastmoney.com/"

# 美股（secid=105.TICKER）
curl -s "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=105.AAPL&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&beg=0&end=20500000&lmt=60" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  -H "Referer: https://quote.eastmoney.com/"

# 港股（secid=116.代码）
curl -s "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=116.00700&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&beg=0&end=20500000&lmt=60" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36" \
  -H "Referer: https://quote.eastmoney.com/"
```

**SECID 规则**：
- A股沪市(6/9开头): `1.代码`
- A股深市(0/3开头): `0.代码`
- 美股: `105.TICKER`
- 港股: `116.代码`

**参数**：`klt=101`(日线) / `klt=102`(周线) / `klt=103`(月线)；`fqt=1`(前复权) / `fqt=2`(后复权)

**响应**：`data.klines` 数组，每条 `"日期,开,收,高,低,量"`

---

## 三、估值指标（PE/PB）

### 3.1 东方财富估值接口

```bash
# A股 PE/PB
curl -s "https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_DMSK_NEWINDICATOR&columns=SECURITY_CODE,SECUCODE&quoteColumns=f115~01~SECURITY_CODE~PE_TTM,f23~01~SECURITY_CODE~PB_NEW_NOTICE&filter=(SECUCODE=%22600519.SH%22)&pageNumber=1&pageSize=1&source=HSF10&client=PC" \
  -H "User-Agent: Mozilla/5.0" \
  -H "Referer: https://data.eastmoney.com/"

# 美股 PE/PB
curl -s "https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_USF10_DATA_MAININDICATOR&columns=ALL&filter=(SECURITY_CODE=%22AAPL%22)&pageNumber=1&pageSize=1&sortTypes=-1&sortColumns=REPORT_DATE&source=INTLSECURITIES&client=PC" \
  -H "User-Agent: Mozilla/5.0" \
  -H "Referer: https://data.eastmoney.com/"

# 港股 PE/PB
curl -s "https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_CUSTOM_HKF10_FN_MAININDICATORMAX&columns=ALL&filter=(SECURITY_CODE=%2200700%22)&pageNumber=1&pageSize=1&sortTypes=-1&sortColumns=REPORT_DATE&source=F10&client=PC" \
  -H "User-Agent: Mozilla/5.0" \
  -H "Referer: https://data.eastmoney.com/"
```

**A股代码格式**：沪市 `{code}.SH`，深市 `{code}.SZ`

---

## 四、A股财务数据（利润/ROE）

```bash
# A股主要财务指标（近10期）
curl -s "https://datacenter.eastmoney.com/securities/api/data/get?type=RPT_F10_FINANCE_MAINFINADATA&sty=APP_F10_MAINFINADATA&filter=(SECUCODE=%22600519.SH%22)&p=1&ps=10&sr=-1&st=REPORT_DATE&source=HSF10&client=PC" \
  -H "User-Agent: Mozilla/5.0" \
  -H "Referer: https://emweb.securities.eastmoney.com/"
```

**关键返回字段**：
- `PARENTNETPROFIT`: 归母净利润
- `KCFJCXSYJLR`: 扣非净利润
- `TOTALOPERATEREVE`: 营业总收入
- `BASIC_EPS`: 基本每股收益
- `WEIGHTAVG_ROE`: 加权平均ROE

---

## 五、板块与全市场快照

### 5.1 A股全市场涨跌幅排名

```bash
# 涨幅前20
curl -s "http://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=20&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14,f3,f24,f25" \
  -H "User-Agent: Mozilla/5.0" \
  -H "Referer: http://quote.eastmoney.com/center/gridlist.html"
```

字段：`f12`=代码, `f14`=名称, `f3`=今日涨跌幅%, `f24`=60日涨幅%, `f25`=年初至今涨幅%

### 5.2 行业板块列表

```bash
curl -s "http://82.push2.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m:90+t:2&fields=f12,f14,f3" \
  -H "User-Agent: Mozilla/5.0" \
  -H "Referer: http://quote.eastmoney.com/"
```

### 5.3 代码搜索（ticker → secid）

```bash
curl -s "https://searchapi.eastmoney.com/api/suggest/get?input=AAPL&type=14&token=D43BF722C8E33BDC906FB84D85E326E8"
```

---

## 六、生成走势图

拿到 K 线数据后，使用 `generate_chart` 工具生成走势图：

```json
{
  "type": "line",
  "data": {
    "labels": ["2026-07-01", "2026-07-02", "..."],
    "datasets": [{
      "label": "贵州茅台",
      "data": [1850.0, 1862.5, "..."],
      "borderColor": "rgb(255, 99, 132)",
      "fill": false
    }]
  },
  "options": {"plugins": {"title": {"display": true, "text": "贵州茅台 近30日走势"}}}
}
```

---

## 七、注意事项

1. **编码**：腾讯/新浪接口返回 GBK，必须 `iconv -f GBK -t UTF-8`
2. **Headers**：所有接口必须带 User-Agent；新浪需 Referer；东财需 Referer
3. **交易时间**：A股 9:30-15:00，港股 9:30-16:00，美股 21:30-4:00（北京时间）
4. **非交易时段**返回最近一个交易日的收盘数据
5. **东财 ut/token**：`bd1d9ddb04089700cf9c27f6f7426281` 和 `D43BF722C8E33BDC906FB84D85E326E8` 是公开固定值
6. **限速**：连续请求间隔至少 1 秒
7. **优先级**：实时行情用腾讯 → 新浪兜底；K线/估值用东财

## 工具依赖
activate_tools: shell, generate_chart
