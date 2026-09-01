import * as React from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./select";
import { cn } from "../lib/utils";

/**
 * 一个可在「设置（默认模型/轻量模型）」与「聊天输入框」间复用的模型选择下拉。
 *
 * 解决了设置里原本那种原始 Select 的问题：
 *  - 列表项展示 alias（或 description）并附带 provider 徽标，同聊天输入框一致；
 *  - 触发按钮渲染当前选中模型的 alias + provider，而不是干巴巴的 id。
 *
 * valueMode 决定选中值如何编码：
 *  - "fullId"：`provider/id` 复合格式（聊天输入框用，可区分不同 provider 的同名模型）；
 *  - "id"：纯 `id`（设置里落库用，保持与既有配置格式兼容）。
 */
export interface ModelOption {
  id: string;
  provider?: string;
  description?: string;
  alias?: string[];
}

export interface ModelSelectProps {
  models: ModelOption[];
  value: string;
  onValueChange: (value: string) => void;
  /** 选中值编码方式，默认 "fullId" */
  valueMode?: "fullId" | "id";
  /** 是否提供「空选项」（如轻量/心跳/定时模型留空跟随默认），默认 false */
  allowEmpty?: boolean;
  /** allowEmpty 时空选项的文案 */
  emptyLabel?: string;
  /** 未选中时触发按钮展示的占位文案 */
  placeholder?: string;
  /**
   * value 匹配不到任何模型时，触发按钮展示的兜底文案（替代直接显示原始 value）。
   * 用于哨兵值（如聊天输入框的 NEED_CHOICE「重名待重选」）——避免把实现细节字符串
   * 直接抖给用户。缺省时回退为显示原始 value。
   */
  unmatchedLabel?: (value: string) => React.ReactNode;
  disabled?: boolean;
  /** 触发按钮尺寸，聊天输入框紧凑场景用 "sm" */
  size?: "sm" | "default";
  triggerClassName?: string;
  contentClassName?: string;
  /** 触发按钮内容额外渲染的节点（追加在选中值右侧，如模式图标） */
  triggerSuffix?: React.ReactNode;
  /** 渲染在列表顶部的额外项（allowEmpty 项之后），用于注入特殊提示项（如「重名待重选」） */
  extraItems?: React.ReactNode;
}

function fullIdOf(m: ModelOption): string {
  return m.provider ? `${m.provider}/${m.id}` : m.id;
}

/**
 * id 模式撞车回退时，把内部用的 `provider/id` 复合 value 拆回裸 id 落库。
 * 只剥掉第一个斜杠前的 provider 前缀，其余（含 id 中可能出现的斜杠）原样保留。
 */
export function bareIdFromComposite(v: string): string {
  const i = v.indexOf("/");
  return i === -1 ? v : v.slice(i + 1);
}

function displayNameOf(m: ModelOption): string {
  return m.alias?.[0] || m.description || m.id;
}

function ModelItemLabel({ m, valueMode }: { m: ModelOption; valueMode: "fullId" | "id" }) {
  // id 模式用纯 id 作 value，同名模型（尤其不同 provider 提供同 alias）会撞车；
  // 右侧标注 provider 或原始 id，帮用户在列表里分辨，避免误选。
  const disambig =
    valueMode === "id"
      ? m.provider
        ? m.provider
        : displayNameOf(m) !== m.id
          ? m.id
          : null
      : m.provider || null;
  return (
    <span className="flex items-center gap-2 w-full">
      <span className="truncate">{displayNameOf(m)}</span>
      {disambig && (
        <span className="text-muted-foreground/60 text-[10px] ml-auto shrink-0">{disambig}</span>
      )}
    </span>
  );
}

export function ModelSelect({
  models,
  value,
  onValueChange,
  valueMode = "fullId",
  allowEmpty = false,
  emptyLabel,
  placeholder = "选择模型",
  unmatchedLabel,
  disabled,
  size = "default",
  triggerClassName,
  contentClassName,
  triggerSuffix,
  extraItems,
}: ModelSelectProps) {
  // 是否存在跨 provider 的同名（同 id）模型。id 模式下这些模型的裸 id 会撞车，
  // 导致 radix Select 把它们当成同一 item（选中一个则同名的全高亮/匹配混乱）。
  const hasIdCollision = valueMode === "id" && new Set(models.map((m) => m.id)).size !== models.length;

  // id 模式默认用裸 id 作 value（落库兼容存量配置）；但若存在同名撞车，
  // 则退回用 provider/id 保证 item value 全局唯一，onValueChange 再拆回裸 id 落库。
  const itemValue = (m: ModelOption) => {
    if (valueMode === "fullId") return fullIdOf(m);
    return hasIdCollision && m.provider ? `${m.provider}/${m.id}` : m.id;
  };

  // 撞车时传入的 value 也要升级成 provider/id，否则 radix 拿裸 id 匹配不到 item、选中态丢失。
  // 裸 id 唯一命中 → 升级为对应 provider/id；歧义（命中多个同名）→ 保持原样走 unmatched 兜底。
  const effectiveValue = (() => {
    if (valueMode !== "id" || !hasIdCollision) return value;
    const hits = models.filter((m) => m.id === value);
    if (hits.length === 1 && hits[0].provider) return `${hits[0].provider}/${hits[0].id}`;
    return value;
  })();

  const handleValueChange = (v: string) => {
    if (v == null) return;
    // id 模式且因同名撞车而用了 provider/id 作 value 时，拆回裸 id 落库。
    if (valueMode === "id" && hasIdCollision) {
      const isComposite = v.includes("/") && models.some((m) => fullIdOf(m) === v);
      // 去掉 provider 前缀、保留斜杠后的模型 id（bareIdFromComposite）。
      // 此前写成 v.split("/", 1)[0]，取到的是斜杠前的 provider 名，
      // 导致「选了模型却把 provider 名落库成默认模型」的 bug。
      onValueChange(isComposite ? bareIdFromComposite(v) : v);
      return;
    }
    onValueChange(v);
  };

  return (
    <Select value={effectiveValue} onValueChange={(v) => handleValueChange(v as string)} disabled={disabled}>
      <SelectTrigger size={size} className={cn("w-full", triggerClassName)}>
        <SelectValue placeholder={placeholder}>
          {(val: unknown) => {
            const v = typeof val === "string" ? val : "";
            // id 模式下「主动留空跟随默认」是独立语义：即使传了 allowEmpty，触发按钮也要显示 emptyLabel
            // 而不是混成「未选择」的 placeholder。
            if (v === "" && allowEmpty) {
              return <span className="text-muted-foreground">{emptyLabel ?? "留空（自动推断）"}</span>;
            }
            if (v === "") {
              return <span className="text-muted-foreground">{placeholder}</span>;
            }
            const m = models.find((x) => fullIdOf(x) === v || x.id === v);
            // 匹配不到：fullId 模式下可能是 legacy 裸 id / NEED_CHOICE 哨兵，兜底显示裸值本身，
            // 避免触发按钮退化成 placeholder 让用户看不出当前状态。
            if (!m) {
              return (
                <span className="text-muted-foreground">
                  {unmatchedLabel ? unmatchedLabel(v) : v}
                </span>
              );
            }
            return (
              <span className="flex items-center gap-1.5 min-w-0">
                <span className="truncate">{displayNameOf(m)}</span>
                {m.provider && (
                  <span className="text-muted-foreground/60 text-[10px] shrink-0">{m.provider}</span>
                )}
              </span>
            );
          }}
        </SelectValue>
        {triggerSuffix}
      </SelectTrigger>
      <SelectContent className={cn("min-w-[240px] max-h-[50vh] overflow-y-auto", contentClassName)}>
        {allowEmpty && (
          <SelectItem value="">{emptyLabel ?? "留空（自动推断）"}</SelectItem>
        )}
        {extraItems}
        {models.map((m) => (
          <SelectItem key={itemValue(m)} value={itemValue(m)} className="text-sm">
            <ModelItemLabel m={m} valueMode={valueMode} />
          </SelectItem>
        ))}
        {models.length === 0 && (
          <div className="px-2 py-2 text-sm text-muted-foreground">暂无模型</div>
        )}
      </SelectContent>
    </Select>
  );
}
