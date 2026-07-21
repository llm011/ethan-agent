import { describe, it, expect, vi } from "vitest";
import { consumeStream, type ConsumeStreamActions } from "@/components/chat/use-chat-stream";
import type { StreamChunk } from "@/lib/api";

// Helper: create a mock actions object
function mockActions(): ConsumeStreamActions {
  return {
    setMessages: vi.fn(),
    setConsentRequest: vi.fn(),
    setBgPolling: vi.fn(),
    setSessionTitle: vi.fn(),
    setSessionUsage: vi.fn(),
    setStopping: vi.fn(),
    setStreaming: vi.fn(),
    activeSession: "test-session",
  };
}

// Helper: create an async generator from an array of chunks
async function* chunksToStream(chunks: StreamChunk[]): AsyncGenerator<StreamChunk> {
  for (const chunk of chunks) {
    yield chunk;
  }
}

// Helper: create an async generator that throws
async function* throwingStream(error: Error): AsyncGenerator<StreamChunk> {
  throw error;
}

// Helper: yields some content then throws
async function* contentThenThrow(content: string, error: Error): AsyncGenerator<StreamChunk> {
  yield { content };
  throw error;
}

describe("consumeStream", () => {
  it("returns { failed: false } on normal completion", async () => {
    const stream = chunksToStream([
      { content: "Hello" },
      { content: " world" },
      { done: true, usage: { input: 10, output: 5, cache: 0 } },
    ]);

    const result = await consumeStream(stream, [], mockActions());

    expect(result).toEqual({ failed: false });
  });

  it("returns { failed: true } when chunk.error is received", async () => {
    const stream = chunksToStream([
      { content: "partial" },
      { error: "Server error occurred" },
    ]);

    const result = await consumeStream(stream, [], mockActions());

    expect(result).toEqual({ failed: true });
  });

  it("returns { failed: true } when stream throws (connection interrupted)", async () => {
    const stream = throwingStream(new Error("Network failure"));

    const result = await consumeStream(stream, [], mockActions());

    expect(result).toEqual({ failed: true });
  });

  it("returns { failed: true } when stream throws after partial content", async () => {
    const stream = contentThenThrow("partial content", new Error("Connection reset"));

    const result = await consumeStream(stream, [], mockActions());

    expect(result).toEqual({ failed: true });
  });

  it("returns { failed: false } when stream is stopped by user", async () => {
    const stream = chunksToStream([
      { content: "Hello" },
      { stopped: true, usage: { input: 10, output: 2, cache: 0 } },
    ]);

    const result = await consumeStream(stream, [], mockActions());

    // stopped is intentional, not a failure
    expect(result).toEqual({ failed: false });
  });

  it("calls setStreaming(false) on completion", async () => {
    const actions = mockActions();
    const stream = chunksToStream([{ done: true }]);

    await consumeStream(stream, [], actions);

    expect(actions.setStreaming).toHaveBeenCalledWith(false);
  });

  it("calls setStreaming(false) even on error", async () => {
    const actions = mockActions();
    const stream = throwingStream(new Error("boom"));

    await consumeStream(stream, [], actions);

    expect(actions.setStreaming).toHaveBeenCalledWith(false);
  });
});
