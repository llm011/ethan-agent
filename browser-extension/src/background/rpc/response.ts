import type { JsonRpcRequest, JsonRpcResponse } from '../../shared';

export function createSuccessResponse<T>(
  request: JsonRpcRequest,
  result: T,
): JsonRpcResponse<T> {
  return {
    jsonrpc: '2.0',
    id: request.id ?? null,
    result,
  };
}

export function createErrorResponse(
  request: Partial<JsonRpcRequest>,
  code: number,
  message: string,
): JsonRpcResponse {
  return {
    jsonrpc: '2.0',
    id: request.id ?? null,
    error: {
      code,
      message,
    },
  };
}

export function isJsonRpcRequest(value: unknown): value is JsonRpcRequest {
  if (!value || typeof value !== 'object') {
    return false;
  }

  const candidate = value as Partial<JsonRpcRequest>;
  return candidate.jsonrpc === '2.0' && typeof candidate.method === 'string';
}
