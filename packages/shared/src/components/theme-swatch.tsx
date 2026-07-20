// 主题预览三色圆点 —— 桌面端与 Web 端共享（避免多处重复实现）。
// 纯展示组件，不耦合 ThemeDef 结构，调用方传入颜色数组即可。
export function ThemeSwatch({ colors }: { colors: readonly string[] }) {
  return (
    <span className="flex -space-x-1 shrink-0">
      {colors.map((c, i) => (
        <span
          key={i}
          className="h-3.5 w-3.5 rounded-full ring-1 ring-black/10"
          style={{ backgroundColor: c }}
        />
      ))}
    </span>
  );
}
