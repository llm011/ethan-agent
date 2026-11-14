/**
 * 语音设置（TTS / ASR 后端选择 + 一键配置）—— desktop / web 共用。
 *
 * 设计要点：
 *
 * 1. **本地后端不可用不是错误，是常态**。
 *    ethan-tts 依赖 Apple Silicon + MLX，Windows/Linux/Intel Mac 都跑不了。
 *    所以不可用时展示「为什么不能 + 改用在线后端」，而不是一个红色报错。
 *
 * 2. **一键配置前先说清代价**。
 *    本地后端要下 MLX + 几百 MB 模型权重、要几分钟。按钮旁标明，用户才不会被
 *    「点了没反应」困扰。预检不过时按钮直接禁用并给出原因——不让用户白等。
 *
 * 3. **ASR 独立开关但依赖 TTS 后端**。
 *    两者共用同一个 ethan-tts 安装，所以 ASR 可用性跟着 TTS 走。默认 off：
 *    语音输入需要麦克风权限 + 模型，不该默认开。
 */

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  Loader2,
  Mic,
  RefreshCw,
  Volume2,
} from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";

export interface VoiceCheck {
  name: string;
  status: "ok" | "error" | "warn";
  detail: string;
  fix: string;
}

export interface VoiceBackend {
  backend: string;
  available: boolean;
  reason: string;
  cli_path: string;
  service_url: string;
  service_running: boolean;
  checks: VoiceCheck[];
}

export interface VoiceBackendsResponse {
  tts: Record<string, VoiceBackend>;
  asr: VoiceBackend;
  platform: { system: string; machine: string; apple_silicon: boolean };
  python: string;
  current: { tts: string; asr: string };
}

export interface VoiceSettingsProps {
  data: VoiceBackendsResponse | null;
  loading?: boolean;
  busy?: string;
  onRefresh: () => void;
  onSelect: (payload: { tts?: string; asr?: string }) => Promise<void>;
  onSetup: () => Promise<void>;
}

const TTS_LABELS: Record<string, { name: string; desc: string }> = {
  "edge-tts": {
    name: "Edge TTS（在线）",
    desc: "微软在线语音，零安装、跨平台。需要联网，音色与语气控制较弱。",
  },
  "ethan-tts": {
    name: "Ethan TTS（本地）",
    desc: "本机 Qwen3-TTS，离线、可克隆音色、可调语气。需要 Apple Silicon。",
  },
};

function StatusDot({ ok }: { ok: boolean }) {
  return ok ? (
    <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
  ) : (
    <AlertCircle className="h-3.5 w-3.5 text-amber-500" />
  );
}

export function VoiceSettings({
  data,
  loading = false,
  busy = "",
  onRefresh,
  onSelect,
  onSetup,
}: VoiceSettingsProps) {
  const [error, setError] = useState("");
  const [showChecks, setShowChecks] = useState(false);

  const handleSelect = useCallback(
    async (payload: { tts?: string; asr?: string }) => {
      setError("");
      try {
        await onSelect(payload);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [onSelect],
  );

  const handleSetup = useCallback(async () => {
    setError("");
    try {
      await onSetup();
      onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [onSetup, onRefresh]);

  const localTts = data?.tts?.["ethan-tts"];
  const currentTts = data?.current?.tts ?? "";
  const currentAsr = data?.current?.asr ?? "off";
  const failedChecks = (localTts?.checks ?? []).filter((c) => c.status === "error");

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Volume2 className="h-4 w-4" />
            语音
          </CardTitle>
          <Button variant="ghost" size="sm" onClick={onRefresh} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          语音合成（朗读）与语音识别（说话输入）。本地后端离线可用但仅限 Apple
          Silicon；在线后端零安装。
        </p>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* ── TTS 后端 ── */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-medium">语音合成（TTS）</span>
            {data && !data.platform.apple_silicon && (
              <Badge variant="outline" className="text-[10px]">
                {data.platform.system} {data.platform.machine}
              </Badge>
            )}
          </div>

          <div className="space-y-2">
            {Object.entries(TTS_LABELS).map(([key, label]) => {
              const probe = data?.tts?.[key];
              const isCurrent = currentTts === key;
              const isBusy = busy === key;
              const available = probe?.available ?? key === "edge-tts";

              return (
                <div
                  key={key}
                  className={`rounded-lg border p-3 ${
                    isCurrent ? "border-primary/40 bg-primary/5" : "border-border"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusDot ok={available} />
                        <span className="text-sm font-medium">{label.name}</span>
                        {isCurrent && (
                          <Badge variant="default" className="text-[10px]">
                            当前
                          </Badge>
                        )}
                        {key === "ethan-tts" && probe?.service_running && (
                          <Badge variant="outline" className="text-[10px]">
                            服务运行中
                          </Badge>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{label.desc}</p>

                      {/* 不可用原因：这是用户最需要知道的 */}
                      {!available && probe?.reason && (
                        <p className="mt-1 text-xs text-amber-500">{probe.reason}</p>
                      )}
                    </div>

                    <div className="shrink-0">
                      {key === "ethan-tts" && !available ? (
                        <Button
                          size="sm"
                          onClick={handleSetup}
                          disabled={isBusy || !data?.platform.apple_silicon}
                          title={
                            data?.platform.apple_silicon
                              ? "下载依赖与模型，需要几分钟"
                              : "当前平台不支持本地推理"
                          }
                        >
                          {isBusy ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Download className="h-3.5 w-3.5" />
                          )}
                          一键配置
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant={isCurrent ? "secondary" : "default"}
                          disabled={isCurrent || isBusy || !available}
                          onClick={() => handleSelect({ tts: key })}
                        >
                          {isBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                          {isCurrent ? "使用中" : "启用"}
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* 预检明细：默认收起，出问题时才需要看 */}
          {localTts && localTts.checks.length > 0 && (
            <div className="mt-2">
              <button
                type="button"
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
                onClick={() => setShowChecks((v) => !v)}
              >
                环境检查 {failedChecks.length > 0 && `(${failedChecks.length} 项异常)`}
                <span className="text-[10px]">{showChecks ? "收起" : "展开"}</span>
              </button>
              {showChecks && (
                <div className="mt-1.5 space-y-1 rounded-md border p-2">
                  {localTts.checks.map((c) => (
                    <div key={c.name} className="flex items-start gap-2 text-[11px]">
                      <StatusDot ok={c.status === "ok"} />
                      <span className="w-20 shrink-0 text-muted-foreground">{c.name}</span>
                      <span className="min-w-0 flex-1 break-all">{c.detail}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── ASR 开关 ── */}
        <div className="border-t pt-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <Mic className="h-3.5 w-3.5" />
                <span className="text-sm font-medium">语音识别（ASR）</span>
                {currentAsr !== "off" && (
                  <Badge variant="default" className="text-[10px]">
                    已启用
                  </Badge>
                )}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                语音输入的识别引擎。依赖本地语音后端；关闭时只能打字。
              </p>
            </div>
            <Button
              size="sm"
              variant={currentAsr === "off" ? "default" : "secondary"}
              disabled={busy === "asr" || (currentAsr === "off" && !data?.asr?.available)}
              onClick={() => handleSelect({ asr: currentAsr === "off" ? "ethan-tts" : "off" })}
            >
              {busy === "asr" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {currentAsr === "off" ? "启用" : "关闭"}
            </Button>
          </div>
          {currentAsr === "off" && data?.asr && !data.asr.available && (
            <p className="mt-1 text-xs text-amber-500">{data.asr.reason}</p>
          )}
        </div>

        {error && (
          <div className="flex gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="whitespace-pre-wrap">{error}</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
