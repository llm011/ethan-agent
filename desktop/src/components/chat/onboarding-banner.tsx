import { useState } from "react";
import { completeOnboarding } from "@/lib/api";

interface OnboardingBannerProps {
  onDismiss: () => void;
}

export function OnboardingBanner({ onDismiss }: OnboardingBannerProps) {
  const [agentName, setAgentName] = useState("");
  const [userInfo, setUserInfo] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await completeOnboarding(agentName.trim() || "Ethan", userInfo.trim());
    } catch {
      // ignore
    } finally {
      setSubmitting(false);
      onDismiss();
    }
  };

  return (
    <div className="mb-4 rounded-xl border border-yellow-500/40 bg-yellow-500/10 p-4 space-y-3">
      <p className="text-sm font-semibold text-yellow-600 dark:text-yellow-400">
        👋 Welcome! Let me introduce myself.
      </p>
      <p className="text-xs text-muted-foreground leading-relaxed">
        Before we get started, I have two quick questions to personalize our experience.
        You can always update these in Settings later.
      </p>
      <div className="space-y-2">
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">
            What would you like to call me? <span className="opacity-60">(default: Ethan)</span>
          </label>
          <input
            type="text"
            placeholder="Ethan"
            value={agentName}
            onChange={(e) => setAgentName(e.target.value)}
            className="w-full bg-background border border-border rounded-lg px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">
            Who are you? <span className="opacity-60">(e.g. "I'm Alex, a software engineer")</span>
          </label>
          <input
            type="text"
            placeholder="I'm ..."
            value={userInfo}
            onChange={(e) => setUserInfo(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(); }}
            className="w-full bg-background border border-border rounded-lg px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
      </div>
      <div className="flex gap-2 justify-end">
        <button
          onClick={onDismiss}
          className="text-xs text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-lg hover:bg-muted transition-colors"
        >
          Skip
        </button>
        <button
          onClick={handleSubmit}
          disabled={submitting}
          className="text-xs bg-yellow-500 hover:bg-yellow-400 text-white font-semibold px-4 py-1.5 rounded-lg transition-colors disabled:opacity-50"
        >
          {submitting ? "Saving..." : "Let's go!"}
        </button>
      </div>
    </div>
  );
}
