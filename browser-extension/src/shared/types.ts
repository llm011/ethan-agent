export interface DeviceConnectAgentOptions {
  command: string;
  cwd?: string;
  timeout?: number;
}

export type DeviceConnectAgentInput = string | DeviceConnectAgentOptions;

export interface DeviceRunBashOptions {
  command: string;
  cwd?: string;
  timeout?: number;
  allowed_paths?: string[];
  checked?: boolean;
}

export interface DeviceConnectAgentResult {
  exit_code: string;
  stdout: string;
  stderr: string;
  system_error: string;
}

export interface DeviceLoginState {
  isLogin: boolean;
  organizationId?: string;
}

export interface DeviceLocalFileAccessState {
  enabled: boolean;
}

export interface DeviceCommandNotice {
  commandId: string;
  deviceId?: string;
}

export type BrowserRpcClient = 'cli' | 'native-host';

export type JsonRpcId = string | number | null;

export interface JsonRpcRequest<TParams = unknown> {
  jsonrpc: '2.0';
  id?: JsonRpcId;
  method: string;
  params?: TParams;
}

export interface JsonRpcError<TData = unknown> {
  code: number;
  message: string;
  data?: TData;
}

export interface JsonRpcSuccessResponse<TResult = unknown> {
  jsonrpc: '2.0';
  id: JsonRpcId;
  result: TResult;
}

export interface JsonRpcErrorResponse<TData = unknown> {
  jsonrpc: '2.0';
  id: JsonRpcId;
  error: JsonRpcError<TData>;
}

export type JsonRpcResponse<TResult = unknown, TData = unknown> =
  | JsonRpcSuccessResponse<TResult>
  | JsonRpcErrorResponse<TData>;

export interface BrowserRpcAuthenticateParams {
  token: string;
  client: BrowserRpcClient;
  origin?: string;
  pid?: number;
}

export interface BrowserRpcAuthenticateResult {
  authenticated: true;
  client: BrowserRpcClient;
}

export interface BrowserSessionTab {
  tabId: number;
  windowId: number;
  groupId?: number;
  url?: string;
  title?: string;
  active?: boolean;
}

export type BrowserSessionListParams = Record<string, never>;

export interface BrowserSessionInfo {
  sessionId: string;
  title?: string;
  windowId: number;
  groupId: number;
  groupTitle: string;
  activeTabId?: number;
  tabs: BrowserSessionTab[];
}

export interface BrowserSessionCreateParams {
  url?: string;
  title?: string;
}

export interface BrowserSessionCreateResult {
  created: true;
  session: BrowserSessionInfo;
}

export interface BrowserSessionAttachCurrentParams {
  title?: string;
}

export interface BrowserSessionAttachCurrentResult {
  attached: true;
  session: BrowserSessionInfo;
  attachedTabId: number;
}

export interface BrowserSessionListResult {
  sessions: BrowserSessionInfo[];
}

export interface BrowserSessionRenameParams {
  sessionId: string;
  title: string;
}

export interface BrowserSessionRenameResult {
  renamed: true;
  session: BrowserSessionInfo;
}

export interface BrowserSessionReleaseParams {
  sessionId: string;
}

export interface BrowserSessionReleaseResult {
  released: true;
  sessionId: string;
}

export interface BrowserSessionCloseParams {
  sessionId: string;
}

export interface BrowserSessionCloseResult {
  closed: true;
  sessionId: string;
  closedTabIds: number[];
}

export interface BrowserTabOpenParams {
  sessionId: string;
  url: string;
  active?: boolean;
}

export interface BrowserTabOpenResult {
  opened: true;
  sessionId: string;
  tab: BrowserSessionTab;
}

export interface BrowserTabListParams {
  sessionId: string;
}

export interface BrowserTabListResult {
  sessionId: string;
  tabs: BrowserSessionTab[];
}

export type BrowserTabUserListParams = Record<string, never>;

export interface BrowserTabUserListResult {
  tabs: BrowserSessionTab[];
}

export interface BrowserTabAttachParams {
  sessionId: string;
  tabId: number;
}

export interface BrowserTabAttachResult {
  attached: true;
  sessionId: string;
  tab: BrowserSessionTab;
}

export interface BrowserTabActiveParams {
  sessionId: string;
}

export interface BrowserTabActiveResult {
  sessionId: string;
  tab: BrowserSessionTab;
}

export interface BrowserTabActivateParams {
  sessionId: string;
  tabId: number;
}

export interface BrowserTabActivateResult {
  activated: true;
  sessionId: string;
  tab: BrowserSessionTab;
}

export interface BrowserTabCloseParams {
  sessionId: string;
  tabId: number;
}

export interface BrowserTabCloseResult {
  closed: true;
  sessionId: string;
  closedTabId: number;
  sessionClosed?: boolean;
}

export type BrowserPageCoordinateSpace = 'viewport-css-pixel';

export type BrowserPageScreenshotFormat = 'png' | 'jpeg';

export type BrowserPageGetWhat =
  | 'text'
  | 'value'
  | 'html'
  | 'title'
  | 'url'
  | 'box';

export type BrowserPageScrollDirection = 'up' | 'down';

export type BrowserPageMouseAction = 'move' | 'down' | 'up' | 'wheel';

export type BrowserPageMouseButton = 'left' | 'middle' | 'right';

export type BrowserPageLoadState = 'load' | 'domcontentloaded' | 'networkidle';

export interface BrowserPagePoint {
  x: number;
  y: number;
}

export interface BrowserPageBox extends BrowserPagePoint {
  width: number;
  height: number;
}

export interface BrowserPageInfo {
  url?: string;
  title?: string;
}

export interface BrowserPageViewport {
  width: number;
  height: number;
  deviceScaleFactor: number;
}

export interface BrowserPageSnapshotElement {
  ref: string;
  role?: string;
  name?: string;
  text?: string;
  value?: string;
  tagName?: string;
  href?: string;
  depth?: number;
  parentRef?: string;
  backendNodeId?: number;
  frameId?: string;
  box?: BrowserPageBox;
  center?: BrowserPagePoint;
  actions: string[];
}

export interface BrowserPageSnapshotRef {
  ref: string;
  role: string;
  name?: string;
  nth?: number;
  backendNodeId?: number;
  frameId?: string;
}

export interface BrowserPageBaseParams {
  sessionId: string;
}

export interface BrowserPageRefParams extends BrowserPageBaseParams {
  ref: string;
}

export interface BrowserPageBaseResult {
  ok: true;
  sessionId: string;
  tabId: number;
  page: BrowserPageInfo;
  coordinateSpace: BrowserPageCoordinateSpace;
}

export interface BrowserPageSnapshotParams extends BrowserPageBaseParams {
  interactive?: boolean;
  compact?: boolean;
  cursor?: boolean;
  urls?: boolean;
  depth?: number;
  selector?: string;
}

export interface BrowserPageSnapshotResult extends BrowserPageBaseResult {
  snapshot: string;
  origin: string;
  refs: Record<string, BrowserPageSnapshotRef>;
  viewport: BrowserPageViewport;
  elements: BrowserPageSnapshotElement[];
}

export type BrowserPageClickParams = BrowserPageRefParams;

export type BrowserPageHoverParams = BrowserPageRefParams;

export type BrowserPageScrollIntoViewParams = BrowserPageRefParams;

export interface BrowserPageActionResult extends BrowserPageBaseResult {
  ref?: string;
}

export interface BrowserPageFillParams extends BrowserPageRefParams {
  text: string;
}

export interface BrowserPageTypeParams extends BrowserPageRefParams {
  text: string;
}

export interface BrowserPageSelectParams extends BrowserPageRefParams {
  value: string;
}

export interface BrowserPagePressParams extends BrowserPageBaseParams {
  key: string;
}

export interface BrowserPageScrollParams extends BrowserPageBaseParams {
  direction: BrowserPageScrollDirection;
  pixels: number;
}

export interface BrowserPageScreenshotParams extends BrowserPageBaseParams {
  fullPage?: boolean;
  format?: BrowserPageScreenshotFormat;
  quality?: number;
}

export interface BrowserPageScreenshotData {
  data: string;
  mimeType: string;
  format: BrowserPageScreenshotFormat;
  width: number;
  height: number;
  fullPage: boolean;
}

export interface BrowserPageScreenshotResult extends BrowserPageBaseResult {
  screenshot: BrowserPageScreenshotData;
  viewport: BrowserPageViewport;
}

export interface BrowserPageGetParams extends BrowserPageBaseParams {
  what: BrowserPageGetWhat;
  ref?: string;
}

export interface BrowserPageGetResult extends BrowserPageBaseResult {
  what: BrowserPageGetWhat;
  value?: string | number | boolean | null;
  box?: BrowserPageBox;
}

export interface BrowserPageMouseParams extends BrowserPageBaseParams {
  action: BrowserPageMouseAction;
  x?: number;
  y?: number;
  button?: BrowserPageMouseButton;
  deltaX?: number;
  deltaY?: number;
}

export interface BrowserPageWaitParams extends BrowserPageBaseParams {
  ms?: number;
  load?: BrowserPageLoadState;
}

export interface BrowserPageWaitResult extends BrowserPageBaseResult {
  waitedMs?: number;
  load?: BrowserPageLoadState;
}

export interface BrowserPageEvalParams extends BrowserPageBaseParams {
  script: string;
  awaitPromise?: boolean;
}

export interface BrowserPageEvalResult extends BrowserPageBaseResult {
  origin: string;
  result: unknown;
}

export interface BrowserExtensionTab {
  id?: number;
  windowId?: number;
  groupId?: number;
  url?: string;
  title?: string;
  active?: boolean;
}

export interface DesktopPushMessage {
  title?: string;
  body?: string;
  content?: string;
  text?: string;
  message?: string;
  url?: string;
  target_url?: string;
  targetUrl?: string;
  schema?: string;
  link?: string;
  token?: string;
  rid?: string | number;
  id?: string | number;
  rid64?: string | number;
  group_id?: string | number;
  group_id_str?: string;
  sender?: string | number;
  sender_id?: string | number;
  click_position?: string;
  [key: string]: unknown;
}

export interface DesktopPushRegisterResult {
  deviceId: string;
  registered: boolean;
  statusCode?: number;
  body?: string;
}

export interface DesktopPushShowResult {
  supported: boolean;
  shown: boolean;
  title?: string;
  body?: string;
  targetUrl?: string;
  reason?: string;
}

export interface UpdaterCheckForUpdatesOptions {
  uid: string;
}

export interface UpdaterDebugCheckForUpdatesOptions {
  uid?: string;
  buildId?: string;
  pid?: string;
  env?: string;
  baseURL?: string;
}

export interface UpdaterDebugCheckForUpdatesResult {
  url: string;
  response?: unknown;
  error?: string;
}

export interface DevtoolsDebugAPI {
  runBash: (input: DeviceRunBashOptions) => Promise<DeviceConnectAgentResult>;
  debugCheckForUpdates: (
    options: UpdaterDebugCheckForUpdatesOptions,
  ) => Promise<UpdaterDebugCheckForUpdatesResult>;
}

export interface Result<T = undefined> {
  code: number;
  message: string;
  data?: T;
}

export type ShellWhitelistResult = Result<string[]>;

export interface ElectronAPI {
  app: {
    getVersion: () => Promise<string>;
    getPlatform: () => Promise<string>;
    isPackaged: () => Promise<boolean>;
    getChannel: () => Promise<string>;
    getDeviceId?: () => Promise<string>;
    getEnvConfig: () => Promise<{
      enableTeaVerify: boolean;
      enableDevTools: boolean;
      headers: Record<string, string>;
    }>;
    setEnvHeaders: (headers: Record<string, string>) => Promise<void>;
  };
  shell: {
    openExternal: (url: string) => Promise<void>;
    getWhitelistCommands: () => Promise<ShellWhitelistResult>;
    addWhitelistCommand: (command: string) => Promise<ShellWhitelistResult>;
    removeWhitelistCommand: (command: string) => Promise<ShellWhitelistResult>;
  };
  window: {
    minimize: () => Promise<void>;
    maximize: () => Promise<void>;
    close: () => Promise<void>;
    isMaximized: () => Promise<boolean>;
    onMaximizedChange: (callback: (isMaximized: boolean) => void) => () => void;
  };
  updater: {
    rendererReady: () => Promise<void>;
    checkForUpdates: (options: UpdaterCheckForUpdatesOptions) => Promise<void>;
    quitAndInstall: () => Promise<void>;
    startDownload: () => Promise<void>;
    onUpdateAvailable: (
      callback: (info: { version: string; isForceUpdate: boolean }) => void,
    ) => () => void;
    onUpdateDownloaded: (
      callback: (info?: { version: string; isForceUpdate?: boolean }) => void,
    ) => () => void;
    onDownloadProgress: (
      callback: (progress: {
        percent: number;
        bytesPerSecond: number;
        transferred: number;
        total: number;
      }) => void,
    ) => () => void;
    onUpdateError: (
      callback: (error: { message: string }) => void,
    ) => () => void;
    onNoUpdate: (callback: () => void) => () => void;
    onDownloading: (callback: () => void) => () => void;
  };
  theme: {
    get: () => Promise<'dark' | 'light'>;
    set: (theme: 'dark' | 'light' | 'system') => Promise<void>;
    onChanged: (callback: (theme: 'dark' | 'light') => void) => () => void;
  };
  auth: {
    openLoginPopup: (url: string) => Promise<string>;
    openOAuthPopup: (url: string) => Promise<string>;
  };
  device: {
    notifyLoginState: (state: DeviceLoginState) => void;
    notifyLocalFileAccessState: (state: DeviceLocalFileAccessState) => void;
    dispatchCommand: (notice: DeviceCommandNotice) => void;
    connectAgent: (
      input: DeviceConnectAgentInput,
    ) => Promise<DeviceConnectAgentResult>;
  };
  imc: {
    registerDevice: (deviceId?: string) => Promise<DesktopPushRegisterResult>;
    showNotification: (
      message: DesktopPushMessage,
    ) => Promise<DesktopPushShowResult>;
    onNotificationClick: (callback: (targetUrl?: string) => void) => () => void;
  };
}
