
import { useMemo, useRef, useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Check, Copy, WrapText } from "lucide-react";

interface CodeBlockProps {
  language: string;
  code: string;
}

// Fixed style object — never changes, so SyntaxHighlighter never re-renders due to style
const BASE_STYLE = {
  margin: 0,
  borderRadius: "0.5rem",
  fontSize: "0.75rem",
  lineHeight: "1.6",
  overflowX: "auto" as const,
};

const LINE_NUMBER_STYLE = {
  color: "#555",
  fontSize: "0.7rem",
  minWidth: "2.5em",
  userSelect: "none" as const,
};

export function CodeBlock({ language, code }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const [wrap, setWrap] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const toggleWrap = () => {
    const next = !wrap;
    setWrap(next);
    // Directly patch the <pre> element — avoids re-rendering SyntaxHighlighter
    const pre = containerRef.current?.querySelector("pre");
    if (pre) {
      pre.style.whiteSpace = next ? "pre-wrap" : "pre";
      pre.style.wordBreak = next ? "break-all" : "normal";
      pre.style.overflowX = next ? "hidden" : "auto";
    }
  };

  // Memoised so the object reference stays stable across parent re-renders
  const customStyle = useMemo(() => BASE_STYLE, []);

  return (
    <div ref={containerRef} className="relative group my-3">
      <div className="absolute right-2 top-2 z-10 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={toggleWrap}
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
      <SyntaxHighlighter
        language={language || "text"}
        style={oneDark}
        showLineNumbers
        lineNumberStyle={LINE_NUMBER_STYLE}
        customStyle={customStyle}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
}
