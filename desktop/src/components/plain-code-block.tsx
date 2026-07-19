import { useState } from "react";
import { Check, Copy, WrapText } from "lucide-react";

interface PlainCodeBlockProps {
  code: string;
  className?: string;
}

export function PlainCodeBlock({ code, className = "" }: PlainCodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const [wrap, setWrap] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={`relative group my-3 ${className}`}>
      <div className="absolute right-2 top-2 z-10 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={() => setWrap((v) => !v)}
          aria-label={wrap ? "关闭自动换行" : "开启自动换行"}
          title={wrap ? "关闭自动换行" : "开启自动换行"}
          className={`p-1.5 rounded bg-zinc-700/80 hover:text-white transition-colors ${
            wrap ? "text-white" : "text-zinc-300"
          }`}
        >
          <WrapText className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={handleCopy}
          aria-label="复制代码"
          title="复制代码"
          className="p-1.5 rounded bg-zinc-700/80 text-zinc-300 hover:text-white transition-colors"
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      </div>
      <pre
        className={`bg-zinc-900 text-zinc-100 rounded-lg p-4 overflow-x-auto text-xs leading-relaxed font-mono ${
          wrap ? "whitespace-pre-wrap break-words" : "whitespace-pre"
        }`}
      >
        <code>{code}</code>
      </pre>
    </div>
  );
}
