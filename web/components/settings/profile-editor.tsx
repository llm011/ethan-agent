"use client";

import { useState, useEffect } from "react";
import { Button } from "@ethan/shared/ui/button";
import { MdEditor } from "@ethan/shared/components/md-editor";
import { fetchUserProfile, updateUserProfile } from "@/lib/api";

export function ProfileEditor() {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const c = await fetchUserProfile();
        if (alive) setContent(c);
      } catch {
        // ignore
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await updateUserProfile(content);
      setSavedAt(Date.now());
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="h-full flex flex-col min-h-[500px]">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-lg font-medium">我的画像 (user_profile.md)</h3>
        <div className="flex items-center gap-3">
          {savedAt && <span className="text-xs text-muted-foreground">已保存</span>}
          <Button size="sm" onClick={save} disabled={saving || loading}>
            {saving ? "保存中…" : "保存"}
          </Button>
        </div>
      </div>
      <p className="text-sm text-muted-foreground mb-4">
        关于你的长期画像。填写姓名、性格、偏好等信息，Agent 会在回复时参考。后台记忆整理时会自动抽取并补充，也可在此直接查看与编辑。
      </p>
      {loading ? (
        <div className="text-sm text-muted-foreground">加载中…</div>
      ) : (
        <MdEditor
          value={content}
          onChange={setContent}
          placeholder={"# 用户画像\n\n## 基础特征\n- ...\n\n## 心理与情绪\n- ..."}
        />
      )}
    </div>
  );
}
