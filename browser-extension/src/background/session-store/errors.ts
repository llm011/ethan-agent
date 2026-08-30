import { BROWSER_RPC_ERROR_CODE } from '../../shared';

export class BrowserExtensionRpcError extends Error {
  constructor(
    readonly code: number,
    message: string,
  ) {
    super(message);
  }
}

export function createSessionNotFoundError(
  sessionId: string,
): BrowserExtensionRpcError {
  return new BrowserExtensionRpcError(
    BROWSER_RPC_ERROR_CODE.browserSessionNotFound,
    `Session ${sessionId} not found`,
  );
}

/**
 * attach 失败时抛出，额外带上「失败前已经被物理改动过的 tab」。
 *
 * attach 中间会跨窗口移动 / 摘出旧 group，一旦中途报错，调用方光看错误信息
 * 并不知道浏览器当前到底被改成什么样了。这里把这些 tab 一并交出去，方便上层
 * 判断或提示，而不是只看到一个笼统的失败。
 */
export class BrowserTabAttachError extends BrowserExtensionRpcError {
  constructor(
    code: number,
    message: string,
    readonly touchedTabIds: number[],
  ) {
    super(code, message);
  }
}
