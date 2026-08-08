import { useState, useEffect, useCallback, useRef } from "react";
import { CheckCircle2 } from "lucide-react";
import { Button } from "../ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";

// 只匹配「明确要求用户执行操作 + 完成后通知」的祈使句。
// 收紧原则：
//   1. 必须同时包含「动作动词」+「完成/后」+「告诉/通知/继续」
//   2. 用 tempered greedy token (?:(?!我会|我将).) 排除「我会/我将」开头的陈述句
//      （如「登录完成后我会告诉你下一步」「处理完成后我会通知你」）
//   3. 避免描述性语句误触发，也避免连环确认（误点后发虚假「已完成」）
const CONFIRM_PATTERNS = [
  /扫码(授权|登录|验证).{0,15}(完成|后)(?:(?!我会|我将).){0,10}(告诉|通知|说|喊|继续)/,
  /(授权|登录).{0,5}完成(?:(?!我会|我将).){0,10}(告诉|通知|说|喊|继续)/,
  /(完成|操作完)后(?:(?!我会|我将).){0,10}(告诉|通知|说|喊|继续)/,
];

export interface ActionConfirmConfig {
  shouldShow: boolean;
  confirmText: string;
  autoMessage: string;
}

export function detectActionConfirm(content: string): ActionConfirmConfig | null {
  for (const pattern of CONFIRM_PATTERNS) {
    if (pattern.test(content)) {
      if (content.includes("授权")) {
        return {
          shouldShow: true,
          confirmText: "已完成授权，请继续",
          autoMessage: "已完成授权，请继续。",
        };
      }
      if (content.includes("登录")) {
        return {
          shouldShow: true,
          confirmText: "已完成登录，请继续",
          autoMessage: "已完成登录，请继续。",
        };
      }
      return {
        shouldShow: true,
        confirmText: "已完成，请继续",
        autoMessage: "已完成，请继续。",
      };
    }
  }
  return null;
}

interface ActionConfirmDialogProps {
  open: boolean;
  confirmText: string;
  onConfirm: () => void;
  onCancel: () => void;
}

function ActionConfirmDialog({
  open,
  confirmText,
  onConfirm,
  onCancel,
}: ActionConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(o: boolean) => !o && onCancel()}>
      <DialogContent showCloseButton={false} className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-green-500" />
            确认继续
          </DialogTitle>
          <DialogDescription>
            完成操作后点击确认，我会继续执行后续任务。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="flex-col sm:flex-row gap-2">
          <Button variant="outline" onClick={onCancel} className="sm:mr-auto">
            取消
          </Button>
          <Button onClick={onConfirm}>
            {confirmText}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface ActionConfirmBarProps {
  content: string;
  isStreaming: boolean;
  isLast: boolean;
  onConfirm: (message: string) => void;
}

export function ActionConfirmBar({ content, isStreaming, isLast, onConfirm }: ActionConfirmBarProps) {
  const [config, setConfig] = useState<ActionConfirmConfig | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const onConfirmRef = useRef(onConfirm);
  onConfirmRef.current = onConfirm;
  // 跟踪 streaming 状态，只在 streaming→non-streaming 转换时检测，
  // 避免 content 被后端回写更新后重置 confirmed 导致按钮复活
  const wasStreamingRef = useRef(false);

  useEffect(() => {
    if (isStreaming) {
      wasStreamingRef.current = true;
      setConfig(null);
      return;
    }
    if (wasStreamingRef.current) {
      const detected = detectActionConfirm(content);
      setConfig(detected);
      setConfirmed(false);
      wasStreamingRef.current = false;
    }
  }, [content, isStreaming]);

  const handleConfirm = useCallback(() => {
    if (!config) return;
    setDialogOpen(false);
    // 先发送，成功后再置 confirmed，失败则按钮保持可见可重试
    try {
      onConfirmRef.current(config.autoMessage);
      setConfirmed(true);
    } catch {
      // 发送异常时不置 confirmed，用户可重试
    }
  }, [config]);

  const handleCancel = useCallback(() => {
    setDialogOpen(false);
  }, []);

  if (!config || !config.shouldShow || !isLast || confirmed || isStreaming) {
    return null;
  }

  return (
    <>
      <div className="mt-3 pt-2 border-t border-border/50">
        <Button
          size="sm"
          onClick={() => setDialogOpen(true)}
          className="gap-2"
        >
          <CheckCircle2 className="h-4 w-4" />
          {config.confirmText}
        </Button>
      </div>
      <ActionConfirmDialog
        open={dialogOpen}
        confirmText={config.confirmText}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </>
  );
}
