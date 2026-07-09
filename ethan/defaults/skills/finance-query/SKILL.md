# 金融行情查询

## 触发关键词
A股, 股票, 上证, 深证, 指数, 行情, 大盘, 涨跌, 基金, 净值, 港股, 美股, 收盘, 开盘

## 核心原则

查询中国 A 股/指数实时和历史行情数据时，**优先使用以下免费 API**，不要依赖 web_search（搜索引擎对实时行情结果很差）。

### 1. 新浪财经实时行情（推荐）

```bash
# 上证指数
curl -s -H "Referer: http://finance.sina.com.cn" "http://hq.sinajs.cn/list=sh000001"

# 深证成指
curl -s -H "Referer: http://finance.sina.com.cn" "http://hq.sinajs.cn/list=sz399001"

# 个股（如贵州茅台 600519）
curl -s -H "Referer: http://finance.sina.com.cn" "http://hq.sinajs.cn/list=sh600519"

# 批量查询（逗号分隔）
curl -s -H "Referer: http://finance.sina.com.cn" "http://hq.sinajs.cn/list=sh000001,sz399001,sh600519"
```

**返回格式**（GBK 编码，需 iconv 或直接解析）：
```
var hq_str_sh000001="上证指数,3000.12,2998.55,3005.67,3010.00,2995.00,0,0,436789012,52345678901,..."
```
字段顺序：名称,今开,昨收,当前价,最高,最低,买一,卖一,成交量(股),成交额(元),买一量,买一价,...

**解码 GBK**：
```bash
curl -s -H "Referer: http://finance.sina.com.cn" "http://hq.sinajs.cn/list=sh000001" | iconv -f GBK -t UTF-8
```

### 2. 历史 K 线（新浪）

```bash
# 日K线（最近 N 天）—— 返回 JSON
curl -s "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh000001&scale=240&ma=no&datalen=30"
```

返回 JSON 数组：`[{"day":"2026-06-10","open":"3001.23","high":"3015.67","low":"2998.45","close":"3010.89","volume":"34567890"}, ...]`

### 3. 东方财富 API（备选）

```bash
# 上证指数实时
curl -s "http://push2.eastmoney.com/api/qt/stock/get?secid=1.000001&fields=f43,f44,f45,f46,f47,f48,f57,f58,f169,f170"
```

### 4. 生成走势图

拿到历史数据后，使用 `generate_chart` 工具生成走势图（Chart.js 配置）：

```json
{
  "type": "line",
  "data": {
    "labels": ["日期1", "日期2", ...],
    "datasets": [{
      "label": "上证指数",
      "data": [3001, 3015, ...],
      "borderColor": "rgb(255, 99, 132)",
      "fill": false
    }]
  }
}
```

### 5. 注意事项

- **必须带 Referer**：新浪接口不带 Referer 会返回空数据
- **编码问题**：hq.sinajs.cn 返回 GBK 编码，用 `iconv -f GBK -t UTF-8` 转码
- **交易时间**：A 股交易时间 9:30-15:00（北京时间），非交易时段返回上一交易日收盘数据
- **港股/美股代码规则**：港股前缀 `hk`（如 `hk00700`），美股用 `.`（如 `gb_aapl`）

## 工具依赖
activate_tools: shell, generate_chart
