import type {
  BrowserPageActionResult,
  BrowserPageMouseParams,
  BrowserPageSavePdfParams,
  BrowserPageSavePdfResult,
  BrowserPageScreenshotParams,
  BrowserPageScreenshotResult,
} from '../../shared';
import { createViewportExpression } from '../page-runtime';
import type {
  LayoutMetricsResult,
  PageControllerContext,
  ScreenshotCaptureResult,
  ViewportRuntimeResult,
} from './types';
import {
  dispatchMouseButton,
  dispatchMouseMove,
  evaluate,
} from './cdp-helpers';
import {
  DEFAULT_MOUSE_X,
  DEFAULT_MOUSE_Y,
  DEFAULT_SCREENSHOT_FORMAT,
} from './constants';

export async function screenshotAction(
  ctx: PageControllerContext,
  params: BrowserPageScreenshotParams,
): Promise<BrowserPageScreenshotResult> {
  return ctx.withPage(params.sessionId, async ({ tab, client }) => {
    await client.send('Page.enable');
    const viewport = await evaluate<ViewportRuntimeResult>(
      client,
      createViewportExpression(),
    );
    const format = params.format || DEFAULT_SCREENSHOT_FORMAT;
    const screenshotParams: Record<string, unknown> = {
      format,
      fromSurface: true,
      captureBeyondViewport: Boolean(params.fullPage),
      ...((format === 'jpeg' || format === 'webp') && typeof params.quality === 'number'
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
      ...ctx.createBaseResult(params.sessionId, tab),
      screenshot: {
        data: captured.data,
        mimeType: format === 'jpeg' ? 'image/jpeg' : format === 'webp' ? 'image/webp' : 'image/png',
        format,
        width,
        height,
        fullPage: Boolean(params.fullPage),
      },
      viewport,
    };
  });
}

export async function savePdfAction(
  ctx: PageControllerContext,
  params: BrowserPageSavePdfParams,
): Promise<BrowserPageSavePdfResult> {
  return ctx.withPage(params.sessionId, async ({ tab, client }) => {
    await client.send('Page.enable');
    const paperFormats: Record<string, { width: number; height: number }> = {
      a4: { width: 8.27, height: 11.69 },
      letter: { width: 8.5, height: 11 },
      legal: { width: 8.5, height: 14 },
      a3: { width: 11.69, height: 16.54 },
      tabloid: { width: 11, height: 17 },
    };
    const fmt = paperFormats[params.paperFormat || 'a4'] || paperFormats.a4;
    const pdfResult = await client.send<{ data: string }>('Page.printToPDF', {
      landscape: params.landscape ?? false,
      paperWidth: fmt.width,
      paperHeight: fmt.height,
      printBackground: true,
      preferCSSPageSize: false,
    });
    return {
      ...ctx.createBaseResult(params.sessionId, tab),
      data: pdfResult.data,
      path: params.path || '',
      mimeType: 'application/pdf' as const,
    };
  });
}

export async function mouseAction(
  ctx: PageControllerContext,
  params: BrowserPageMouseParams,
): Promise<BrowserPageActionResult> {
  return ctx.withPage(params.sessionId, async ({ tab, client }) => {
    const current = ctx.lastMousePositionByTab.get(tab.tabId) || {
      x: DEFAULT_MOUSE_X,
      y: DEFAULT_MOUSE_Y,
    };
    if (params.action === 'move') {
      const point = {
        x: params.x ?? current.x,
        y: params.y ?? current.y,
      };
      await dispatchMouseMove(client, point.x, point.y);
      ctx.lastMousePositionByTab.set(tab.tabId, point);
    } else if (params.action === 'down') {
      await dispatchMouseButton(
        client,
        'mousePressed',
        current,
        params.button,
      );
    } else if (params.action === 'up') {
      await dispatchMouseButton(
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

    return ctx.createActionResult(params.sessionId, tab);
  });
}
