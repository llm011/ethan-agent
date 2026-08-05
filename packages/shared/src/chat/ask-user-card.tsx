import { useEffect, useState } from "react";
import { MessageCircleQuestion } from "lucide-react";
import { Card } from "../ui/card";
import { Button } from "../ui/button";

export interface AskUserRequest {
  request_id: string;
  question: string;
  options: Array<{ label: string; value: string }>;
  default: string;
  timeout: number;
}

interface AskUserCardProps {
  request: AskUserRequest;
  onRespond: (requestId: string, value: string) => void;
}

export function AskUserCard({ request, onRespond }: AskUserCardProps) {
  const [remaining, setRemaining] = useState(request.timeout);
  const [responded, setResponded] = useState(false);

  useEffect(() => {
    if (responded) return;
    if (remaining <= 0) {
      setResponded(true);
      onRespond(request.request_id, request.default);
      return;
    }
    const timer = setTimeout(() => setRemaining((r) => r - 1), 1000);
    return () => clearTimeout(timer);
  }, [remaining, responded, request.request_id, request.default, onRespond]);

  const handleSelect = (value: string) => {
    if (responded) return;
    setResponded(true);
    onRespond(request.request_id, value);
  };

  return (
    <Card className="p-4 gap-3 border border-blue-500/40 bg-blue-500/5 shadow-md ring-0">
      <div className="flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-500/15">
          <MessageCircleQuestion className="h-4 w-4 text-blue-600 dark:text-blue-400" />
        </div>
        <div className="text-sm font-semibold flex-1">{request.question}</div>
        {!responded && (
          <span className="text-xs text-muted-foreground tabular-nums bg-muted px-1.5 py-0.5 rounded">{remaining}s</span>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        {request.options.map((opt) => (
          <Button
            key={opt.value}
            variant={opt.value === request.default ? "default" : "outline"}
            size="sm"
            disabled={responded}
            onClick={() => handleSelect(opt.value)}
          >
            {opt.label}
            {opt.value === request.default && !responded && (
              <span className="ml-1 text-xs opacity-60">(默认)</span>
            )}
          </Button>
        ))}
      </div>

      {responded && (
        <div className="text-xs text-muted-foreground">已确认</div>
      )}
    </Card>
  );
}
