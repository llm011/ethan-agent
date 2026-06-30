"use client";

// 临时测试页：直接喂样例 A2UI envelope 验证卡片渲染（验证完即删）。
import { A2uiCard } from "@/components/chat/a2ui-card";

const CATALOG = "https://a2ui.org/specification/v0_9_1/catalogs/basic/catalog.json";

const compareCard = [
  { version: "v0.9.1", createSurface: { surfaceId: "compare", catalogId: CATALOG } },
  { version: "v0.9.1", updateComponents: { surfaceId: "compare", components: [
    { id: "root", component: "Card", child: "col" },
    { id: "col", component: "Column", children: ["title", "row"] },
    { id: "title", component: "Text", text: "PyTorch vs JAX", variant: "h3" },
    { id: "row", component: "Row", justify: "spaceBetween", children: ["left", "right"] },
    { id: "left", component: "Column", weight: 1, children: ["l-h", "l-1", "l-2"] },
    { id: "l-h", component: "Text", text: "PyTorch", variant: "h4" },
    { id: "l-1", component: "Text", text: "- 生态最大\n- 上手快" },
    { id: "l-2", component: "Text", text: "- 社区 90%+" },
    { id: "right", component: "Column", weight: 1, children: ["r-h", "r-1", "r-2"] },
    { id: "r-h", component: "Text", text: "JAX", variant: "h4" },
    { id: "r-1", component: "Text", text: "- 函数式 + JIT\n- TPU 性能强" },
    { id: "r-2", component: "Text", text: "- 学习曲线陡" },
  ] } },
];

const statsCard = [
  { version: "v0.9.1", createSurface: { surfaceId: "stat", catalogId: CATALOG } },
  { version: "v0.9.1", updateComponents: { surfaceId: "stat", components: [
    { id: "root", component: "Card", child: "col" },
    { id: "col", component: "Column", children: ["name", "value", "trend"] },
    { id: "name", component: "Text", text: { path: "/metricName" }, variant: "caption" },
    { id: "value", component: "Text", text: { call: "formatCurrency", args: { value: { path: "/value" }, currency: "CNY" }, returnType: "string" }, variant: "h1" },
    { id: "trend", component: "Text", text: { call: "formatString", args: { value: "较上月 +${/trendPercent}%" } }, variant: "body" },
  ] } },
  { version: "v0.9.1", updateDataModel: { surfaceId: "stat", value: { metricName: "本月营收", value: 48294, trendPercent: 12.5 } } },
];

const shippingCard = [
  { version: "v0.9.1", createSurface: { surfaceId: "ship", catalogId: CATALOG } },
  { version: "v0.9.1", updateComponents: { surfaceId: "ship", components: [
    { id: "root", component: "Card", child: "col" },
    { id: "col", component: "Column", children: ["hd", "div", "list", "eta"] },
    { id: "hd", component: "Text", text: "包裹状态", variant: "h3" },
    { id: "div", component: "Divider" },
    { id: "list", component: "Column", children: { path: "/steps", componentId: "tpl" } },
    { id: "tpl", component: "Row", align: "center", children: ["ic", "tx"] },
    { id: "ic", component: "Icon", name: { path: "icon" } },
    { id: "tx", component: "Text", text: { path: "label" } },
    { id: "eta", component: "Text", text: { path: "/eta" }, variant: "caption" },
  ] } },
  { version: "v0.9.1", updateDataModel: { surfaceId: "ship", value: { steps: [
    { icon: "check", label: "已下单" },
    { icon: "check", label: "已发货" },
    { icon: "send", label: "派送中" },
  ], eta: "预计今天 20:00 送达" } } },
];

const buttonCard = [
  { version: "v0.9.1", createSurface: { surfaceId: "act", catalogId: CATALOG } },
  { version: "v0.9.1", updateComponents: { surfaceId: "act", components: [
    { id: "root", component: "Card", child: "col" },
    { id: "col", component: "Column", children: ["q", "btn"] },
    { id: "q", component: "Text", text: "要继续部署到生产吗？" },
    { id: "btn", component: "Button", variant: "primary", child: "btn-label", action: { event: { name: "confirm_deploy", context: { env: "prod" } } } },
    { id: "btn-label", component: "Text", text: "确认部署" },
  ] } },
];

const timelineCard = [
  { version: "v0.9.1", createSurface: { surfaceId: "trip", catalogId: CATALOG } },
  { version: "v0.9.1", updateComponents: { surfaceId: "trip", components: [
    { id: "root", component: "Card", child: "col" },
    { id: "col", component: "Column", children: ["hd", "tl"] },
    { id: "hd", component: "Text", text: "丽江三日攻略", variant: "h3" },
    { id: "tl", component: "Timeline", children: ["d1", "d2", "d3"] },
    { id: "d1", component: "Column", children: ["d1t", "d1b"] },
    { id: "d1t", component: "Text", text: "Day 1 · 抵达", variant: "h4" },
    { id: "d1b", component: "Text", text: "- 古城闲逛\n- 四方街吃晚餐" },
    { id: "d2", component: "Column", children: ["d2t", "d2b"] },
    { id: "d2t", component: "Text", text: "Day 2 · 雪山", variant: "h4" },
    { id: "d2b", component: "Text", text: "- 玉龙雪山缆车\n- 蓝月谷" },
    { id: "d3", component: "Column", children: ["d3t", "d3b"] },
    { id: "d3t", component: "Text", text: "Day 3 · 束河", variant: "h4" },
    { id: "d3b", component: "Text", text: "- 束河古镇\n- 返程" },
  ] } },
];

const rankList = [
  { version: "v0.9.1", createSurface: { surfaceId: "rank", catalogId: CATALOG } },
  { version: "v0.9.1", updateComponents: { surfaceId: "rank", components: [
    { id: "root", component: "Card", child: "col" },
    { id: "col", component: "Column", children: ["hd", "list"] },
    { id: "hd", component: "Text", text: "本周热门框架", variant: "h3" },
    { id: "list", component: "List", children: { path: "/items", componentId: "tpl" } },
    { id: "tpl", component: "Row", align: "center", justify: "spaceBetween", children: ["nm", "sc"] },
    { id: "nm", component: "Text", text: { path: "name" } },
    { id: "sc", component: "Text", text: { path: "score" }, variant: "caption" },
  ] } },
  { version: "v0.9.1", updateDataModel: { surfaceId: "rank", value: { items: [
    { name: "1. PyTorch", score: "★ 48.2k" },
    { name: "2. TensorFlow", score: "★ 31.5k" },
    { name: "3. JAX", score: "★ 22.1k" },
  ] } } },
];

// 论文解读评价卡实验：标题 + arXiv + 三维评分 + 核心结论 + 关键指标
const paperCard = [
  { version: "v0.9.1", createSurface: { surfaceId: "paper", catalogId: CATALOG } },
  { version: "v0.9.1", updateComponents: { surfaceId: "paper", components: [
    { id: "root", component: "Card", child: "col" },
    { id: "col", component: "Column", children: ["title", "arxiv", "div1", "scoreRow", "div2", "concl", "metrics"] },
    { id: "title", component: "Text", text: "Attention Is All You Need", variant: "h3" },
    { id: "arxiv", component: "Text", text: "arXiv:1706.03762 · Transformer", variant: "caption" },
    { id: "div1", component: "Divider" },
    { id: "scoreRow", component: "Row", justify: "spaceBetween", children: ["s1", "s2", "s3"] },
    { id: "s1", component: "Column", weight: 1, children: ["s1l", "s1v"] },
    { id: "s1l", component: "Text", text: "创新性", variant: "caption" },
    { id: "s1v", component: "Text", text: "★★★★★" },
    { id: "s2", component: "Column", weight: 1, children: ["s2l", "s2v"] },
    { id: "s2l", component: "Text", text: "实用性", variant: "caption" },
    { id: "s2v", component: "Text", text: "★★★★★" },
    { id: "s3", component: "Column", weight: 1, children: ["s3l", "s3v"] },
    { id: "s3l", component: "Text", text: "严谨性", variant: "caption" },
    { id: "s3v", component: "Text", text: "★★★★☆" },
    { id: "div2", component: "Divider" },
    { id: "concl", component: "Text", text: "**核心结论**：纯注意力机制取代 RNN/CNN，完全并行、长程依赖更强。" },
    { id: "metrics", component: "Column", children: ["m1", "m2"] },
    { id: "m1", component: "Row", justify: "spaceBetween", children: ["m1k", "m1v"] },
    { id: "m1k", component: "Text", text: "EN-DE BLEU" },
    { id: "m1v", component: "Text", text: "28.4 (SOTA)" },
    { id: "m2", component: "Row", justify: "spaceBetween", children: ["m2k", "m2v"] },
    { id: "m2k", component: "Text", text: "训练成本" },
    { id: "m2v", component: "Text", text: "↓ 数量级" },
  ] } },
];

export default function A2uiTestPage() {
  return (
    <div className="max-w-2xl mx-auto p-8 space-y-6">
      <h1 className="text-xl font-bold">A2UI 卡片渲染测试</h1>
      <section>
        <h2 className="text-sm text-muted-foreground mb-1">对比卡</h2>
        <A2uiCard surfaces={compareCard} onAction={(t) => alert(t)} />
      </section>
      <section>
        <h2 className="text-sm text-muted-foreground mb-1">统计卡（formatCurrency + formatString）</h2>
        <A2uiCard surfaces={statsCard} />
      </section>
      <section>
        <h2 className="text-sm text-muted-foreground mb-1">状态卡（模板列表 + Icon）</h2>
        <A2uiCard surfaces={shippingCard} />
      </section>
      <section>
        <h2 className="text-sm text-muted-foreground mb-1">交互卡（按钮）</h2>
        <A2uiCard surfaces={buttonCard} onAction={(t) => alert(t)} />
      </section>
      <section>
        <h2 className="text-sm text-muted-foreground mb-1">时间轴（旅游攻略）</h2>
        <A2uiCard surfaces={timelineCard} />
      </section>
      <section>
        <h2 className="text-sm text-muted-foreground mb-1">列表（排行）</h2>
        <A2uiCard surfaces={rankList} />
      </section>
      <section>
        <h2 className="text-sm text-muted-foreground mb-1">论文解读评价卡（实验）</h2>
        <A2uiCard surfaces={paperCard} />
      </section>
    </div>
  );
}
