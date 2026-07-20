
// 授权 UI：固定模板的内联卡片（非 agent 实时生成），shadcn 风格对齐 A2UI 卡片。
// 「卡片为主，模态保底」：ConsentCard 渲染异常时由 ErrorBoundary 回退到 ConsentDialog 模态框。

import { Component, type ReactNode } from "react";
import { ShieldCheck } from "lucide-react";
import { Card } from "../ui/card";
import { Button } from "../ui/button";
import { ConsentDialog, type ConsentRequest } from "../components/consent-dialog";

const TOOL_LABELS: Record<string, string> = {
  get_secret: "读取密钥",
  set_secret: "保存密钥",
  file_read: "读取文件",
  file_write: "写入文件",
  shell: "执行命令",
};

interface ConsentCardProps {
  request: ConsentRequest;
  onRespond: (requestId: string, allowed: boolean) => void;
}

// 固定模板卡片：工具 + 操作描述 + 详情 + 允许/拒绝。
function ConsentCard({ request, onRespond }: ConsentCardProps) {
  return (
    <Card className="p-4 gap-3 border border-amber-500/40 bg-amber-500/5 shadow-md ring-0">
      <div className="flex items-center gap-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-amber-500/15">
          <ShieldCheck className="h-4 w-4 text-amber-600 dark:text-amber-400" />
        </div>
        <div className="text-sm font-semibold">需要授权</div>
      </div>

      <div className="space-y-1.5 text-sm">
        <div className="flex items-baseline gap-2">
          <span className="text-muted-foreground shrink-0">工具</span>
          <span className="font-medium">
            {TOOL_LABELS[request.tool] || request.tool}
            <code className="ml-1.5 rounded bg-muted px-1 py-0.5 text-xs text-muted-foreground">
              {request.tool}
            </code>
          </span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-muted-foreground shrink-0">操作</span>
          <span className="font-medium">{request.description}</span>
        </div>
        {request.detail && (
          <div className="text-xs text-muted-foreground break-all pl-[2.5rem]">
            {request.detail}
          </div>
        )}
      </div>

      <div className="text-xs text-muted-foreground">
        同一会话内同类操作授权一次后不再询问。
      </div>

      <div className="flex justify-end gap-2">
        <Button variant="outline" size="sm" onClick={() => onRespond(request.request_id, false)}>
          拒绝
        </Button>
        <Button size="sm" onClick={() => onRespond(request.request_id, true)}>
          允许
        </Button>
      </div>
    </Card>
  );
}

interface GateProps {
  request: ConsentRequest | null;
  onRespond: (requestId: string, allowed: boolean) => void;
}

interface GateState {
  failed: boolean;
}

// ConsentGate：卡片为主，模态保底。ConsentCard 抛错时切到 ConsentDialog。
export class ConsentGate extends Component<GateProps, GateState> {
  state: GateState = { failed: false };

  static getDerivedStateFromError(): GateState {
    return { failed: true };
  }

  render() {
    const { request, onRespond } = this.props;
    if (!request) return null;
    if (this.state.failed) {
      return <ConsentDialog request={request} onRespond={onRespond} />;
    }
    return (
      <div className="max-w-3xl mx-auto px-4 pb-2">
        <ConsentCard request={request} onRespond={onRespond} />
      </div>
    );
  }
}
