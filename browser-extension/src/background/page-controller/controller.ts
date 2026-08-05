import type {
  BrowserPageActionResult,
  BrowserPageBaseResult,
  BrowserPageEvalParams,
  BrowserPageEvalResult,
  BrowserPageGetParams,
  BrowserPageGetResult,
  BrowserPageMouseParams,
  BrowserPagePoint,
  BrowserPagePressParams,
  BrowserPageSavePdfParams,
  BrowserPageSavePdfResult,
  BrowserPageScreenshotParams,
  BrowserPageScreenshotResult,
  BrowserPageSnapshotParams,
  BrowserPageSnapshotResult,
  BrowserPageUploadParams,
  BrowserPageWaitParams,
  BrowserPageWaitResult,
  BrowserSessionTab,
} from '../../shared';
import type { BrowserSessionStore } from '../session-store';
import { withCdpClient } from '../cdp-client';
import { BrowserPageRefStore } from '../ref-store';
import type { PageContext, PageControllerContext } from './types';
import { COORDINATE_SPACE } from './constants';
import { getPageInfo } from './key-mapping';
import {
  snapshotAction,
  getAction,
  evalAction,
  scrollAction,
  waitAction,
} from './navigation-actions';
import {
  clickAction,
  hoverAction,
  fillAction,
  typeAction,
  selectAction,
  scrollIntoViewAction,
  pressAction,
  uploadAction,
} from './interaction-actions';
import {
  screenshotAction,
  savePdfAction,
  mouseAction,
} from './capture-actions';

export class BrowserPageController implements PageControllerContext {
  readonly lastMousePositionByTab = new Map<number, BrowserPagePoint>();

  readonly refStore = new BrowserPageRefStore();

  constructor(readonly sessionStore: BrowserSessionStore) {}

  async snapshot(
    params: BrowserPageSnapshotParams,
  ): Promise<BrowserPageSnapshotResult> {
    return snapshotAction(this, params);
  }

  async click(params: {
    sessionId: string;
    ref: string;
  }): Promise<BrowserPageActionResult> {
    return clickAction(this, params);
  }

  async hover(params: {
    sessionId: string;
    ref: string;
  }): Promise<BrowserPageActionResult> {
    return hoverAction(this, params);
  }

  async fill(params: {
    sessionId: string;
    ref: string;
    text: string;
  }): Promise<BrowserPageActionResult> {
    return fillAction(this, params);
  }

  async type(params: {
    sessionId: string;
    ref: string;
    text: string;
  }): Promise<BrowserPageActionResult> {
    return typeAction(this, params);
  }

  async select(params: {
    sessionId: string;
    ref: string;
    value: string;
  }): Promise<BrowserPageActionResult> {
    return selectAction(this, params);
  }

  async scrollIntoView(params: {
    sessionId: string;
    ref: string;
  }): Promise<BrowserPageActionResult> {
    return scrollIntoViewAction(this, params);
  }

  async press(
    params: BrowserPagePressParams,
  ): Promise<BrowserPageActionResult> {
    return pressAction(this, params);
  }

  async scroll(params: {
    sessionId: string;
    direction: 'up' | 'down';
    pixels: number;
  }): Promise<BrowserPageActionResult> {
    return scrollAction(this, params);
  }

  async screenshot(
    params: BrowserPageScreenshotParams,
  ): Promise<BrowserPageScreenshotResult> {
    return screenshotAction(this, params);
  }

  async get(params: BrowserPageGetParams): Promise<BrowserPageGetResult> {
    return getAction(this, params);
  }

  async eval(params: BrowserPageEvalParams): Promise<BrowserPageEvalResult> {
    return evalAction(this, params);
  }

  async upload(
    params: BrowserPageUploadParams,
  ): Promise<BrowserPageActionResult> {
    return uploadAction(this, params);
  }

  async savePdf(
    params: BrowserPageSavePdfParams,
  ): Promise<BrowserPageSavePdfResult> {
    return savePdfAction(this, params);
  }

  async mouse(
    params: BrowserPageMouseParams,
  ): Promise<BrowserPageActionResult> {
    return mouseAction(this, params);
  }

  async wait(
    params: BrowserPageWaitParams,
  ): Promise<BrowserPageWaitResult> {
    return waitAction(this, params);
  }

  async withPage<TResult>(
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

  createBaseResult(
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

  createActionResult(
    sessionId: string,
    tab: BrowserSessionTab,
    ref?: string,
  ): BrowserPageActionResult {
    return {
      ...this.createBaseResult(sessionId, tab),
      ...(ref ? { ref } : {}),
    };
  }
}
