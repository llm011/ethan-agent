// 自定义 A2UI catalog：用项目的 shadcn/ui + Tailwind + lucide 实现各 A2UI 组件，
// 替换 @a2ui/react 的裸 basicCatalog。协议的数据绑定/函数(formatCurrency 等)沿用 basicCatalog。
// A2UI 设计上 catalog 可替换，这是让卡片贴合产品设计系统的正确做法。

import { Fragment, type ReactNode, type CSSProperties } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import * as Lucide from "lucide-react";
import { Catalog } from "@a2ui/web_core/v0_9";
import {
  createComponentImplementation,
  Text as BasicText,
  Image as BasicImage,
  Icon as BasicIcon,
  Row as BasicRow,
  Column as BasicColumn,
  List as BasicList,
  Card as BasicCard,
  Divider as BasicDivider,
  Button as BasicButton,
  basicCatalog,
  type ReactComponentImplementation,
} from "@a2ui/react/v0_9";
import { Card } from "@ethan/shared/ui/card";
import { Button as ShadButton } from "@ethan/shared/ui/button";
import { Separator } from "@ethan/shared/ui/separator";

type ChildRef = string | { id: string; basePath?: string };
type BuildChild = (id: string, basePath?: string) => ReactNode;

function renderChildren(children: unknown, buildChild: BuildChild): ReactNode {
  if (!Array.isArray(children)) return null;
  return (children as ChildRef[]).map((ref, i) => {
    if (typeof ref === "string") return <Fragment key={`${ref}-${i}`}>{buildChild(ref)}</Fragment>;
    return <Fragment key={`${ref.id}-${ref.basePath ?? i}`}>{buildChild(ref.id, ref.basePath)}</Fragment>;
  });
}

function weightStyle(weight: unknown): CSSProperties {
  return typeof weight === "number" && weight > 0 ? { flex: weight, minWidth: 0 } : {};
}

// ── Text：标题用 Tailwind 字号层级；body 走 markdown；caption 弱化 ──
const HEADING_CLASS: Record<string, string> = {
  h1: "text-xl font-semibold tracking-tight",
  h2: "text-lg font-semibold tracking-tight",
  h3: "text-base font-semibold",
  h4: "text-sm font-semibold",
  h5: "text-sm font-medium",
};

const Text = createComponentImplementation(BasicText, ({ props }: any) => {
  const text = typeof props.text === "string" ? props.text : String(props.text ?? "");
  const variant: string = props.variant || "body";
  // 排行榜序号徽章：带底色的圆，和正文区分开
  if (variant === "rankBadge") {
    return (
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary tabular-nums">
        {text}
      </div>
    );
  }
  if (HEADING_CLASS[variant]) {
    return <div className={HEADING_CLASS[variant]} style={weightStyle(props.weight)}>{text}</div>;
  }
  if (variant === "caption") {
    return <div className="text-xs text-muted-foreground" style={weightStyle(props.weight)}>{text}</div>;
  }
  // body：渲染 markdown（粗体/列表/链接），用紧凑 prose
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none text-sm leading-relaxed [&>:first-child]:mt-0 [&>:last-child]:mb-0" style={weightStyle(props.weight)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
});

// ── Card：用 shadcn Card ──
const CardImpl = createComponentImplementation(BasicCard, ({ props, buildChild }: any) => (
  <Card className="p-4 gap-3 border border-border shadow-md ring-0" style={weightStyle(props.weight)}>
    {props.child ? buildChild(props.child) : null}
  </Card>
));

// ── Row / Column：flex + gap ──
const mapJustify: Record<string, string> = {
  center: "justify-center", end: "justify-end", spaceAround: "justify-around",
  spaceBetween: "justify-between", spaceEvenly: "justify-evenly", start: "justify-start", stretch: "justify-stretch",
};
const mapAlign: Record<string, string> = {
  start: "items-start", center: "items-center", end: "items-end", stretch: "items-stretch",
};

const Row = createComponentImplementation(BasicRow, ({ props, buildChild }: any) => (
  <div
    className={`flex flex-row gap-3 ${mapJustify[props.justify] || "justify-start"} ${mapAlign[props.align] || "items-start"}`}
    style={weightStyle(props.weight)}
  >
    {renderChildren(props.children, buildChild)}
  </div>
));

const Column = createComponentImplementation(BasicColumn, ({ props, buildChild }: any) => (
  <div
    className={`flex flex-col gap-2 ${mapJustify[props.justify] || "justify-start"} ${mapAlign[props.align] || "items-stretch"}`}
    style={weightStyle(props.weight)}
  >
    {renderChildren(props.children, buildChild)}
  </div>
));

const List = createComponentImplementation(BasicList, ({ props, buildChild }: any) => {
  const horizontal = props.direction === "horizontal";
  return (
    <div className={`flex ${horizontal ? "flex-row overflow-x-auto" : "flex-col"} gap-2`} style={weightStyle(props.weight)}>
      {renderChildren(props.children, buildChild)}
    </div>
  );
});

// ── Timeline：扩展组件（行程/攻略/进度）。复用 Column 的 schema（只绑定 children），
//    每个节点前置一个圆点，左侧一条贯穿竖向连线。颜色走设计 token。──
function renderTimelineChildren(children: unknown, buildChild: BuildChild): ReactNode {
  if (!Array.isArray(children)) return null;
  return (children as ChildRef[]).map((ref, i) => {
    const node = typeof ref === "string" ? buildChild(ref) : buildChild(ref.id, ref.basePath);
    const key = typeof ref === "string" ? `${ref}-${i}` : `${ref.id}-${ref.basePath ?? i}`;
    return (
      <div key={key} className="relative pl-7 pb-4 last:pb-0">
        {/* 节点圆点 */}
        <span className="absolute left-[5px] top-1.5 h-3 w-3 rounded-full bg-primary ring-2 ring-background" />
        {node}
      </div>
    );
  });
}

const TimelineImpl = createComponentImplementation(
  { name: "Timeline", schema: (BasicColumn as ReactComponentImplementation).schema },
  ({ props, buildChild }: any) => (
    <div className="relative" style={weightStyle(props.weight)}>
      {/* 贯穿竖向连线 */}
      <span className="absolute left-[10px] top-1.5 bottom-1.5 w-px bg-border" />
      {renderTimelineChildren(props.children, buildChild)}
    </div>
  ),
);


// ── Button：用 shadcn Button ──
const VARIANT_MAP: Record<string, "default" | "secondary" | "ghost"> = {
  primary: "default", borderless: "ghost", default: "secondary",
};
const ButtonImpl = createComponentImplementation(BasicButton, ({ props, buildChild }: any) => (
  <ShadButton
    type="button"
    variant={VARIANT_MAP[props.variant] || "secondary"}
    size="sm"
    onClick={props.action}
    disabled={props.isValid === false}
    style={weightStyle(props.weight)}
  >
    {props.child ? buildChild(props.child) : null}
  </ShadButton>
));

// ── Divider：用 shadcn Separator ──
const DividerImpl = createComponentImplementation(BasicDivider, ({ props }: any) => (
  <Separator orientation={props.axis === "vertical" ? "vertical" : "horizontal"} className="my-1" />
));

// ── Icon：映射到 lucide（A2UI 用 Material Symbols 字体名，这里转 lucide 组件）──
const ICON_MAP: Record<string, keyof typeof Lucide> = {
  check: "Check", check_circle: "CircleCheck", close: "X", send: "Send",
  info: "Info", warning: "TriangleAlert", error: "CircleX", star: "Star",
  favorite: "Heart", mail: "Mail", phone: "Phone", calendar: "Calendar",
  calendarToday: "Calendar", calendar_today: "Calendar", schedule: "Clock", clock: "Clock",
  trending_up: "TrendingUp", trendingUp: "TrendingUp", trending_down: "TrendingDown",
  arrow_upward: "ArrowUp", arrow_downward: "ArrowDown", arrow_forward: "ArrowRight",
  add: "Plus", remove: "Minus", search: "Search", settings: "Settings",
  home: "House", person: "User", location_on: "MapPin", shopping_cart: "ShoppingCart",
  local_shipping: "Truck", package: "Package", payment: "CreditCard", done: "Check",
};

const IconImpl = createComponentImplementation(BasicIcon, ({ props }: any) => {
  const name = typeof props.name === "string" ? props.name : "";
  const lucideName = ICON_MAP[name] || ICON_MAP[name.replace(/[A-Z]/g, (l: string) => "_" + l.toLowerCase())];
  const Cmp = (lucideName && (Lucide[lucideName] as React.ComponentType<{ className?: string }>)) || Lucide.Dot;
  return <Cmp className="h-4 w-4 text-muted-foreground shrink-0" />;
});

// ── Image：圆角 ──
const ImageImpl = createComponentImplementation(BasicImage, ({ props }: any) => {
  const variant: string = props.variant || "";
  const cls = variant === "avatar" ? "h-10 w-10 rounded-full object-cover"
    : variant === "icon" ? "h-6 w-6 object-contain"
    : "max-w-full rounded-lg object-cover";
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={props.url} alt={props.description || ""} className={cls} style={weightStyle(props.weight)} />;
});

// 覆盖视觉组件，其余（表单类/Tabs/Modal/Video 等）沿用 basicCatalog 实现。
const OVERRIDDEN = new Set(["Text", "Card", "Row", "Column", "List", "Button", "Divider", "Icon", "Image"]);
const kept = (basicCatalog.components as Map<string, any>);
const keptImpls = Array.from(kept.values()).filter((c: any) => !OVERRIDDEN.has(c.name));

export const shadcnCatalog: Catalog<ReactComponentImplementation> = new Catalog<ReactComponentImplementation>(
  basicCatalog.id,
  [Text, CardImpl, Row, Column, List, ButtonImpl, DividerImpl, IconImpl, ImageImpl, TimelineImpl, ...keptImpls] as ReactComponentImplementation[],
  Array.from(basicCatalog.functions.values()),
);
