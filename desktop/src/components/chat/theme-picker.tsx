"use client";

import { Palette, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { THEMES } from "./themes";
import { useTheme } from "./use-theme";

// 右上角调色盘：点击弹出主题列表，每项带三色预览圆点。
export function ThemePicker({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" size="icon" className={className} title="切换主题" />
        }
      >
        <Palette className="h-4 w-4" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={6} className="w-44">
        {/* base-ui 的 GroupLabel 必须包在 Group 内，否则读不到 MenuGroupContext 会抛错 */}
        <DropdownMenuGroup>
          <DropdownMenuLabel>主题</DropdownMenuLabel>
          {THEMES.map((t) => (
            <DropdownMenuItem
              key={t.id}
              onClick={() => setTheme(t.id)}
              className="flex items-center gap-2"
            >
              <span className="flex -space-x-1 shrink-0">
                {t.swatch.map((c, i) => (
                  <span
                    key={i}
                    className="h-3.5 w-3.5 rounded-full ring-1 ring-black/10"
                    style={{ backgroundColor: c }}
                  />
                ))}
              </span>
              <span className="flex-1">{t.label}</span>
              {theme === t.id && <Check className="h-3.5 w-3.5 text-primary" />}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
