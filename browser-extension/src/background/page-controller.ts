/* eslint-disable max-lines -- page CDP controller keeps MVP operations together */
import type {
  BrowserPageActionResult,
  BrowserPageBaseResult,
  BrowserPageBox,
  BrowserPageEvalParams,
  BrowserPageEvalResult,
  BrowserPageGetParams,
  BrowserPageGetResult,
  BrowserPageMouseButton,
  BrowserPageMouseParams,
  BrowserPagePoint,
  BrowserPagePressParams,
  BrowserPageScreenshotParams,
  BrowserPageScreenshotResult,
  BrowserPageSnapshotParams,
  BrowserPageSnapshotResult,
  BrowserPageWaitParams,
  BrowserPageWaitResult,
  BrowserSessionTab,
} from '../shared';
import { BROWSER_RPC_ERROR_CODE } from '../shared';

import { BrowserExtensionRpcError } from './session-store';
import type { BrowserSessionStore } from './session-store';
import {
  createReadyStateExpression,
  createScrollExpression,
  createViewportExpression,
} from './page-runtime';
import { withCdpClient } from './cdp-client';
import type { CdpClient } from './cdp-client';
import { takeAxSnapshot } from './ax-snapshot';
import { BrowserPageRefStore } from './ref-store';
import type { BrowserPageRefEntry } from './ref-store';

const COORDINATE_SPACE = 'viewport-css-pixel';
const DEFAULT_SCREENSHOT_FORMAT = 'png';
const KEY_MODIFIER_ALT = 1;
const KEY_MODIFIER_CTRL = 2;
const KEY_MODIFIER_META = 4;
const KEY_MODIFIER_SHIFT = 8;
const READY_POLL_INTERVAL_MS = 100;
const READY_TIMEOUT_MS = 10_000;
const NETWORK_IDLE_EXTRA_WAIT_MS = 500;
const DEFAULT_MOUSE_X = 0;
const DEFAULT_MOUSE_Y = 0;

interface RuntimeEvaluateResponse<TValue> {
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

interface RuntimeStatus {
  ok: boolean;
  error?: string;
}

interface GetRuntimeResult extends RuntimeStatus {
  value?: string | number | boolean | null;
  box?: BrowserPageBox;
}

interface ViewportRuntimeResult {
  width: number;
  height: number;
  deviceScaleFactor: number;
}

interface LayoutMetricsResult {
  cssContentSize?: {
    width: number;
    height: number;
  };
  contentSize?: {
    width: number;
    height: number;
  };
}

interface ScreenshotCaptureResult {
  data: string;
}

interface DomResolveNodeResult {
  object: {
    objectId?: string;
  };
}

interface DomGetBoxModelResult {
  model: {
    content?: number[];
    border?: number[];
    width: number;
    height: number;
  };
}

interface RuntimeCallFunctionResponse<TResult> {
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

interface PageContext {
  tab: BrowserSessionTab;
  client: CdpClient;
}

interface ResolvedRef {
  entry: BrowserPageRefEntry;
  objectId: string;
  box: BrowserPageBox;
  center: BrowserPagePoint;
}

function createRefNotFoundError(ref: string): BrowserExtensionRpcError {
  return new BrowserExtensionRpcError(
    BROWSER_RPC_ERROR_CODE.browserPageRefNotFound,
    `Snapshot ref ${ref} not found. Run page snapshot again.`,
  );
}

function createPageOperationError(message: string): BrowserExtensionRpcError {
  return new BrowserExtensionRpcError(
    BROWSER_RPC_ERROR_CODE.browserPageOperationFailed,
    message,
  );
}

function getPageInfo(tab: BrowserSessionTab): { url?: string; title?: string } {
  return {
    url: tab.url,
    title: tab.title,
  };
}

function getMouseButton(
  button: BrowserPageMouseButton | undefined,
): 'left' | 'middle' | 'right' {
  return button || 'left';
}

function getKeyDefinition(key: string): {
  key: string;
  code: string;
  windowsVirtualKeyCode: number;
  text?: string;
  modifiers: number;
} {
  const parts = key
    .split('+')
    .map(part => part.trim())
    .filter(Boolean);
  const baseKey = parts.pop() || key;
  let modifiers = 0;
  parts.forEach(part => {
    const normalized = part.toLowerCase();
    if (normalized === 'alt' || normalized === 'option') {
      modifiers |= KEY_MODIFIER_ALT;
    } else if (normalized === 'control' || normalized === 'ctrl') {
      modifiers |= KEY_MODIFIER_CTRL;
    } else if (
      normalized === 'meta' ||
      normalized === 'command' ||
      normalized === 'cmd'
    ) {
      modifiers |= KEY_MODIFIER_META;
    } else if (normalized === 'shift') {
      modifiers |= KEY_MODIFIER_SHIFT;
    }
  });

  const specialKeys: Record<string, { code: string; keyCode: number }> = {
    Enter: { code: 'Enter', keyCode: 13 },
    Tab: { code: 'Tab', keyCode: 9 },
    Escape: { code: 'Escape', keyCode: 27 },
    Backspace: { code: 'Backspace', keyCode: 8 },
    Delete: { code: 'Delete', keyCode: 46 },
    ArrowUp: { code: 'ArrowUp', keyCode: 38 },
    ArrowDown: { code: 'ArrowDown', keyCode: 40 },
    ArrowLeft: { code: 'ArrowLeft', keyCode: 37 },
    ArrowRight: { code: 'ArrowRight', keyCode: 39 },
  };
  const special = specialKeys[baseKey];
  if (special) {
    return {
      key: baseKey,
      code: special.code,
      windowsVirtualKeyCode: special.keyCode,
      modifiers,
    };
  }

  const text = baseKey.length === 1 && modifiers === 0 ? baseKey : undefined;
  return {
    key: baseKey,
    code: baseKey.length === 1 ? `Key${baseKey.toUpperCase()}` : baseKey,
    windowsVirtualKeyCode:
      baseKey.length === 1 ? baseKey.toUpperCase().charCodeAt(0) : 0,
    text,
    modifiers,
  };
}

export class BrowserPageController {
  private readonly lastMousePositionByTab = new Map<number, BrowserPagePoint>();

  private readonly refStore = new BrowserPageRefStore();

  constructor(private readonly sessionStore: BrowserSessionStore) {}

  async snapshot(
    params: BrowserPageSnapshotParams,
  ): Promise<BrowserPageSnapshotResult> {
    return this.withPage(params.sessionId, async ({ tab, client }) => {
      const snapshot = await takeAxSnapshot(client, params);
      this.refStore.reset(tab.tabId, snapshot.refs);
      return {
        ...this.createBaseResult(params.sessionId, tab),
        origin: tab.url || '',
        snapshot: snapshot.snapshot,
        refs: this.refStore.toRecord(tab.tabId),
        viewport: snapshot.viewport,
        elements: snapshot.elements,
      };
    });
  }

  async click(params: {
    sessionId: string;
    ref: string;
  }): Promise<BrowserPageActionResult> {
    return this.withPage(params.sessionId, async ({ tab, client }) => {
      const resolved = await this.resolveRef(client, tab, params.ref, true);
      await this.dispatchMouseMove(
        client,
        resolved.center.x,
        resolved.center.y,
      );
      await this.dispatchMouseButton(
        client,
        'mousePressed',
        resolved.center,
        'left',
      );
      await this.dispatchMouseButton(
        client,
        'mouseReleased',
        resolved.center,
        'left',
      );
      this.lastMousePositionByTab.set(tab.tabId, resolved.center);
      return this.createActionResult(params.sessionId, tab, params.ref);
    });
  }

  async hover(params: {
    sessionId: string;
    ref: string;
  }): Promise<BrowserPageActionResult> {
    return this.withPage(params.sessionId, async ({ tab, client }) => {
      const resolved = await this.resolveRef(client, tab, params.ref, false);
      await this.dispatchMouseMove(
        client,
        resolved.center.x,
        resolved.center.y,
      );
      this.lastMousePositionByTab.set(tab.tabId, resolved.center);
      return this.createActionResult(params.sessionId, tab, params.ref);
    });
  }

  async fill(params: {
    sessionId: string;
    ref: string;
    text: string;
  }): Promise<BrowserPageActionResult> {
    return this.runInsertText(params.sessionId, params.ref, 'fill', params.text);
  }

  async type(params: {
    sessionId: string;
    ref: string;
    text: string;
  }): Promise<BrowserPageActionResult> {
    return this.runInsertText(params.sessionId, params.ref, 'type', params.text);
  }

  async select(params: {
    sessionId: string;
    ref: string;
    value: string;
  }): Promise<BrowserPageActionResult> {
    return this.runDomAction(
      params.sessionId,
      params.ref,
      'select',
      params.value,
    );
  }

  async scrollIntoView(params: {
    sessionId: string;
    ref: string;
  }): Promise<BrowserPageActionResult> {
    return this.runDomAction(params.sessionId, params.ref, 'scrollIntoView');
  }

  async press(
    params: BrowserPagePressParams,
  ): Promise<BrowserPageActionResult> {
    return this.withPage(params.sessionId, async ({ tab, client }) => {
      const definition = getKeyDefinition(params.key);
      await client.send('Input.dispatchKeyEvent', {
        type: 'rawKeyDown',
        key: definition.key,
        code: definition.code,
        windowsVirtualKeyCode: definition.windowsVirtualKeyCode,
        modifiers: definition.modifiers,
        ...(definition.text ? { text: definition.text } : {}),
      });
      await client.send('Input.dispatchKeyEvent', {
        type: 'keyUp',
        key: definition.key,
        code: definition.code,
        windowsVirtualKeyCode: definition.windowsVirtualKeyCode,
        modifiers: definition.modifiers,
      });
      return this.createActionResult(params.sessionId, tab);
    });
  }

  async scroll(params: {
    sessionId: string;
    direction: 'up' | 'down';
    pixels: number;
  }): Promise<BrowserPageActionResult> {
    return this.withPage(params.sessionId, async ({ tab, client }) => {
      this.ensureRuntimeOk(
        await this.evaluate<RuntimeStatus>(
          client,
          createScrollExpression(params.direction, params.pixels),
        ),
      );
      return this.createActionResult(params.sessionId, tab);
    });
  }

  async screenshot(
    params: BrowserPageScreenshotParams,
  ): Promise<BrowserPageScreenshotResult> {
    return this.withPage(params.sessionId, async ({ tab, client }) => {
      await client.send('Page.enable');
      const viewport = await this.evaluate<ViewportRuntimeResult>(
        client,
        createViewportExpression(),
      );
      const format = params.format || DEFAULT_SCREENSHOT_FORMAT;
      const screenshotParams: Record<string, unknown> = {
        format,
        fromSurface: true,
        captureBeyondViewport: Boolean(params.fullPage),
        ...(format === 'jpeg' && typeof params.quality === 'number'
          ? { quality: params.quality }
          : {}),
      };
      let width = viewport.width;
      let height = viewport.height;

      if (params.fullPage) {
        const metrics = await client.send<LayoutMetricsResult>(
          'Page.getLayoutMetrics',
        );
        const contentSize = metrics.cssContentSize || metrics.contentSize;
        width = Math.ceil(contentSize?.width || viewport.width);
        height = Math.ceil(contentSize?.height || viewport.height);
        screenshotParams.clip = {
          x: 0,
          y: 0,
          width,
          height,
          scale: 1,
        };
      }

      const captured = await client.send<ScreenshotCaptureResult>(
        'Page.captureScreenshot',
        screenshotParams,
      );
      return {
        ...this.createBaseResult(params.sessionId, tab),
        screenshot: {
          data: captured.data,
          mimeType: format === 'jpeg' ? 'image/jpeg' : 'image/png',
          format,
          width,
          height,
          fullPage: Boolean(params.fullPage),
        },
        viewport,
      };
    });
  }

  async get(params: BrowserPageGetParams): Promise<BrowserPageGetResult> {
    return this.withPage(params.sessionId, async ({ tab, client }) => {
      if (params.what === 'title' || params.what === 'url') {
        const value = await this.evaluate<string>(
          client,
          params.what === 'title' ? 'document.title' : 'location.href',
        );
        return {
          ...this.createBaseResult(params.sessionId, tab),
          what: params.what,
          value,
        };
      }

      const resolved = await this.resolveRef(
        client,
        tab,
        params.ref || '',
        false,
      );
      const result = await this.callFunctionOn<GetRuntimeResult>(
        client,
        resolved.objectId,
        `function(what) {
          if (what === 'box') {
            const rect = this.getBoundingClientRect();
            return {
              ok: true,
              box: {
                x: Math.round(rect.x),
                y: Math.round(rect.y),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
              }
            };
          }
          if (what === 'html') return { ok: true, value: this.outerHTML };
          if (what === 'value') return { ok: true, value: 'value' in this ? this.value : null };
          return { ok: true, value: this.innerText || this.textContent || '' };
        }`,
        [params.what],
      );
      this.ensureRuntimeOk(result, params.ref);
      return {
        ...this.createBaseResult(params.sessionId, tab),
        what: params.what,
        ...(result.box ? { box: result.box } : { value: result.value }),
      };
    });
  }

  async eval(params: BrowserPageEvalParams): Promise<BrowserPageEvalResult> {
    return this.withPage(params.sessionId, async ({ tab, client }) => {
      const response = await client.send<RuntimeEvaluateResponse<unknown>>(
        'Runtime.evaluate',
        {
          expression: params.script,
          returnByValue: true,
          awaitPromise: params.awaitPromise !== false,
        },
      );
      if (response.exceptionDetails) {
        throw createPageOperationError(
          response.exceptionDetails.exception?.description ||
            response.exceptionDetails.text ||
            'Runtime evaluation failed',
        );
      }
      return {
        ...this.createBaseResult(params.sessionId, tab),
        origin: tab.url || '',
        result:
          typeof response.result?.value !== 'undefined'
            ? response.result.value
            : (response.result?.description ?? null),
      };
    });
  }

  async mouse(
    params: BrowserPageMouseParams,
  ): Promise<BrowserPageActionResult> {
    return this.withPage(params.sessionId, async ({ tab, client }) => {
      const current = this.lastMousePositionByTab.get(tab.tabId) || {
        x: DEFAULT_MOUSE_X,
        y: DEFAULT_MOUSE_Y,
      };
      if (params.action === 'move') {
        const point = {
          x: params.x ?? current.x,
          y: params.y ?? current.y,
        };
        await this.dispatchMouseMove(client, point.x, point.y);
        this.lastMousePositionByTab.set(tab.tabId, point);
      } else if (params.action === 'down') {
        await this.dispatchMouseButton(
          client,
          'mousePressed',
          current,
          params.button,
        );
      } else if (params.action === 'up') {
        await this.dispatchMouseButton(
          client,
          'mouseReleased',
          current,
          params.button,
        );
      } else {
        await client.send('Input.dispatchMouseEvent', {
          type: 'mouseWheel',
          x: current.x,
          y: current.y,
          deltaX: params.deltaX ?? 0,
          deltaY: params.deltaY ?? 0,
        });
      }

      return this.createActionResult(params.sessionId, tab);
    });
  }

  async wait(params: BrowserPageWaitParams): Promise<BrowserPageWaitResult> {
    return this.withPage(params.sessionId, async ({ tab, client }) => {
      if (typeof params.ms === 'number') {
        await new Promise(resolve => setTimeout(resolve, params.ms));
      }
      if (params.load) {
        await this.waitForLoadState(client, params.load);
      }
      return {
        ...this.createBaseResult(params.sessionId, tab),
        ...(typeof params.ms === 'number' ? { waitedMs: params.ms } : {}),
        ...(params.load ? { load: params.load } : {}),
      };
    });
  }

  private async withPage<TResult>(
    sessionId: string,
    run: (context: PageContext) => Promise<TResult>,
  ): Promise<TResult> {
    const activeTab = await this.sessionStore.getActiveTab({ sessionId });
    return withCdpClient(activeTab.tab.tabId, client =>
      run({
        tab: activeTab.tab,
        client,
      }),
    );
  }

  private createBaseResult(
    sessionId: string,
    tab: BrowserSessionTab,
  ): BrowserPageBaseResult {
    return {
      ok: true,
      sessionId,
      tabId: tab.tabId,
      page: getPageInfo(tab),
      coordinateSpace: COORDINATE_SPACE,
    };
  }

  private createActionResult(
    sessionId: string,
    tab: BrowserSessionTab,
    ref?: string,
  ): BrowserPageActionResult {
    return {
      ...this.createBaseResult(sessionId, tab),
      ...(ref ? { ref } : {}),
    };
  }

  private async evaluate<TResult>(
    client: CdpClient,
    expression: string,
  ): Promise<TResult> {
    const response = await client.send<RuntimeEvaluateResponse<TResult>>(
      'Runtime.evaluate',
      {
        expression,
        returnByValue: true,
        awaitPromise: false,
      },
    );
    if (response.exceptionDetails) {
      throw createPageOperationError(
        response.exceptionDetails.exception?.description ||
          response.exceptionDetails.text ||
          'Runtime evaluation failed',
      );
    }

    return response.result?.value as TResult;
  }

  private async runInsertText(
    sessionId: string,
    ref: string,
    mode: 'fill' | 'type',
    text: string,
  ): Promise<BrowserPageActionResult> {
    return this.withPage(sessionId, async ({ tab, client }) => {
      const resolved = await this.resolveRef(client, tab, ref, false);
      // 1) 聚焦元素并按 mode 设置选区：fill=全选(随后 insertText 替换)，type=光标移到末尾(追加)。
      const prep = await this.callFunctionOn<RuntimeStatus>(
        client,
        resolved.objectId,
        `function(mode) {
          if (typeof this.focus === 'function') this.focus();
          const isInput = ('value' in this) && typeof this.select === 'function';
          if (mode === 'fill') {
            if (isInput) {
              this.select();
            } else if (this.isContentEditable) {
              const range = document.createRange();
              range.selectNodeContents(this);
              const sel = window.getSelection();
              sel.removeAllRanges();
              sel.addRange(range);
            }
          } else if (isInput) {
            const len = (this.value || '').length;
            try { this.setSelectionRange(len, len); } catch (e) {}
          } else if (this.isContentEditable) {
            const range = document.createRange();
            range.selectNodeContents(this);
            range.collapse(false);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
          }
          return { ok: true };
        }`,
        [mode],
      );
      this.ensureRuntimeOk(prep, ref);
      // 2) 经 CDP Input.insertText 注入文本——走真实输入管线，触发 beforeinput/input(InputEvent)，
      //    CodeMirror/Lexical/React 受控组件都能识别；直接改 value/textContent 这些框架不认，
      //    会出现「框里看着有字、内部 model 仍为空」的发送失败。
      if (mode === 'fill' && text === '') {
        // insertText('') 不保证清空已选内容，单独发一次 Delete 删除选区。
        await client.send('Input.dispatchKeyEvent', {
          type: 'keyDown', key: 'Delete', code: 'Delete', windowsVirtualKeyCode: 46,
        });
        await client.send('Input.dispatchKeyEvent', {
          type: 'keyUp', key: 'Delete', code: 'Delete', windowsVirtualKeyCode: 46,
        });
      } else {
        await client.send('Input.insertText', { text });
      }
      return this.createActionResult(sessionId, tab, ref);
    });
  }

  private async runDomAction(
    sessionId: string,
    ref: string,
    action: 'fill' | 'type' | 'select' | 'scrollIntoView',
    value?: string,
  ): Promise<BrowserPageActionResult> {
    return this.withPage(sessionId, async ({ tab, client }) => {
      const resolved = await this.resolveRef(client, tab, ref, false);
      const result = await this.callFunctionOn<RuntimeStatus>(
        client,
        resolved.objectId,
        `function(action, value) {
          const dispatch = type => this.dispatchEvent(new Event(type, { bubbles: true }));
          if (action === 'scrollIntoView') {
            this.scrollIntoView({ block: 'center', inline: 'center', behavior: 'auto' });
            return { ok: true };
          }
          if (action === 'select') {
            this.value = value || '';
            dispatch('input');
            dispatch('change');
            return { ok: true };
          }
          if (typeof this.focus === 'function') this.focus();
          if (this.isContentEditable) {
            this.textContent = action === 'fill'
              ? value || ''
              : String(this.textContent || '') + (value || '');
            dispatch('input');
            return { ok: true };
          }
          if ('value' in this) {
            this.value = action === 'fill'
              ? value || ''
              : String(this.value || '') + (value || '');
            dispatch('input');
            dispatch('change');
            return { ok: true };
          }
          return { ok: false, error: 'UNSUPPORTED_ELEMENT' };
        }`,
        [action, value || ''],
      );
      this.ensureRuntimeOk(result, ref);
      return this.createActionResult(sessionId, tab, ref);
    });
  }

  private ensureRuntimeOk(result: RuntimeStatus, ref?: string): void {
    if (result.ok) {
      return;
    }

    if (result.error === 'REF_NOT_FOUND' && ref) {
      throw createRefNotFoundError(ref);
    }

    throw createPageOperationError(result.error || 'Page operation failed');
  }

  private async resolveRef(
    client: CdpClient,
    tab: BrowserSessionTab,
    ref: string,
    checkCovered: boolean,
  ): Promise<ResolvedRef> {
    const entry = this.refStore.get(tab.tabId, ref);
    if (!entry || typeof entry.backendNodeId !== 'number') {
      throw createRefNotFoundError(ref);
    }

    await client.send('DOM.scrollIntoViewIfNeeded', {
      backendNodeId: entry.backendNodeId,
    });
    const [boxModel, resolvedNode] = await Promise.all([
      client.send<DomGetBoxModelResult>('DOM.getBoxModel', {
        backendNodeId: entry.backendNodeId,
      }),
      client.send<DomResolveNodeResult>('DOM.resolveNode', {
        backendNodeId: entry.backendNodeId,
        objectGroup: 'ethan-browser',
      }),
    ]);
    const objectId = resolvedNode.object.objectId;
    if (!objectId) {
      throw createRefNotFoundError(ref);
    }
    const quad = boxModel.model.content || boxModel.model.border || [];
    const xs = [quad[0], quad[2], quad[4], quad[6]].filter(
      (value): value is number => typeof value === 'number',
    );
    const ys = [quad[1], quad[3], quad[5], quad[7]].filter(
      (value): value is number => typeof value === 'number',
    );
    const x = xs.length
      ? xs.reduce((sum, value) => sum + value, 0) / xs.length
      : DEFAULT_MOUSE_X;
    const y = ys.length
      ? ys.reduce((sum, value) => sum + value, 0) / ys.length
      : DEFAULT_MOUSE_Y;
    const box = {
      x: Math.round(Math.min(...xs, x)),
      y: Math.round(Math.min(...ys, y)),
      width: Math.round(boxModel.model.width),
      height: Math.round(boxModel.model.height),
    };
    const center = {
      x: Math.round(x),
      y: Math.round(y),
    };

    if (checkCovered) {
      await this.assertClickPointNotCovered(client, objectId, center);
    }

    return {
      entry,
      objectId,
      box,
      center,
    };
  }

  private async callFunctionOn<TResult>(
    client: CdpClient,
    objectId: string,
    functionDeclaration: string,
    args: unknown[] = [],
  ): Promise<TResult> {
    const response = await client.send<RuntimeCallFunctionResponse<TResult>>(
      'Runtime.callFunctionOn',
      {
        objectId,
        functionDeclaration,
        arguments: args.map(value => ({ value })),
        returnByValue: true,
        awaitPromise: true,
      },
    );
    if (response.exceptionDetails) {
      throw createPageOperationError(
        response.exceptionDetails.exception?.description ||
          response.exceptionDetails.text ||
          'Runtime call failed',
      );
    }
    return response.result?.value as TResult;
  }

  private async assertClickPointNotCovered(
    client: CdpClient,
    objectId: string,
    point: BrowserPagePoint,
  ): Promise<void> {
    const result = await this.callFunctionOn<RuntimeStatus>(
      client,
      objectId,
      `function(x, y) {
        const hit = document.elementFromPoint(x, y);
        if (!hit || hit === this || this.contains(hit) || hit.contains(this)) {
          return { ok: true };
        }
        const id = hit.id ? '#' + hit.id : '';
        const classes = typeof hit.className === 'string' && hit.className
          ? '.' + hit.className.trim().split(/\\s+/).slice(0, 3).join('.')
          : '';
        return {
          ok: false,
          error: 'covered by <' + hit.tagName.toLowerCase() + id + classes + '>'
        };
      }`,
      [point.x, point.y],
    );
    this.ensureRuntimeOk(result);
  }

  private dispatchMouseMove(
    client: CdpClient,
    x: number,
    y: number,
  ): Promise<void> {
    return client.send('Input.dispatchMouseEvent', {
      type: 'mouseMoved',
      x,
      y,
      button: 'none',
    });
  }

  private dispatchMouseButton(
    client: CdpClient,
    type: 'mousePressed' | 'mouseReleased',
    point: BrowserPagePoint,
    button: BrowserPageMouseButton | undefined,
  ): Promise<void> {
    return client.send('Input.dispatchMouseEvent', {
      type,
      x: point.x,
      y: point.y,
      button: getMouseButton(button),
      clickCount: 1,
    });
  }

  private async waitForLoadState(
    client: CdpClient,
    load: string,
  ): Promise<void> {
    const start = Date.now();
    while (Date.now() - start < READY_TIMEOUT_MS) {
      const ready = await this.evaluate<boolean>(
        client,
        createReadyStateExpression(load),
      );
      if (ready) {
        if (load === 'networkidle') {
          await new Promise(resolve =>
            setTimeout(resolve, NETWORK_IDLE_EXTRA_WAIT_MS),
          );
        }
        return;
      }
      await new Promise(resolve => setTimeout(resolve, READY_POLL_INTERVAL_MS));
    }

    throw createPageOperationError(`Timed out waiting for load state: ${load}`);
  }
}
