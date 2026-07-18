import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ShieldCheck } from "lucide-react";

export interface ConsentRequest {
  request_id: string;
  tool: string;
  description: string;
  detail?: string;
}

interface ConsentDialogProps {
  request: ConsentRequest | null;
  onRespond: (requestId: string, allowed: boolean) => void;
}

const TOOL_LABELS: Record<string, string> = {
  get_secret: "读取密钥",
  set_secret: "保存密钥",
  file_read: "读取文件",
  file_write: "写入文件",
  shell: "执行命令",
};

export function ConsentDialog({ request, onRespond }: ConsentDialogProps) {
  const open = request !== null;
  return (
    <Dialog open={open} onOpenChange={(o: boolean) => !o && request && onRespond(request.request_id, false)}>
      <DialogContent showCloseButton={false} className="max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-amber-500/15">
              <ShieldCheck className="h-5 w-5 text-amber-600 dark:text-amber-400" />
            </div>
            <DialogTitle>需要授权</DialogTitle>
          </div>
          <DialogDescription className="pt-1">
            Ethan 请求执行一个敏感操作，需要你的确认。
          </DialogDescription>
        </DialogHeader>

        {request && (
          <div className="space-y-2 rounded-md border bg-muted/40 p-3 text-sm">
            <div className="flex items-baseline gap-2">
              <span className="text-muted-foreground">工具</span>
              <span className="font-medium">
                {TOOL_LABELS[request.tool] || request.tool}
                <code className="ml-1.5 rounded bg-muted px-1 py-0.5 text-xs text-muted-foreground">
                  {request.tool}
                </code>
              </span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-muted-foreground">操作</span>
              <span className="font-medium">{request.description}</span>
            </div>
            {request.detail && (
              <div className="text-xs text-muted-foreground break-all">
                {request.detail}
              </div>
            )}
          </div>
        )}

        <DialogFooter className="gap-2">
          <Button
            variant="outline"
            onClick={() => request && onRespond(request.request_id, false)}
          >
            拒绝
          </Button>
          <Button
            onClick={() => request && onRespond(request.request_id, true)}
          >
            允许
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
