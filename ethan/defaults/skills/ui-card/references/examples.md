# A2UI 卡片示例（照着改）

每个示例都是完整的 `ui_card` 工具 `messages` 参数，直接拿去改文案即可。
catalogId 统一用 `https://a2ui.org/specification/v0_9_1/catalogs/basic/catalog.json`（下面缩写成 CATALOG）。

## 1. 对比卡（两栏并排）

```json
{"messages":[
  {"version":"v0.9.1","createSurface":{"surfaceId":"compare","catalogId":"CATALOG"}},
  {"version":"v0.9.1","updateComponents":{"surfaceId":"compare","components":[
    {"id":"root","component":"Card","child":"col"},
    {"id":"col","component":"Column","children":["title","row"]},
    {"id":"title","component":"Text","text":"PyTorch vs JAX","variant":"h3"},
    {"id":"row","component":"Row","justify":"spaceBetween","children":["left","right"]},
    {"id":"left","component":"Column","weight":1,"children":["l-h","l-1","l-2"]},
    {"id":"l-h","component":"Text","text":"PyTorch","variant":"h4"},
    {"id":"l-1","component":"Text","text":"- 生态最大\n- 上手快"},
    {"id":"l-2","component":"Text","text":"- 社区 90%+"},
    {"id":"right","component":"Column","weight":1,"children":["r-h","r-1","r-2"]},
    {"id":"r-h","component":"Text","text":"JAX","variant":"h4"},
    {"id":"r-1","component":"Text","text":"- 函数式 + JIT\n- TPU 性能强"},
    {"id":"r-2","component":"Text","text":"- 学习曲线陡"}
  ]}}
]}
```

## 2. 状态/进度卡（图标 + 步骤）

```json
{"messages":[
  {"version":"v0.9.1","createSurface":{"surfaceId":"ship","catalogId":"CATALOG"}},
  {"version":"v0.9.1","updateComponents":{"surfaceId":"ship","components":[
    {"id":"root","component":"Card","child":"col"},
    {"id":"col","component":"Column","children":["hd","div","s1","s2","s3","eta"]},
    {"id":"hd","component":"Text","text":"包裹状态","variant":"h3"},
    {"id":"div","component":"Divider"},
    {"id":"s1","component":"Row","align":"center","children":["i1","t1"]},
    {"id":"i1","component":"Icon","name":"check"},
    {"id":"t1","component":"Text","text":"已下单"},
    {"id":"s2","component":"Row","align":"center","children":["i2","t2"]},
    {"id":"i2","component":"Icon","name":"check"},
    {"id":"t2","component":"Text","text":"已发货"},
    {"id":"s3","component":"Row","align":"center","children":["i3","t3"]},
    {"id":"i3","component":"Icon","name":"send"},
    {"id":"t3","component":"Text","text":"派送中"},
    {"id":"eta","component":"Text","text":"预计今天 20:00 送达","variant":"caption"}
  ]}}
]}
```

## 3. 统计卡（数据绑定 + 格式化）

```json
{"messages":[
  {"version":"v0.9.1","createSurface":{"surfaceId":"stat","catalogId":"CATALOG"}},
  {"version":"v0.9.1","updateComponents":{"surfaceId":"stat","components":[
    {"id":"root","component":"Card","child":"col"},
    {"id":"col","component":"Column","children":["name","value","trend"]},
    {"id":"name","component":"Text","text":{"path":"/metricName"},"variant":"caption"},
    {"id":"value","component":"Text","text":{"call":"formatCurrency","args":{"value":{"path":"/value"},"currency":"CNY"},"returnType":"string"},"variant":"h1"},
    {"id":"trend","component":"Text","text":{"call":"formatString","args":{"value":"较上月 +${/trendPercent}%"}},"variant":"body"}
  ]}},
  {"version":"v0.9.1","updateDataModel":{"surfaceId":"stat","value":{"metricName":"本月营收","value":48294,"trendPercent":12.5}}}
]}
```

## 4. 模板列表（数组渲染成多行）

`children` 用模板对象 `{"path":"/list","componentId":"模板id"}`，模板里用**相对路径**（不带前导 `/`）取数组每项的字段。

```json
{"messages":[
  {"version":"v0.9.1","createSurface":{"surfaceId":"todo","catalogId":"CATALOG"}},
  {"version":"v0.9.1","updateComponents":{"surfaceId":"todo","components":[
    {"id":"root","component":"Card","child":"list"},
    {"id":"list","component":"Column","children":{"path":"/items","componentId":"tpl"}},
    {"id":"tpl","component":"Row","align":"center","children":["ic","tx"]},
    {"id":"ic","component":"Icon","name":{"path":"icon"}},
    {"id":"tx","component":"Text","text":{"path":"label"}}
  ]}},
  {"version":"v0.9.1","updateDataModel":{"surfaceId":"todo","value":{"items":[
    {"icon":"check","label":"写方案"},
    {"icon":"star","label":"评审"},
    {"icon":"send","label":"上线"}
  ]}}}
]}
```

## 5. 带按钮的交互卡

Button 必须有 `child`（标签 Text）和 `action`。点击后前端把 event 当作新一轮用户消息发回 agent。

```json
{"messages":[
  {"version":"v0.9.1","createSurface":{"surfaceId":"act","catalogId":"CATALOG"}},
  {"version":"v0.9.1","updateComponents":{"surfaceId":"act","components":[
    {"id":"root","component":"Card","child":"col"},
    {"id":"col","component":"Column","children":["q","btn"]},
    {"id":"q","component":"Text","text":"要继续部署到生产吗？"},
    {"id":"btn","component":"Button","variant":"primary","child":"btn-label","action":{"event":{"name":"confirm_deploy","context":{"env":"prod"}}}},
    {"id":"btn-label","component":"Text","text":"确认部署"}
  ]}}
]}
```

## 6. 时间轴（行程/攻略/进度）

`Timeline` 是扩展组件：`children` 数组，每个节点是一个 Column/Card，渲染时自动带竖向连线 + 圆点。

```json
{"messages":[
  {"version":"v0.9.1","createSurface":{"surfaceId":"trip","catalogId":"CATALOG"}},
  {"version":"v0.9.1","updateComponents":{"surfaceId":"trip","components":[
    {"id":"root","component":"Card","child":"col"},
    {"id":"col","component":"Column","children":["hd","tl"]},
    {"id":"hd","component":"Text","text":"三日攻略","variant":"h3"},
    {"id":"tl","component":"Timeline","children":["d1","d2","d3"]},
    {"id":"d1","component":"Column","children":["d1t","d1b"]},
    {"id":"d1t","component":"Text","text":"Day 1 · 抵达","variant":"h4"},
    {"id":"d1b","component":"Text","text":"- 古城闲逛\n- 当地晚餐"},
    {"id":"d2","component":"Column","children":["d2t","d2b"]},
    {"id":"d2t","component":"Text","text":"Day 2 · 主景点","variant":"h4"},
    {"id":"d2b","component":"Text","text":"- 雪山缆车\n- 蓝月谷"},
    {"id":"d3","component":"Column","children":["d3t","d3b"]},
    {"id":"d3t","component":"Text","text":"Day 3 · 返程","variant":"h4"},
    {"id":"d3b","component":"Text","text":"- 古镇\n- 返程"}
  ]}}
]}
```

