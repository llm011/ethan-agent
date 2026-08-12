import { useEffect, useState } from "react";
import { Hourglass } from "lucide-react";
import { Card } from "../ui/card";
import { Button } from "../ui/button";
import { Input } from "../ui/input";

export interface WaitForUserRequest {
  request_id: string;
  prompt: string;
  input_type: "confirm" | "text";
  placeholder?: string;
  confirm_label?: string;
  cancel_label?: string;
  timeout: number;
}

interface WaitForUserCardProps {
  request: WaitForUserRequest;
  onRespond: (requestId: string, value: string) => void;
}

export function WaitForUserCard({ request, onRespond }: WaitForUserCardProps) {
  const [remaining, setRemaining] = useState(request.timeout);
  const [responded, setResponded] = useState(false);
  const [textValue, setTextValue] = useState("");

  const isText = request.input_type === "text";
  const confirmLabel = request.confirm_label || "已完成";
  const cancelLabel = request.cancel_label || "取消";

  useEffect(() => {
    if (responded) return;
    if (remaining <= 0) {
      setResponded(true);
      onRespond(request.request_id, "timeout");
      return;
    }
    const timer = setTimeout(() => setRemaining((r) => r - 1), 1000);
    return () => clearTimeout(timer);
  }, [remaining, responded, request.request_id, onRespond]);

  const handleConfirm = () => {
    if (responded) return;
    setResponded(true);
    onRespond(request.request_id, isText ? (textValue.trim() || "done") : "done");
  };

  const handleCancel = () => {
    if (responded) return;
    setResponded(true);
    onRespond(request.request_id, "cancel");
  };

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
  };

  return (
    <Card className="p-4 gap-3 border border-amber-500/40 bg-amber-500/5 shadow-md ring-0">
      <div className="flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-amber-500/15">
          <Hourglass className="h-4 w-4 text-amber-600 dark:text-amber-400" />
        </div>
        <div className="text-sm font-medium flex-1 whitespace-pre-wrap break-all">{request.prompt}</div>
        {!responded && (
          <span className="text-xs text-muted-foreground tabular-nums bg-muted px-1.5 py-0.5 rounded whitespace-nowrap">
            {formatTime(remaining)}
          </span>
        )}
      </div>

      {isText && !responded && (
        <Input
          value={textValue}
          onChange={(e) => setTextValue(e.target.value)}
          placeholder={request.placeholder || "请输入..."}
          onKeyDown={(e) => e.key === "Enter" && handleConfirm()}
          autoFocus
        />
      )}

      {!responded ? (
        <div className="flex gap-2 justify-end">
          <Button variant="outline" size="sm" onClick={handleCancel}>
            {cancelLabel}
          </Button>
          <Button size="sm" onClick={handleConfirm} disabled={isText && !textValue.trim()}>
            {confirmLabel}
          </Button>
        </div>
      ) : (
        <div className="text-xs text-muted-foreground">已确认</div>
      )}
    </Card>
  );
}
