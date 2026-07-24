// 单页 deck JSON → React 渲染（1000×562.5 逻辑坐标，按 scale 缩放）
// best-effort 预览：text/shape/line/table/image/chart/latex 全覆盖，复杂形状退化为矩形
import katex from "katex";
import type { CSSProperties } from "react";
import { PptChart } from "./chart";
import { CANVAS_H, CANVAS_W, DEFAULT_THEME } from "./types";
import type { PptElement, PptParagraph, PptRun, PptSlideData, PptTheme } from "./types";

export interface SlideRenderCtx {
  theme: PptTheme;
  /** 把 image 元素的 src（assets/xxx 相对路径或绝对路径）映射成可访问 URL */
  assetUrl: (src: string) => string;
}

function typo(ctx: SlideRenderCtx, textType?: string) {
  const t = { ...DEFAULT_THEME.typography, ...(ctx.theme.typography ?? {}) };
  return (textType && t[textType]) || {};
}

function runStyle(ctx: SlideRenderCtx, textType: string | undefined, run: PptRun): CSSProperties {
  const base = typo(ctx, textType) as { fontSize?: number; color?: string; bold?: boolean };
  const fontSize = run.fontSize ?? base.fontSize ?? 14;
  const style: CSSProperties = {
    fontSize,
    color: run.color ?? base.color ?? ctx.theme.fontColor ?? DEFAULT_THEME.fontColor,
    fontWeight: run.bold ?? base.bold ? 700 : 400,
    fontStyle: run.italic ? "italic" : undefined,
    fontFamily: run.fontName ?? ctx.theme.fontName ?? DEFAULT_THEME.fontName,
    textDecoration: [
      run.underline ? "underline" : "",
      run.strikethrough ? "line-through" : "",
    ].filter(Boolean).join(" ") || undefined,
    whiteSpace: "pre-wrap",
  };
  if (run.sub || run.sup) {
    style.fontSize = fontSize * 0.7;
    style.verticalAlign = run.sub ? "sub" : "super";
  }
  return style;
}

function Paragraphs({
  ctx,
  paragraphs,
  textType,
}: {
  ctx: SlideRenderCtx;
  paragraphs: PptParagraph[];
  textType?: string;
}) {
  let num = 0;
  return (
    <>
      {paragraphs.map((p, i) => {
        if (p.bullet === "number") num += 1;
        else num = 0;
        const prefix = p.bullet === "bullet" ? "• " : p.bullet === "number" ? `${num}. ` : "";
        return (
          <div
            key={i}
            style={{
              textAlign: p.align ?? "left",
              lineHeight: p.lineHeight ?? 1.5,
              marginTop: p.spaceBefore ?? 0,
              marginBottom: p.spaceAfter ?? 0,
            }}
          >
            {prefix && <span style={paragraphPrefixStyle(ctx, textType)}>{prefix}</span>}
            {p.runs.map((r, j) => (
              <span key={j} style={runStyle(ctx, textType, r)}>
                {r.text}
              </span>
            ))}
          </div>
        );
      })}
    </>
  );
}

function paragraphPrefixStyle(ctx: SlideRenderCtx, textType?: string): CSSProperties {
  const base = typo(ctx, textType) as { fontSize?: number; color?: string };
  return {
    fontSize: base.fontSize ?? 14,
    color: base.color ?? ctx.theme.fontColor ?? DEFAULT_THEME.fontColor,
  };
}

function fillStyle(el: PptElement): CSSProperties {
  if (el.gradient?.colors?.length) {
    const stops = el.gradient.colors.map((c) => `${c.color} ${c.pos}%`).join(", ");
    // pptx 渐变角顺时针（0=向右），CSS 顺时针从向上起算：css = pptx + 90
    const deg = (el.gradient.rotate ?? 0) + 90;
    return { background: `linear-gradient(${deg}deg, ${stops})` };
  }
  if (el.fill) return { background: el.fill };
  return {};
}

function outlineStyle(el: PptElement): CSSProperties {
  const o = el.outline;
  if (!o || !o.width) return {};
  const style = o.style === "dashed" ? "dashed" : o.style === "dotted" ? "dotted" : "solid";
  return { border: `${o.width}px ${style} ${o.color ?? "#D1D5DB"}` };
}

function boxStyle(el: PptElement): CSSProperties {
  return {
    position: "absolute",
    left: el.left ?? 0,
    top: el.top ?? 0,
    width: el.width ?? 0,
    height: el.height ?? 0,
    opacity: el.opacity ?? 1,
    transform: el.rotate ? `rotate(${el.rotate}deg)` : undefined,
  };
}

const SHAPE_RADIUS: Record<string, string> = {
  roundRect: "10%",
  round1Rect: "10% 10% 0 0",
  round2SameRect: "10% 10% 0 0",
  round2DiagRect: "10% 0 10% 0",
  snipRoundRect: "10%",
};

function ShapeElement({ el, ctx }: { el: PptElement; ctx: SlideRenderCtx }) {
  const shape = el.shape ?? "rect";
  const radius = shape === "ellipse" ? "50%" : SHAPE_RADIUS[shape] ?? (shape.includes("round") ? "10%" : 0);
  const shadow = el.shadow
    ? `${el.shadow.h ?? 0}px ${el.shadow.v ?? 0}px ${el.shadow.blur ?? 0}px ${el.shadow.color ?? "#00000014"}`
    : undefined;
  return (
    <div
      style={{
        ...boxStyle(el),
        ...fillStyle(el),
        ...outlineStyle(el),
        borderRadius: radius,
        boxShadow: shadow,
        display: "flex",
        flexDirection: "column",
        justifyContent:
          el.text?.align === "middle" ? "center" : el.text?.align === "bottom" ? "flex-end" : "flex-start",
        overflow: "hidden",
        padding: el.text ? 6 : 0,
        boxSizing: "border-box",
      }}
    >
      {el.text && <Paragraphs ctx={ctx} paragraphs={el.text.paragraphs} />}
    </div>
  );
}

function TextElement({ el, ctx }: { el: PptElement; ctx: SlideRenderCtx }) {
  const inset = el.inset ?? [0, 0, 0, 0];
  return (
    <div
      style={{
        ...boxStyle(el),
        ...fillStyle(el),
        ...outlineStyle(el),
        display: "flex",
        flexDirection: "column",
        justifyContent: el.vAlign === "middle" ? "center" : el.vAlign === "bottom" ? "flex-end" : "flex-start",
        padding: `${inset[0]}px ${inset[1]}px ${inset[2]}px ${inset[3]}px`,
        boxSizing: "border-box",
        overflow: "hidden",
        writingMode: el.vertical ? "vertical-rl" : undefined,
      }}
    >
      <Paragraphs ctx={ctx} paragraphs={el.paragraphs ?? []} textType={el.textType} />
    </div>
  );
}

function ImageElement({ el, ctx }: { el: PptElement; ctx: SlideRenderCtx }) {
  const src = el.src ?? "";
  const url = /^https?:\/\//.test(src) ? src : ctx.assetUrl(src);
  const isPlaceholder = src.startsWith("gen:") || src.startsWith("icon:") || !src;
  return (
    <div style={{ ...boxStyle(el), ...outlineStyle(el), borderRadius: el.radius ?? 0, overflow: "hidden" }}>
      {isPlaceholder ? (
        <div
          style={{
            width: "100%",
            height: "100%",
            background: "#F3F4F6",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#9CA3AF",
            fontSize: 11,
          }}
        >
          图片占位
        </div>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={url}
          alt=""
          style={{
            width: "100%",
            height: "100%",
            objectFit: el.fit === "contain" ? "contain" : el.fit === "fill" ? "fill" : "cover",
            transform: `${el.flipH ? "scaleX(-1)" : ""} ${el.flipV ? "scaleY(-1)" : ""}`.trim() || undefined,
          }}
        />
      )}
    </div>
  );
}

function LineElement({ el }: { el: PptElement; ctx: SlideRenderCtx }) {
  const [x1, y1] = el.start ?? [0, 0];
  const [x2, y2] = el.end ?? [0, 0];
  const left = Math.min(x1, x2);
  const top = Math.min(y1, y2);
  const w = Math.max(Math.abs(x2 - x1), 1);
  const h = Math.max(Math.abs(y2 - y1), 1);
  const color = el.color ?? "#D1D5DB";
  const width = el.width ?? 1;
  const dash = el.style === "dashed" ? "6 4" : el.style === "dotted" ? "2 3" : undefined;
  const markerId = `arrow-${el.id}`;
  const [pStart, pEnd] = el.points ?? ["", ""];
  return (
    <svg style={{ position: "absolute", left, top, overflow: "visible" }} width={w} height={h}>
      <defs>
        <marker id={markerId} markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
          <path d="M0,0 L7,3 L0,6 Z" fill={color} />
        </marker>
      </defs>
      <line
        x1={x1 - left}
        y1={y1 - top}
        x2={x2 - left}
        y2={y2 - top}
        stroke={color}
        strokeWidth={width}
        strokeDasharray={dash}
        markerEnd={pEnd === "arrow" ? `url(#${markerId})` : undefined}
        markerStart={pStart === "arrow" ? `url(#${markerId})` : undefined}
      />
      {pStart === "dot" && <circle cx={x1 - left} cy={y1 - top} r={width + 1.5} fill={color} />}
      {pEnd === "dot" && <circle cx={x2 - left} cy={y2 - top} r={width + 1.5} fill={color} />}
    </svg>
  );
}

interface TableCell {
  text?: string;
  colspan?: number;
  rowspan?: number;
  merged?: boolean;
  style?: {
    bold?: boolean;
    em?: boolean;
    underline?: boolean;
    strikethrough?: boolean;
    color?: string;
    backcolor?: string;
    fontSize?: number;
    fontName?: string;
    align?: "left" | "center" | "right";
    vAlign?: "top" | "middle" | "bottom";
  };
}

function TableElement({ el, ctx }: { el: PptElement; ctx: SlideRenderCtx }) {
  const rows = (el.data as unknown as TableCell[][]) ?? [];
  const colWidths = el.colWidths ?? rows[0]?.map(() => 1 / (rows[0].length || 1)) ?? [];
  const headerColor = el.theme?.color ?? ctx.theme.themeColors?.[0] ?? "#1E40AF";
  const borderColor = el.outline?.color ?? ctx.theme.outline?.color ?? "#E5E7EB";
  const fontColor = ctx.theme.fontColor ?? DEFAULT_THEME.fontColor;
  return (
    <div style={{ ...boxStyle(el), overflow: "hidden" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", tableLayout: "fixed" }}>
        <colgroup>
          {colWidths.map((cw, i) => (
            <col key={i} style={{ width: `${cw * 100}%` }} />
          ))}
        </colgroup>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => {
                if (cell.merged) return null;
                const isHeader = ri === 0 && el.theme?.rowHeader;
                const st = cell.style ?? {};
                return (
                  <td
                    key={ci}
                    colSpan={cell.colspan ?? 1}
                    rowSpan={cell.rowspan ?? 1}
                    style={{
                      border: `1px solid ${borderColor}`,
                      padding: "4px 8px",
                      minHeight: el.cellMinHeight ?? 32,
                      background: st.backcolor ?? (isHeader ? headerColor : "transparent"),
                      color: st.color ?? (isHeader ? "#FFFFFF" : fontColor),
                      fontWeight: st.bold ?? isHeader ? 700 : 400,
                      fontStyle: st.em ? "italic" : undefined,
                      fontSize: st.fontSize ?? 12,
                      fontFamily: st.fontName ?? ctx.theme.fontName ?? DEFAULT_THEME.fontName,
                      textAlign: st.align ?? (isHeader ? "center" : "left"),
                      verticalAlign: st.vAlign ?? "middle",
                      textDecoration: st.underline ? "underline" : st.strikethrough ? "line-through" : undefined,
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                    }}
                  >
                    {cell.text}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LatexElement({ el, ctx }: { el: PptElement; ctx: SlideRenderCtx }) {
  let html = "";
  try {
    html = katex.renderToString(el.latex ?? "", { throwOnError: true, displayMode: true, output: "html" });
  } catch {
    html = "";
  }
  const color = el.color ?? ctx.theme.fontColor ?? DEFAULT_THEME.fontColor;
  const fontSize = el.fontSize ?? 20;
  return (
    <div
      style={{
        ...boxStyle(el),
        display: "flex",
        alignItems: "center",
        justifyContent: el.align === "left" ? "flex-start" : el.align === "right" ? "flex-end" : "center",
        overflow: "hidden",
        color,
        fontSize,
      }}
    >
      {html ? (
        <span dangerouslySetInnerHTML={{ __html: html }} style={{ fontSize, color }} />
      ) : (
        <span style={{ fontFamily: "Cambria Math, STIX Two Math, serif", fontStyle: "italic", fontSize, color }}>
          {el.latex}
        </span>
      )}
    </div>
  );
}

function Element({ el, ctx }: { el: PptElement; ctx: SlideRenderCtx }) {
  switch (el.type) {
    case "text":
      return <TextElement el={el} ctx={ctx} />;
    case "shape":
      return <ShapeElement el={el} ctx={ctx} />;
    case "image":
      return <ImageElement el={el} ctx={ctx} />;
    case "line":
      return <LineElement el={el} ctx={ctx} />;
    case "table":
      return <TableElement el={el} ctx={ctx} />;
    case "chart":
      return (
        <div style={boxStyle(el)}>
          <PptChart el={el} colors={ctx.theme.themeColors ?? DEFAULT_THEME.themeColors!} />
        </div>
      );
    case "latex":
      return <LatexElement el={el} ctx={ctx} />;
    default:
      return null; // 未知元素跳过
  }
}

function slideBackground(slide: PptSlideData, ctx: SlideRenderCtx): CSSProperties {
  const bg = slide.background;
  if (!bg) return { background: ctx.theme.backgroundColor ?? DEFAULT_THEME.backgroundColor };
  if (bg.type === "solid") return { background: bg.color };
  if (bg.type === "gradient") {
    const stops = bg.gradient.colors.map((c) => `${c.color} ${c.pos}%`).join(", ");
    return { background: `linear-gradient(${(bg.gradient.rotate ?? 0) + 90}deg, ${stops})` };
  }
  if (bg.type === "image") {
    return {
      backgroundImage: `url(${ctx.assetUrl(bg.image.src)})`,
      backgroundSize: bg.image.size === "contain" ? "contain" : "cover",
      backgroundPosition: "center",
      backgroundColor: ctx.theme.backgroundColor ?? DEFAULT_THEME.backgroundColor,
    };
  }
  return {};
}

/** 渲染一页：外层尺寸 = 画布 × scale，内部 transform 缩放，元素坐标直接用逻辑 px */
export function PptSlide({
  slide,
  theme,
  scale = 1,
  assetUrl,
}: {
  slide: PptSlideData;
  theme?: PptTheme;
  scale?: number;
  assetUrl: (src: string) => string;
}) {
  const ctx: SlideRenderCtx = { theme: theme ?? {}, assetUrl };
  return (
    <div
      style={{
        width: CANVAS_W * scale,
        height: CANVAS_H * scale,
        overflow: "hidden",
        position: "relative",
        flexShrink: 0,
      }}
    >
      <div
        style={{
          width: CANVAS_W,
          height: CANVAS_H,
          transform: `scale(${scale})`,
          transformOrigin: "top left",
          position: "relative",
          ...slideBackground(slide, ctx),
        }}
      >
        {(slide.elements ?? []).map((el) => (
          <Element key={el.id} el={el} ctx={ctx} />
        ))}
      </div>
    </div>
  );
}
