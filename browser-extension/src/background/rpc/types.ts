import type {
  BrowserPageActionResult,
  BrowserPageClickParams,
  BrowserPageEvalParams,
  BrowserPageEvalResult,
  BrowserPageFillParams,
  BrowserPageGetParams,
  BrowserPageGetResult,
  BrowserPageHoverParams,
  BrowserPageMouseButton,
  BrowserPageMouseParams,
  BrowserPagePressParams,
  BrowserPageScreenshotFormat,
  BrowserPageScreenshotParams,
  BrowserPageScreenshotResult,
  BrowserPageScrollDirection,
  BrowserPageScrollIntoViewParams,
  BrowserPageScrollParams,
  BrowserPageSelectParams,
  BrowserPageSnapshotParams,
  BrowserPageSnapshotResult,
  BrowserPageTypeParams,
  BrowserPageUploadParams,
  BrowserPageSavePdfParams,
  BrowserPageSavePdfResult,
  BrowserPageWaitParams,
  BrowserPageWaitResult,
  BrowserNetworkStartResult,
  BrowserNetworkStopResult,
  BrowserNetworkListResult,
  BrowserNetworkDetailResult,
  BrowserSessionAttachCurrentParams,
  BrowserSessionAttachCurrentResult,
  BrowserSessionCloseParams,
  BrowserSessionCloseResult,
  BrowserSessionCreateParams,
  BrowserSessionCreateResult,
  BrowserSessionListResult,
  BrowserSessionRenameParams,
  BrowserSessionRenameResult,
  BrowserSessionReleaseParams,
  BrowserSessionReleaseResult,
  BrowserTabActivateParams,
  BrowserTabActivateResult,
  BrowserTabActiveParams,
  BrowserTabActiveResult,
  BrowserTabAttachParams,
  BrowserTabAttachResult,
  BrowserTabCloseParams,
  BrowserTabCloseResult,
  BrowserTabListParams,
  BrowserTabListResult,
  BrowserTabOpenParams,
  BrowserTabOpenResult,
  BrowserTabUserListResult,
  BrowserTabAttachBatchParams,
  BrowserTabAttachBatchResult,
  BrowserTabDetachParams,
  BrowserTabDetachResult,
  BrowserTabMoveParams,
  BrowserTabMoveResult,
  BrowserSessionUpdateParams,
  BrowserSessionUpdateResult,
} from '../../shared';
import { BROWSER_RPC_METHODS } from '../../shared';

export interface BrowserRequestDependencies {
  createSession: (
    params: BrowserSessionCreateParams,
  ) => Promise<BrowserSessionCreateResult>;
  attachCurrentSession: (
    params: BrowserSessionAttachCurrentParams,
  ) => Promise<BrowserSessionAttachCurrentResult>;
  listSessions: () => Promise<BrowserSessionListResult>;
  renameSession: (
    params: BrowserSessionRenameParams,
  ) => Promise<BrowserSessionRenameResult>;
  releaseSession: (
    params: BrowserSessionReleaseParams,
  ) => Promise<BrowserSessionReleaseResult>;
  closeSession: (
    params: BrowserSessionCloseParams,
  ) => Promise<BrowserSessionCloseResult>;
  openTab: (params: BrowserTabOpenParams) => Promise<BrowserTabOpenResult>;
  listTabs: (params: BrowserTabListParams) => Promise<BrowserTabListResult>;
  listUserTabs: () => Promise<BrowserTabUserListResult>;
  attachTab: (
    params: BrowserTabAttachParams,
  ) => Promise<BrowserTabAttachResult>;
  getActiveTab: (
    params: BrowserTabActiveParams,
  ) => Promise<BrowserTabActiveResult>;
  activateTab: (
    params: BrowserTabActivateParams,
  ) => Promise<BrowserTabActivateResult>;
  closeTab: (params: BrowserTabCloseParams) => Promise<BrowserTabCloseResult>;
  attachBatchTabs: (
    params: BrowserTabAttachBatchParams,
  ) => Promise<BrowserTabAttachBatchResult>;
  detachTab: (
    params: BrowserTabDetachParams,
  ) => Promise<BrowserTabDetachResult>;
  moveTab: (
    params: BrowserTabMoveParams,
  ) => Promise<BrowserTabMoveResult>;
  updateSession: (
    params: BrowserSessionUpdateParams,
  ) => Promise<BrowserSessionUpdateResult>;
  pageSnapshot: (
    params: BrowserPageSnapshotParams,
  ) => Promise<BrowserPageSnapshotResult>;
  pageClick: (
    params: BrowserPageClickParams,
  ) => Promise<BrowserPageActionResult>;
  pageFill: (params: BrowserPageFillParams) => Promise<BrowserPageActionResult>;
  pageType: (params: BrowserPageTypeParams) => Promise<BrowserPageActionResult>;
  pagePress: (
    params: BrowserPagePressParams,
  ) => Promise<BrowserPageActionResult>;
  pageHover: (
    params: BrowserPageHoverParams,
  ) => Promise<BrowserPageActionResult>;
  pageSelect: (
    params: BrowserPageSelectParams,
  ) => Promise<BrowserPageActionResult>;
  pageScroll: (
    params: BrowserPageScrollParams,
  ) => Promise<BrowserPageActionResult>;
  pageScrollIntoView: (
    params: BrowserPageScrollIntoViewParams,
  ) => Promise<BrowserPageActionResult>;
  pageScreenshot: (
    params: BrowserPageScreenshotParams,
  ) => Promise<BrowserPageScreenshotResult>;
  pageGet: (params: BrowserPageGetParams) => Promise<BrowserPageGetResult>;
  pageMouse: (
    params: BrowserPageMouseParams,
  ) => Promise<BrowserPageActionResult>;
  pageWait: (params: BrowserPageWaitParams) => Promise<BrowserPageWaitResult>;
  pageEval: (params: BrowserPageEvalParams) => Promise<BrowserPageEvalResult>;
  pageUpload: (params: BrowserPageUploadParams) => Promise<BrowserPageActionResult>;
  pageSavePdf: (params: BrowserPageSavePdfParams) => Promise<BrowserPageSavePdfResult>;
  networkStart: (params: { sessionId: string }) => Promise<BrowserNetworkStartResult>;
  networkStop: (params: { sessionId: string }) => Promise<BrowserNetworkStopResult>;
  networkList: (params: { sessionId: string; filter?: string }) => Promise<BrowserNetworkListResult>;
  networkDetail: (params: { sessionId: string; requestId: string }) => Promise<BrowserNetworkDetailResult>;
}

export const ALLOWED_METHODS = new Set<string>([
  BROWSER_RPC_METHODS.sessionsCreate,
  BROWSER_RPC_METHODS.sessionsAttachCurrent,
  BROWSER_RPC_METHODS.sessionsList,
  BROWSER_RPC_METHODS.sessionsRename,
  BROWSER_RPC_METHODS.sessionsRelease,
  BROWSER_RPC_METHODS.sessionsClose,
  BROWSER_RPC_METHODS.tabsOpen,
  BROWSER_RPC_METHODS.tabsList,
  BROWSER_RPC_METHODS.tabsUserList,
  BROWSER_RPC_METHODS.tabsAttach,
  BROWSER_RPC_METHODS.tabsActive,
  BROWSER_RPC_METHODS.tabsActivate,
  BROWSER_RPC_METHODS.tabsClose,
  BROWSER_RPC_METHODS.tabsAttachBatch,
  BROWSER_RPC_METHODS.tabsDetach,
  BROWSER_RPC_METHODS.tabsMove,
  BROWSER_RPC_METHODS.sessionsUpdate,
  BROWSER_RPC_METHODS.pagesSnapshot,
  BROWSER_RPC_METHODS.pagesClick,
  BROWSER_RPC_METHODS.pagesFill,
  BROWSER_RPC_METHODS.pagesType,
  BROWSER_RPC_METHODS.pagesPress,
  BROWSER_RPC_METHODS.pagesHover,
  BROWSER_RPC_METHODS.pagesSelect,
  BROWSER_RPC_METHODS.pagesScroll,
  BROWSER_RPC_METHODS.pagesScrollIntoView,
  BROWSER_RPC_METHODS.pagesScreenshot,
  BROWSER_RPC_METHODS.pagesGet,
  BROWSER_RPC_METHODS.pagesMouse,
  BROWSER_RPC_METHODS.pagesWait,
  BROWSER_RPC_METHODS.pagesEval,
  BROWSER_RPC_METHODS.pagesUpload,
  BROWSER_RPC_METHODS.pagesSavePdf,
  BROWSER_RPC_METHODS.networkStart,
  BROWSER_RPC_METHODS.networkStop,
  BROWSER_RPC_METHODS.networkList,
  BROWSER_RPC_METHODS.networkDetail,
]);
