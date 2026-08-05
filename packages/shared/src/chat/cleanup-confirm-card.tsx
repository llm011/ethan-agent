
// 浏览器清理确认卡片：对话结束后弹出，让用户选择是否关闭 agent 打开的 tab group。
// 样式与 ConsentCard 对齐，蓝色主题区分于授权的琥珀色。

import { useEffect, useState } from "react";
import { FolderX, FolderCheck } from "lucide-react";
import { Card } from "../ui/card";
import { Button } from "../ui/button";

export interface CleanupSessionInfo {
  sessionId: string;
  title: string;
  tabCount: number;
}

export interface CleanupConfirmRequest {
  request_id: string;
  sessions: CleanupSessionInfo[];
  timeout?: number;
}

interface CleanupCardProps extends CleanupConfirmRequest {
  onRespond: (requestId: string, action: "close" | "keep") => void;
}

function CleanupConfirmCard({ request_id, sessions, timeout = 120, onRespond }: CleanupCardProps) {
  const [responded, setResponded] = useState(false);
  const [remaining, setRemaining] = useState(timeout);

  const groupLabel = sessions.length === 1
    ? (sessions[0].title || "未命名标签组")
    : `${sessions.length} 个标签组`;

  useEffect(() => {
    if (responded) return;
    if (remaining <= 0) {
      setResponded(true);
      onRespond(request_id, "keep");
      return;
    }
    const timer = setTimeout(() => setRemaining((r) => r - 1), 1000);
    return () => clearTimeout(timer);
  }, [remaining, responded, request_id, onRespond]);

  const handle = (action: "close" | "keep") => {
    if (responded) return;
    setResponded(true);
    onRespond(request_id, action);
  };

  return (
    <Card className="p-4 gap-3 border border-blue-500/40 bg-blue-500/5 shadow-md ring-0">
      <div className="flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-500/15">
          <FolderCheck className="h-4 w-4 text-blue-600 dark:text-blue-400" />
        </div>
        <div className="text-sm font-semibold flex-1">浏览器标签组清理</div>
        {!responded && (
          <span className="text-xs text-muted-foreground tabular-nums bg-muted px-1.5 py-0.5 rounded">{remaining}s 后自动保留</span>
        )}
      </div>

      <div className="text-sm text-muted-foreground">
        Ethan 刚才打开的标签组「{groupLabel}」要怎么处理？
      </div>

      {sessions.length > 1 && (
        <div className="space-y-1 text-xs text-muted-foreground pl-[2.5rem]">
          {sessions.map((s) => (
            <div key={s.sessionId}>
              · {s.title || "未命名"}{s.tabCount ? `（${s.tabCount} 个标签）` : ""}
            </div>
          ))}
        </div>
      )}

      {responded ? (
        <div className="text-xs text-muted-foreground border-t border-border/50 pt-2">
          已处理
        </div>
      ) : (
        <div className="flex justify-end gap-2">
          <Button variant="destructive" size="sm" onClick={() => handle("close")}>
            <FolderX className="h-3.5 w-3.5 mr-1" />
            关闭标签组
          </Button>
          <Button variant="default" size="sm" onClick={() => handle("keep")}>
            <FolderCheck className="h-3.5 w-3.5 mr-1" />
            保留（默认）
          </Button>
        </div>
      )}
    </Card>
  );
}

interface CleanupConfirmGateProps {
  request: CleanupConfirmRequest | null;
  onRespond: (requestId: string, action: "close" | "keep") => void;
}

export function CleanupConfirmGate({ request, onRespond }: CleanupConfirmGateProps) {
  if (!request) return null;
  return (
    <div className="max-w-3xl mx-auto px-4 pb-2">
      <CleanupConfirmCard {...request} onRespond={onRespond} />
    </div>
  );
}
