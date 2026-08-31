// 模型选择下拉 —— 桌面端与 Web 端、对话输入框与设置页共享的唯一实现。
//
// 统一约定：选项与选中态都以「provider 前缀 + 模型描述/id」呈现，
// provider 用 mono + muted 小字（与设置页模型列表的展示风格一致），
// 避免不同 provider 下同名模型无法区分。
//
// 两种形态：
//   variant="inline" —— 对话输入框底部的轻量下拉（无边框、hover 出底色）
//   variant="form"   —— 设置页表单里的常规下拉（有边框、占满一行）
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import { cn } from "../lib/utils";

export interface ModelOption {
  id: string;
  description?: string;
  /** 归属 provider，缺省时不展示前缀（如测试桩、老数据） */
  provider?: string;
}

export interface ModelSelectProps {
  models: ModelOption[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  variant?: "inline" | "form";
  /** 未选中时的占位文案 */
  placeholder?: string;
  /** 可选的「留空」项，如设置页的轻量模型；value 通常为 "" */
  emptyOption?: { value: string; label: string };
  className?: string;
}

const TRIGGER_STYLES = {
  inline:
    "h-7 px-2.5 text-xs bg-transparent border-0 text-muted-foreground hover:text-foreground hover:bg-muted rounded-lg shadow-none focus:ring-0 focus:ring-offset-0 gap-1 w-auto max-w-[240px]",
  form: "w-full",
} as const;

/** provider 前缀 + 模型名，trigger 与 item 共用，保证选中前后视觉一致 */
function ModelLabel({ model, size }: { model: ModelOption; size: "inline" | "form" }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      {model.provider && (
        <span
          className={cn(
            "shrink-0 font-mono text-muted-foreground",
            size === "inline" ? "text-[10px]" : "text-xs"
          )}
        >
          {model.provider}
        </span>
      )}
      <span className="truncate">{model.description || model.id}</span>
    </span>
  );
}

export function ModelSelect({
  models,
  value,
  onChange,
  disabled = false,
  variant = "form",
  placeholder = "选择模型",
  emptyOption,
  className,
}: ModelSelectProps) {
  const itemTextClass = variant === "inline" ? "text-xs" : undefined;

  return (
    <Select
      value={value}
      onValueChange={(next: unknown) => {
        // base-ui 在某些关闭路径下会回传 null，忽略之，避免把选中态清空。
        // form 形态需要允许 emptyOption 的空串落库，故只挡 null/undefined。
        if (next === null || next === undefined) return;
        const v = String(next);
        if (v === "" && !emptyOption) return;
        onChange(v);
      }}
      disabled={disabled}
    >
      <SelectTrigger className={cn(TRIGGER_STYLES[variant], className)}>
        <SelectValue placeholder={placeholder}>
          {(current: string) => {
            if (emptyOption && current === emptyOption.value) {
              return <span className="truncate text-muted-foreground">{emptyOption.label}</span>;
            }
            const model = models.find((m) => m.id === current);
            if (!model) return placeholder;
            return <ModelLabel model={model} size={variant} />;
          }}
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {emptyOption && (
          <SelectItem value={emptyOption.value} className={itemTextClass}>
            {emptyOption.label}
          </SelectItem>
        )}
        {models.map((m) => (
          <SelectItem
            key={`${m.provider ?? ""}/${m.id}`}
            value={m.id}
            className={itemTextClass}
          >
            <ModelLabel model={m} size={variant} />
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
