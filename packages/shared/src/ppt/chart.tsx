// 图表元素的 SVG 渲染（best-effort 预览：column/bar/line/area/pie/ring）
import type { PptElement } from "./types";

const FONT = "inherit";

function Axis({ w, h, color }: { w: number; h: number; color: string }) {
  return (
    <>
      <line x1={0} y1={h} x2={w} y2={h} stroke={color} strokeWidth={1} />
      <line x1={0} y1={0} x2={0} y2={h} stroke={color} strokeWidth={1} />
    </>
  );
}

export function PptChart({ el, colors }: { el: PptElement; colors: string[] }) {
  const w = el.width ?? 400;
  const h = el.height ?? 300;
  const data = el.data;
  if (!data || !Array.isArray(data.series) || data.series.length === 0) {
    return <Fallback w={w} h={h} label="图表数据缺失" />;
  }
  const labels = data.labels ?? [];
  const series = data.series;
  const type = el.chartType ?? "column";
  const palette = (el.themeColors?.length ? el.themeColors : colors) ?? ["#1E40AF"];
  const padL = 8, padB = 18, padT = 8;
  const iw = w - padL - 4;
  const ih = h - padT - padB;
  const axisColor = "#D1D5DB";
  const labelColor = "#6B7280";
  const labelSize = Math.max(8, Math.min(11, w / 50));

  const flat = series.flat();
  const maxV = Math.max(...flat.map((v) => Math.abs(v)), 1);

  if (type === "pie" || type === "ring") {
    const vals = series[0] ?? [];
    const total = vals.reduce((a, b) => a + b, 0) || 1;
    const cx = w / 2 - (data.legends?.length ? 40 : 0);
    const cy = h / 2;
    const r = Math.min(w, h) / 2 - 12;
    const innerR = type === "ring" ? r * 0.55 : 0;
    let angle = -Math.PI / 2;
    const slices = vals.map((v, i) => {
      const a0 = angle;
      const a1 = angle + (v / total) * Math.PI * 2;
      angle = a1;
      const large = a1 - a0 > Math.PI ? 1 : 0;
      const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0);
      const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1);
      const xi1 = cx + innerR * Math.cos(a1), yi1 = cy + innerR * Math.sin(a1);
      const xi0 = cx + innerR * Math.cos(a0), yi0 = cy + innerR * Math.sin(a0);
      const d = innerR
        ? `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1} L ${xi1} ${yi1} A ${innerR} ${innerR} 0 ${large} 0 ${xi0} ${yi0} Z`
        : `M ${cx} ${cy} L ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1} Z`;
      return <path key={i} d={d} fill={palette[i % palette.length]} stroke="#fff" strokeWidth={1} />;
    });
    return (
      <svg width={w} height={h} style={{ display: "block" }}>
        {slices}
        {labels.map((lb, i) => (
          <text key={i} x={w - 76} y={20 + i * (labelSize + 6)} fontSize={labelSize} fill={labelColor} fontFamily={FONT}>
            <tspan fill={palette[i % palette.length]}>● </tspan>
            {lb}
          </text>
        ))}
      </svg>
    );
  }

  if (type === "line" || type === "area") {
    const n = labels.length || 1;
    const stepX = iw / Math.max(n - 1, 1);
    return (
      <svg width={w} height={h} style={{ display: "block" }}>
        <g transform={`translate(${padL},${padT})`}>
          <Axis w={iw} h={ih} color={axisColor} />
          {series.map((s, si) => {
            const pts = s.map((v, i) => [i * stepX, ih - (v / maxV) * ih] as const);
            const poly = pts.map(([x, y]) => `${x},${y}`).join(" ");
            return (
              <g key={si}>
                {type === "area" && (
                  <polygon points={`0,${ih} ${poly} ${(n - 1) * stepX},${ih}`} fill={palette[si % palette.length]} opacity={0.25} />
                )}
                <polyline points={poly} fill="none" stroke={palette[si % palette.length]} strokeWidth={2} />
                {pts.map(([x, y], i) => (
                  <circle key={i} cx={x} cy={y} r={2.5} fill={palette[si % palette.length]} />
                ))}
              </g>
            );
          })}
          {labels.map((lb, i) => (
            <text key={i} x={i * stepX} y={ih + labelSize + 4} fontSize={labelSize} fill={labelColor} textAnchor="middle" fontFamily={FONT}>
              {lb}
            </text>
          ))}
        </g>
      </svg>
    );
  }

  if (type === "column" || type === "bar") {
    const vertical = type === "column";
    const n = labels.length || 1;
    const group = (vertical ? iw / n : ih / n) * 0.7;
    const bw = group / series.length;
    return (
      <svg width={w} height={h} style={{ display: "block" }}>
        <g transform={`translate(${padL},${padT})`}>
          <Axis w={iw} h={ih} color={axisColor} />
          {series.map((s, si) =>
            s.map((v, i) => {
              const frac = v / maxV;
              const x = vertical ? i * (iw / n) + ((iw / n - group) / 2) + si * bw : 0;
              const y = vertical ? ih - frac * ih : i * (ih / n) + ((ih / n - group) / 2) + si * bw;
              return (
                <rect
                  key={`${si}-${i}`}
                  x={x}
                  y={y}
                  width={vertical ? bw * 0.9 : frac * iw}
                  height={vertical ? frac * ih : bw * 0.9}
                  fill={palette[si % palette.length]}
                  rx={1.5}
                />
              );
            })
          )}
          {labels.map((lb, i) =>
            vertical ? (
              <text key={i} x={i * (iw / n) + iw / n / 2} y={ih + labelSize + 4} fontSize={labelSize} fill={labelColor} textAnchor="middle" fontFamily={FONT}>
                {lb}
              </text>
            ) : (
              <text key={i} x={2} y={i * (ih / n) + ih / n / 2} fontSize={labelSize} fill={labelColor} fontFamily={FONT}>
                {lb}
              </text>
            )
          )}
        </g>
      </svg>
    );
  }

  return <Fallback w={w} h={h} label={`${type} 图暂不支持预览`} />;
}

function Fallback({ w, h, label }: { w: number; h: number; label: string }) {
  return (
    <div
      style={{
        width: w,
        height: h,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        border: "1px dashed #D1D5DB",
        borderRadius: 8,
        color: "#9CA3AF",
        fontSize: 12,
      }}
    >
      {label}
    </div>
  );
}
