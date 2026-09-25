/* 「我的头像 / 名字」编辑块 —— 设置页里唯一设置气泡身份的地方。
 *
 * 两端共用：差异（相对 URL → 绝对 URL、auth token 读取、缓存失效）全部通过
 * props 注入，组件本身只有一套布局与交互，保证两端表现一致。
 *
 * 交互约定：
 * - 选文件即上传（不额外点「保存」）—— 头像是单值字段，多一步确认只会让人以为没生效
 * - 名字必须显式保存（它可能被清空，自动保存分不清「清空」和「还没输入」）
 * - 上传中/保存中都要禁用按钮，避免并发上传让后端的两份文件互相覆盖
 */
import * as React from "react";
import { Loader2, Trash2, Upload } from "lucide-react";

import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { UserAvatar } from "./user-avatar";
import { cn } from "../lib/utils";

export interface UserIdentityEditorProps {
  /** 当前头像相对 URL；空串 = 未设置 */
  avatarUrl: string;
  /** 当前显示名 */
  displayName: string;
  /** 相对 URL → 当前端绝对 URL */
  resolveUrl: (relativePath: string) => string;
  /** 上传头像，返回新的相对 URL */
  onUploadAvatar: (file: File) => Promise<string>;
  /** 清除头像 */
  onClearAvatar: () => Promise<void>;
  /** 保存显示名，返回后端确认后的值 */
  onSaveName: (name: string) => Promise<string>;
  className?: string;
}

/** 前端也拦一道体积/类型：省掉一次注定失败的往返，但后端仍是权威校验。 */
const MAX_AVATAR_BYTES = 5 * 1024 * 1024;
const ACCEPT = "image/png,image/jpeg,image/gif,image/webp,image/bmp";

export function UserIdentityEditor({
  avatarUrl,
  displayName,
  resolveUrl,
  onUploadAvatar,
  onClearAvatar,
  onSaveName,
  className,
}: UserIdentityEditorProps) {
  const fileRef = React.useRef<HTMLInputElement>(null);
  const [currentAvatar, setCurrentAvatar] = React.useState(avatarUrl);
  const [name, setName] = React.useState(displayName);
  const [uploading, setUploading] = React.useState(false);
  const [savingName, setSavingName] = React.useState(false);
  const [status, setStatus] = React.useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  // 父组件异步拿到身份后要同步进来。只在「外部值真的变了」时覆盖本地输入，
  // 否则用户正在输入时会被后台刷新打断。
  const lastSyncedAvatar = React.useRef(avatarUrl);
  React.useEffect(() => {
    if (avatarUrl !== lastSyncedAvatar.current) {
      lastSyncedAvatar.current = avatarUrl;
      setCurrentAvatar(avatarUrl);
    }
  }, [avatarUrl]);
  const lastSyncedName = React.useRef(displayName);
  React.useEffect(() => {
    if (displayName !== lastSyncedName.current) {
      lastSyncedName.current = displayName;
      setName(displayName);
    }
  }, [displayName]);

  React.useEffect(() => {
    if (!status) return;
    const t = setTimeout(() => setStatus(null), status.kind === "ok" ? 2500 : 5000);
    return () => clearTimeout(t);
  }, [status]);

  const pickFile = () => {
    if (uploading) return;
    fileRef.current?.click();
  };

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    // 先清空 input 的值：否则连续选同一个文件不会触发 change，用户会以为「点了没反应」
    e.target.value = "";
    if (!file) return;

    if (!file.type.startsWith("image/")) {
      setStatus({ kind: "err", msg: "请选择图片文件" });
      return;
    }
    if (file.size > MAX_AVATAR_BYTES) {
      setStatus({ kind: "err", msg: `图片超过 ${MAX_AVATAR_BYTES / 1024 / 1024}MB` });
      return;
    }

    setUploading(true);
    try {
      const url = await onUploadAvatar(file);
      setCurrentAvatar(url);
      lastSyncedAvatar.current = url;
      setStatus({ kind: "ok", msg: "头像已更新" });
    } catch (err) {
      setStatus({ kind: "err", msg: err instanceof Error ? err.message : "头像上传失败" });
    } finally {
      setUploading(false);
    }
  };

  const handleClear = async () => {
    if (uploading) return;
    setUploading(true);
    try {
      await onClearAvatar();
      setCurrentAvatar("");
      lastSyncedAvatar.current = "";
      setStatus({ kind: "ok", msg: "已恢复默认头像" });
    } catch (err) {
      setStatus({ kind: "err", msg: err instanceof Error ? err.message : "清除失败" });
    } finally {
      setUploading(false);
    }
  };

  const handleSaveName = async () => {
    setSavingName(true);
    try {
      const saved = await onSaveName(name.trim());
      setName(saved);
      lastSyncedName.current = saved;
      setStatus({ kind: "ok", msg: saved ? "名字已保存" : "名字已清除" });
    } catch (err) {
      setStatus({ kind: "err", msg: err instanceof Error ? err.message : "保存失败" });
    } finally {
      setSavingName(false);
    }
  };

  const nameDirty = name.trim() !== displayName;

  return (
    <div className={cn("rounded-lg border border-border bg-background/40 p-4", className)}>
      <div className="flex items-start gap-4">
        <div className="flex flex-col items-center gap-2">
          {/* 预览用大一号的头像：设置页看得出细节，气泡里那个 28px 太小了 */}
          <UserAvatar url={currentAvatar} name={name} resolveUrl={resolveUrl} size={64} />
          <div className="flex gap-1.5">
            <Button size="sm" variant="outline" onClick={pickFile} disabled={uploading}>
              {uploading ? <Loader2 className="animate-spin" /> : <Upload />}
              上传
            </Button>
            {currentAvatar && (
              <Button size="icon-sm" variant="ghost" onClick={handleClear} disabled={uploading} title="恢复默认头像">
                <Trash2 />
              </Button>
            )}
          </div>
        </div>

        <div className="flex-1 min-w-0 space-y-2">
          <div>
            <label className="text-sm font-medium" htmlFor="user-display-name">
              名字
            </label>
            <p className="text-xs text-muted-foreground mb-1.5">
              显示在对话气泡头像旁。留空则只显示头像。
            </p>
            <div className="flex gap-2">
              <Input
                id="user-display-name"
                value={name}
                maxLength={64}
                placeholder="你的名字"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && nameDirty && !savingName) {
                    e.preventDefault();
                    void handleSaveName();
                  }
                }}
              />
              <Button size="sm" onClick={handleSaveName} disabled={savingName || !nameDirty}>
                {savingName ? "保存中…" : "保存"}
              </Button>
            </div>
          </div>

          <p className="text-xs text-muted-foreground">
            头像会显示在你发送的每条消息旁。未设置时用默认占位（名字首字母或人形图标）。
          </p>
          {status && (
            <p className={cn("text-xs", status.kind === "ok" ? "text-green-600 dark:text-green-400" : "text-destructive")}>
              {status.kind === "ok" ? "✓ " : "⚠ "}
              {status.msg}
            </p>
          )}
        </div>
      </div>

      <input ref={fileRef} type="file" accept={ACCEPT} className="hidden" onChange={handleFile} />
    </div>
  );
}
