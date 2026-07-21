import { describe, it, expect, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { createRef } from "react";
import { ChatInput, type ChatInputHandle } from "@/components/chat/chat-input";

// Minimal props to render ChatInput
function defaultProps() {
  return {
    streaming: false,
    models: [{ id: "gpt-4", description: "GPT-4" }],
    selectedModel: "gpt-4",
    pendingFiles: [],
    quote: null,
    inputRef: { current: null },
    onModelChange: vi.fn(),
    onSend: vi.fn(),
    onFilesChange: vi.fn(),
    onQuoteCancel: vi.fn(),
  };
}

describe("ChatInput restoreInput", () => {
  it("restoreInput sets textarea value via imperative handle", async () => {
    const ref = createRef<ChatInputHandle>();

    render(<ChatInput ref={ref} {...defaultProps()} />);

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toBe("");

    act(() => {
      ref.current!.restoreInput("恢复的文本");
    });

    expect(textarea.value).toBe("恢复的文本");
  });

  it("restoreInput can be called multiple times", async () => {
    const ref = createRef<ChatInputHandle>();

    render(<ChatInput ref={ref} {...defaultProps()} />);

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;

    act(() => {
      ref.current!.restoreInput("first");
    });
    expect(textarea.value).toBe("first");

    act(() => {
      ref.current!.restoreInput("second");
    });
    expect(textarea.value).toBe("second");
  });

  it("ref.current is available after mount", () => {
    const ref = createRef<ChatInputHandle>();

    render(<ChatInput ref={ref} {...defaultProps()} />);

    expect(ref.current).not.toBeNull();
    expect(typeof ref.current!.restoreInput).toBe("function");
  });
});
