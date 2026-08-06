import { useState, useEffect, useCallback, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow, Window } from "@tauri-apps/api/window";
import { type ThemeId, THEMES, normalizeThemeId } from "../components/chat/themes";
import { notifyDesktop } from "../lib/notify";

const DEFAULT_MINUTES = parseInt(localStorage.getItem("countdown_minutes") || "25") || 25;
type Phase = "idle" | "running" | "paused" | "done";

function playChime() {
  try {
    const ctx = new AudioContext();
    const notes = [523.25, 659.25, 783.99]; // C5, E5, G5
    notes.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.3, ctx.currentTime + i * 0.2);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.2 + 0.8);
      osc.connect(gain).connect(ctx.destination);
      osc.start(ctx.currentTime + i * 0.2);
      osc.stop(ctx.currentTime + i * 0.2 + 0.8);
    });
  } catch { /* audio not available */ }
}

interface CountdownColors {
  bg: string;
  cardTop: string;
  cardBot: string;
  digit: string;
  sep: string;
  line: string;
  btn: string;
  btnHover: string;
  accent: string;
}

function getColorsForTheme(id: ThemeId): CountdownColors {
  const theme = THEMES.find((t) => t.id === id) ?? THEMES[0];
  const isDark = theme.isDark || (id === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  if (isDark) {
    return { bg: "#2e2e2e", cardTop: "#141414", cardBot: "#0e0e0e", digit: "#e8e8e8", sep: "#555", line: "rgba(46,46,46,0.8)", btn: "rgba(0,0,0,0.5)", btnHover: "rgba(0,0,0,0.7)", accent: "#4a9eff" };
  }
  switch (id) {
    case "qingwa":
      return { bg: "#e8ede6", cardTop: "#f5f7f2", cardBot: "#eef1eb", digit: "#3a5a48", sep: "#b3c4b8", line: "rgba(111,155,134,0.2)", btn: "rgba(255,255,255,0.7)", btnHover: "rgba(255,255,255,0.9)", accent: "#6f9b86" };
    case "warm":
      return { bg: "#f5ede4", cardTop: "#fdfbf8", cardBot: "#f8f3ed", digit: "#7a5a32", sep: "#d4b896", line: "rgba(201,138,82,0.2)", btn: "rgba(255,255,255,0.7)", btnHover: "rgba(255,255,255,0.9)", accent: "#c98a52" };
    case "paper":
      return { bg: "#eeedea", cardTop: "#fbfaf7", cardBot: "#f4f2ee", digit: "#5a5346", sep: "#c4bfb4", line: "rgba(138,127,109,0.2)", btn: "rgba(255,255,255,0.7)", btnHover: "rgba(255,255,255,0.9)", accent: "#8a7f6d" };
    case "mist":
      return { bg: "#e9ecef", cardTop: "#fbfcfd", cardBot: "#f3f5f7", digit: "#4a5563", sep: "#b4bcc6", line: "rgba(107,119,135,0.2)", btn: "rgba(255,255,255,0.7)", btnHover: "rgba(255,255,255,0.9)", accent: "#6b7787" };
    default:
      return { bg: "#e8ede6", cardTop: "#f5f7f2", cardBot: "#eef1eb", digit: "#3a5a48", sep: "#b3c4b8", line: "rgba(111,155,134,0.2)", btn: "rgba(255,255,255,0.7)", btnHover: "rgba(255,255,255,0.9)", accent: "#6f9b86" };
  }
}

/**
 * Flip card: visually one number, split by a horizontal line.
 * On change, the top half (old) flips down to reveal new value.
 */
function FlipCard({ value }: { value: string }) {
  const [topValue, setTopValue] = useState(value);
  const [botValue, setBotValue] = useState(value);
  const [flipValue, setFlipValue] = useState<string | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const keyRef = useRef(0);

  useEffect(() => {
    if (value !== topValue) {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      // Start flip: flap shows old value, top immediately shows new
      setFlipValue(topValue);
      setTopValue(value);
      keyRef.current += 1;
      // Bottom stays as old value until flip finishes
      timeoutRef.current = setTimeout(() => {
        setBotValue(value);
        setFlipValue(null);
      }, 500);
    }
  }, [value, topValue]);

  return (
    <div className="fc" data-tauri-drag-region>
      <div className="fc-top" data-tauri-drag-region>
        <span data-tauri-drag-region>{topValue}</span>
      </div>
      <div className="fc-bot" data-tauri-drag-region>
        <span data-tauri-drag-region>{botValue}</span>
      </div>
      {flipValue !== null && (
        <div className="fc-flap" key={keyRef.current} data-tauri-drag-region>
          <span data-tauri-drag-region>{flipValue}</span>
        </div>
      )}
      <div className="fc-line" />
    </div>
  );
}

export default function CountdownPage() {
  const [totalSeconds, setTotalSeconds] = useState(DEFAULT_MINUTES * 60);
  const [remaining, setRemaining] = useState(DEFAULT_MINUTES * 60);
  const [phase, setPhase] = useState<Phase>("idle");
  const [alwaysOnTop, setAlwaysOnTop] = useState(() => {
    const saved = localStorage.getItem("countdown_pin");
    return saved !== null ? saved === "1" : true;
  });
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [colors, setColors] = useState<CountdownColors>(() =>
    getColorsForTheme(normalizeThemeId(localStorage.getItem("ethan-theme")))
  );

  useEffect(() => {
    const syncTheme = () => setColors(getColorsForTheme(normalizeThemeId(localStorage.getItem("ethan-theme"))));
    const syncSettings = (e: StorageEvent) => {
      if (e.key === "ethan-theme") syncTheme();
      if (e.key === "countdown_minutes" && e.newValue) {
        const mins = parseInt(e.newValue) || 25;
        const newTotal = mins * 60;
        setTotalSeconds(newTotal);
        if (phase === "idle") setRemaining(newTotal);
      }
      if (e.key === "countdown_pin") {
        const pin = e.newValue !== "0";
        setAlwaysOnTop(pin);
        invoke("set_countdown_always_on_top", { onTop: pin }).catch(() => {});
      }
    };
    window.addEventListener("storage", syncSettings);
    const poll = setInterval(syncTheme, 2000);
    invoke("set_countdown_always_on_top", { onTop: alwaysOnTop }).catch(() => {});
    return () => { window.removeEventListener("storage", syncSettings); clearInterval(poll); };
  }, []);

  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;

  const clearTimer = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const startTimer = useCallback(() => {
    clearTimer();
    if (phase === "idle" || phase === "done") {
      setRemaining(totalSeconds);
    }
    setPhase("running");
  }, [clearTimer, phase, totalSeconds]);

  useEffect(() => {
    if (phase === "running") {
      intervalRef.current = setInterval(() => {
        setRemaining((prev) => {
          if (prev <= 1) {
            clearTimer();
            setPhase("done");
            return totalSeconds;
          }
          return prev - 1;
        });
      }, 1000);
    }
    return clearTimer;
  }, [phase, clearTimer]);

  useEffect(() => {
    if (phase !== "done") return;
    notifyDesktop({ title: "倒计时结束", body: "休息一下吧 ☕" });
    playChime();
  }, [phase]);

  const togglePause = () => {
    if (phase === "running") { clearTimer(); setPhase("paused"); }
    else if (phase === "paused") { setPhase("running"); }
    else { startTimer(); }
  };

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.code === "Space") {
        e.preventDefault();
        togglePause();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  });

  useEffect(() => {
    const handleCommand = (e: StorageEvent) => {
      if (e.key !== "countdown_command" || !e.newValue) return;
      try {
        const cmd = JSON.parse(e.newValue);
        switch (cmd.action) {
          case "start":
            if (cmd.minutes) {
              const newTotal = Math.max(1, Math.min(999, cmd.minutes)) * 60;
              setTotalSeconds(newTotal);
              setRemaining(newTotal);
            }
            clearTimer();
            setPhase("running");
            break;
          case "pause":
            if (phase === "running") { clearTimer(); setPhase("paused"); }
            break;
          case "resume":
            if (phase === "paused") setPhase("running");
            break;
          case "reset":
            clearTimer(); setRemaining(totalSeconds); setPhase("idle");
            break;
        }
      } catch { /* ignore */ }
    };
    window.addEventListener("storage", handleCommand);
    return () => window.removeEventListener("storage", handleCommand);
  });

  const reset = () => { clearTimer(); setRemaining(totalSeconds); setPhase("idle"); };

  const handleClose = async () => {
    try { await invoke("close_countdown_window"); }
    catch { await getCurrentWindow().close(); }
  };

  const openSettings = async () => {
    try {
      const main = await Window.getByLabel("main");
      if (main) {
        await main.show();
        await main.setFocus();
        await main.emit("navigate", "/settings/countdown");
      }
    } catch { /* fallback: ignore */ }
  };

  const pad = (n: number) => n.toString().padStart(2, "0");

  const LeftControls = () => {
    if (phase === "idle" || phase === "done") {
      return (
        <button className="cd-btn" onClick={(e) => { e.stopPropagation(); startTimer(); }} title="Start">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>
        </button>
      );
    }
    return (
      <>
        {phase === "running" ? (
          <button className="cd-btn" onClick={(e) => { e.stopPropagation(); togglePause(); }} title="Pause">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
          </button>
        ) : (
          <button className="cd-btn" onClick={(e) => { e.stopPropagation(); setPhase("running"); }} title="Resume">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>
          </button>
        )}
        <button className="cd-btn" onClick={(e) => { e.stopPropagation(); reset(); }} title="Reset">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
        </button>
      </>
    );
  };

  return (
    <div className="cd-root" data-tauri-drag-region onDoubleClick={togglePause}>
      <div className="cd-inner" data-tauri-drag-region>
        <div className="cd-clock" data-tauri-drag-region>
          <FlipCard value={pad(minutes)} />
          <span className="cd-sep" data-tauri-drag-region>:</span>
          <FlipCard value={pad(seconds)} />
        </div>
      </div>

      <div className="cd-corner-bl"><LeftControls /></div>
      <div className="cd-corner-br">
        <button className="cd-btn" onClick={(e) => { e.stopPropagation(); openSettings(); }} title="Settings">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </button>
        <button className="cd-btn" onClick={(e) => { e.stopPropagation(); handleClose(); }} title="Close">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>

      <style>{`
        html, body { background: transparent !important; margin: 0; padding: 0; overflow: hidden; }
        * { box-sizing: border-box; }
        .cd-root {
          --cd-bg: ${colors.bg};
          --cd-card-top: ${colors.cardTop};
          --cd-card-bot: ${colors.cardBot};
          --cd-digit: ${colors.digit};
          --cd-sep: ${colors.sep};
          --cd-line: ${colors.line};
          --cd-btn: ${colors.btn};
          --cd-btn-hover: ${colors.btnHover};
          --cd-accent: ${colors.accent};
          width: 100vw; height: 100vh;
          position: relative; overflow: visible;
          user-select: none; -webkit-user-select: none;
          cursor: grab;
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          padding: 0;
        }
        .cd-root * { user-select: none; -webkit-user-select: none; }

        .cd-inner {
          position: absolute; inset: 0;
          display: flex; align-items: center; justify-content: center;
          background: var(--cd-bg);
          border-radius: min(14px, 8vw, 15vh);
          overflow: hidden;
        }

        .cd-corner-bl, .cd-corner-br {
          position: absolute; display: flex; gap: 3px;
          opacity: 0; transition: opacity 0.2s; z-index: 20;
        }
        .cd-corner-bl { bottom: 8px; left: 8px; }
        .cd-corner-br { bottom: 8px; right: 8px; }
        .cd-root:hover .cd-corner-bl, .cd-root:hover .cd-corner-br { opacity: 1; }

        .cd-btn {
          width: 22px; height: 22px; border: none;
          background: var(--cd-btn); border-radius: 6px;
          color: var(--cd-digit); display: flex; align-items: center; justify-content: center;
          cursor: pointer; transition: background 0.15s, color 0.15s;
        }
        .cd-btn:hover { background: var(--cd-btn-hover); }

        .cd-clock { display: flex; align-items: center; gap: clamp(2px, 1vw, 6px); pointer-events: none; width: 100%; height: 100%; padding: 0 4px; }
        .cd-sep { font-size: clamp(24px, 10vw, 60px); color: var(--cd-sep); font-weight: 700; pointer-events: none; flex-shrink: 0; }

        /* ===== Flip Card =====
         * Two halves (top + bottom) clip the SAME number so it looks like one digit.
         * On change, a "flap" overlay (old value, top-half only) flips downward.
         */
        .fc {
          --h: clamp(46px, 98vh, 240px);
          --fs: clamp(42px, 28vw, 180px);
          --r: clamp(5px, 1.2vw, 10px);
          position: relative;
          flex: 1;
          height: var(--h);
          border-radius: var(--r);
          perspective: 400px;
        }

        .fc-top, .fc-bot, .fc-flap {
          position: absolute; left: 0; right: 0; height: 50%;
          overflow: hidden;
          pointer-events: none;
        }
        .fc-top span, .fc-bot span, .fc-flap span {
          position: absolute; left: 0; right: 0;
          text-align: center;
          font-size: var(--fs); font-weight: 700; color: var(--cd-digit);
          font-variant-numeric: tabular-nums;
          line-height: var(--h);
          height: var(--h);
          pointer-events: none;
        }

        .fc-top {
          top: 0;
          background: var(--cd-card-top);
          border-radius: var(--r) var(--r) 0 0;
          z-index: 1;
        }
        .fc-top span { top: 0; }

        .fc-bot {
          bottom: 0;
          background: var(--cd-card-bot);
          border-radius: 0 0 var(--r) var(--r);
          z-index: 1;
        }
        .fc-bot span { bottom: 0; }

        /* The flap: top-half of the OLD value, sits above fc-top, flips down */
        .fc-flap {
          top: 0;
          background: var(--cd-card-top);
          border-radius: var(--r) var(--r) 0 0;
          transform-origin: bottom center;
          z-index: 3;
          animation: flapDown 0.5s ease-in forwards;
        }
        .fc-flap span { top: 0; }

        .fc-line {
          position: absolute; left: 2px; right: 2px; top: 50%;
          height: 2px; background: var(--cd-line);
          z-index: 5; pointer-events: none; transform: translateY(-50%);
        }

        @keyframes flapDown {
          0% { transform: rotateX(0deg); }
          100% { transform: rotateX(-90deg); }
        }
      `}</style>
    </div>
  );
}
