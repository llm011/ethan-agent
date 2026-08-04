import type {
  BrowserPageActionResult,
  BrowserPageBaseResult,
  BrowserPageBox,
  BrowserPagePoint,
  BrowserSessionTab,
} from '../../shared';
import type { BrowserSessionStore } from '../session-store';
import type { CdpClient } from '../cdp-client';
import type { BrowserPageRefEntry, BrowserPageRefStore } from '../ref-store';

export interface RuntimeEvaluateResponse<TValue> {
  result?: {
    objectId?: string;
    type?: string;
    subtype?: string;
    value?: TValue;
    description?: string;
  };
  exceptionDetails?: {
    text?: string;
    exception?: {
      description?: string;
    };
  };
}

export interface RuntimeStatus {
  ok: boolean;
  error?: string;
}

export interface GetRuntimeResult extends RuntimeStatus {
  value?: string | number | boolean | null;
  box?: BrowserPageBox;
}

export interface ViewportRuntimeResult {
  width: number;
  height: number;
  deviceScaleFactor: number;
}

export interface LayoutMetricsResult {
  cssContentSize?: {
    width: number;
    height: number;
  };
  contentSize?: {
    width: number;
    height: number;
  };
}

export interface ScreenshotCaptureResult {
  data: string;
}

export interface DomResolveNodeResult {
  object: {
    objectId?: string;
  };
}

export interface DomGetBoxModelResult {
  model: {
    content?: number[];
    border?: number[];
    width: number;
    height: number;
  };
}

export interface RuntimeCallFunctionResponse<TResult> {
  result?: {
    value?: TResult;
    description?: string;
  };
  exceptionDetails?: {
    text?: string;
    exception?: {
      description?: string;
    };
  };
}

export interface PageContext {
  tab: BrowserSessionTab;
  client: CdpClient;
}

export interface ResolvedRef {
  entry: BrowserPageRefEntry;
  objectId: string;
  box: BrowserPageBox;
  center: BrowserPagePoint;
}

/**
 * Internal contract that action modules rely on.
 * Implemented by {@link BrowserPageController} so standalone action
 * functions can access shared state and orchestration helpers.
 */
export interface PageControllerContext {
  readonly sessionStore: BrowserSessionStore;
  readonly refStore: BrowserPageRefStore;
  readonly lastMousePositionByTab: Map<number, BrowserPagePoint>;
  withPage<TResult>(
    sessionId: string,
    run: (context: PageContext) => Promise<TResult>,
  ): Promise<TResult>;
  createBaseResult(
    sessionId: string,
    tab: BrowserSessionTab,
  ): BrowserPageBaseResult;
  createActionResult(
    sessionId: string,
    tab: BrowserSessionTab,
    ref?: string,
  ): BrowserPageActionResult;
}
