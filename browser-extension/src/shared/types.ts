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
  /** 仅命令面板用：页面图标。agent 侧用不到，但不影响序列化。 */
  favIconUrl?: string;
}

export type BrowserSessionListParams = Record<string, never>;

export interface BrowserSessionInfo {
  sessionId: string;
  title?: string;
  windowId: number;
  groupId: number;
  groupTitle: string;
  color?: string;
  activeTabId?: number;
  tabs: BrowserSessionTab[];
}

export interface BrowserSessionCreateParams {
  url?: string;
  title?: string;
  color?: string;
  background?: boolean;
}

export interface BrowserSessionCreateResult {
  created: true;
  session: BrowserSessionInfo;
}

export interface BrowserSessionAttachCurrentParams {
  title?: string;
  color?: string;
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

export interface BrowserSessionUpdateParams {
  sessionId: string;
  title?: string;
  color?: string;
}

export interface BrowserSessionUpdateResult {
  updated: true;
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

/**
 * tabs.search：在当前浏览器已打开的 tab 里按关键词查找。
 *
 * 匹配在扩展侧完成（tab 数据本来就只在这里），不把全量 tab 列表送去 ethan
 * 再匹配——那等于把数据搬到计算处，而不是把计算搬到数据处。
 *
 * query 以空格切词，**任一命中即算匹配**（OR），按命中词数与字段权重打分排序：
 * title 命中权重高于 url 命中，完全匹配权重高于前缀/子串匹配。
 * 大小写不敏感。
 */
export interface BrowserTabSearchParams {
  /** 关键词，空格分隔。空串/未传表示不过滤，返回全部（等价 userList）。 */
  query?: string;
  /** 只返回用户当前活动的 tab，忽略 query。 */
  activeOnly?: boolean;
  /** 限制在某个窗口内搜索。不传=所有窗口。 */
  windowId?: number;
  /** 限制在某个 tab group 内搜索。不传=所有分组；传 0/-1 视为「不在任何分组」。 */
  groupId?: number;
  /** 最多返回多少条候选，默认 10，上限 50。 */
  limit?: number;
  /**
   * 是否把「今天已关闭的 tab」也算进候选（命令面板顶部的开关）。
   *
   * 只影响命令面板；agent 侧的 tabs.search 不传此参数，永远只搜开着的 tab。
   * 历史与当前已打开的按 URL 去重，不会重复出现。
   */
  includeClosed?: boolean;
}

/** 单个候选。tab 字段保持与 BrowserSessionTab 一致，外加命中说明。 */
export interface BrowserTabSearchMatch {
  tab: BrowserSessionTab;
  /** 命中的关键词（去重后，保持原顺序）。 */
  matchedKeywords: string[];
  /** 相关性分数，越大越相关。 */
  score: number;
  /** 命中在哪个字段：title / url / both。 */
  matchedIn: 'title' | 'url' | 'both';
  /** 该 tab 所属分组的标题（若能取到）。 */
  groupTitle?: string;
  /** 该 tab 所属分组的颜色（若能取到）。 */
  groupColor?: string;
}

export interface BrowserTabSearchResult {
  query: string;
  /** 参与搜索的 tab 总数（过滤 window/group 后）。 */
  scanned: number;
  /** 命中总数（可能多于 matches，因为 matches 受 limit 截断）。 */
  total: number;
  matches: BrowserTabSearchMatch[];
  /** 结果是否被 limit 截断。 */
  truncated: boolean;
}

export interface BrowserTabAttachParams {
  sessionId: string;
  tabId: number;
}

export interface BrowserTabAttachResult {
  attached: true;
  sessionId: string;
  tab: BrowserSessionTab;
  /** 若该 tab 此前被别的 session 占用，自动释放其控制权（保留 tab）后挂到本 session，则记录旧 sessionId。 */
  releasedFrom?: string;
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

export interface BrowserTabAttachBatchParams {
  sessionId: string;
  tabIds: number[];
}

export interface BrowserTabAttachBatchResult {
  attached: true;
  sessionId: string;
  tabs: BrowserSessionTab[];
  /** 被自动释放旧 session 控制权的 tab 列表（保留 tab 后挂到本 session）。 */
  releasedFrom?: { tabId: number; sessionId: string }[];
}

export interface BrowserTabDetachParams {
  sessionId: string;
  tabId: number;
}

export interface BrowserTabDetachResult {
  detached: true;
  sessionId: string;
  detachedTabId: number;
}

export interface BrowserTabMoveParams {
  sessionId: string;
  tabId: number;
  index: number;
}

export interface BrowserTabMoveResult {
  moved: true;
  sessionId: string;
  tab: BrowserSessionTab;
}

export type BrowserPageCoordinateSpace = 'viewport-css-pixel';

export type BrowserPageScreenshotFormat = 'png' | 'jpeg' | 'webp';

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
  bbox?: { x: number; y: number; w: number; h: number };
  overlay?: boolean;
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

export interface BrowserPageUploadParams extends BrowserPageBaseParams {
  ref: string;
  files: string[];
}

export interface BrowserPageEvalParams extends BrowserPageBaseParams {
  script: string;
  awaitPromise?: boolean;
}

export interface BrowserPageSavePdfParams extends BrowserPageBaseParams {
  paperFormat?: 'a4' | 'letter' | 'legal' | 'a3' | 'tabloid';
  landscape?: boolean;
  path?: string;
}

export interface BrowserPageSavePdfResult extends BrowserPageBaseResult {
  path: string;
  mimeType: 'application/pdf';
}

// ── Network monitoring ──────────────────────────────────────────────────────

export interface BrowserNetworkBaseParams {
  sessionId: string;
}

export interface BrowserNetworkDetailParams extends BrowserNetworkBaseParams {
  requestId: string;
}

export interface BrowserNetworkEntry {
  requestId: string;
  url: string;
  method: string;
  resourceType?: string;
  status?: number;
  mimeType?: string;
  requestTime?: number;
  responseTime?: number;
  encodedDataLength?: number;
  requestHeaders?: Record<string, string>;
  postData?: string;
  responseHeaders?: Record<string, string>;
  responseBody?: string;
  failed?: boolean;
  errorText?: string;
}

export interface BrowserNetworkStartResult {
  ok: true;
  sessionId: string;
}

export interface BrowserNetworkStopResult {
  ok: true;
  sessionId: string;
  count: number;
}

export interface BrowserNetworkListResult {
  ok: true;
  sessionId: string;
  requests: Omit<BrowserNetworkEntry, 'responseBody' | 'postData'>[];
}

export interface BrowserNetworkDetailResult {
  ok: true;
  sessionId: string;
  request: BrowserNetworkEntry | null;
}

export interface BrowserPageEvalResult extends BrowserPageBaseResult {
  origin: string;
  result: unknown;
}

// ── Tab Organize ──────────────────────────────────────────────────────────────

export type BrowserTabGroupColor =
  | 'grey' | 'blue' | 'red' | 'yellow' | 'green' | 'pink' | 'purple' | 'cyan' | 'orange';

export type BrowserTabOrganizeOp =
  | { op: 'close'; tabs: number[] }
  | { op: 'group'; title: string; tabs: number[]; color?: BrowserTabGroupColor; groupId?: number }
  | { op: 'ungroup'; tabs: number[] }
  | { op: 'ungroup_all'; groupId?: number; title?: string }
  | { op: 'rest'; tabs: number[] }
  | { op: 'rest_group'; groupId?: number; title?: string }
  | { op: 'rest_auto'; groupId?: number; title?: string };

export interface BrowserTabOrganizeParams {
  ops: BrowserTabOrganizeOp[];
  /**
   * 整理完成后是否折叠受影响的 TabGroup。默认 'auto'。
   *
   * 'auto' 折叠所有本次涉及的组,但**跳过包含当前活跃 tab 的组** ——
   * 折叠用户正在用的那一组会把它当场收起来,打断操作。
   * 'none' 完全不折,true/false 为强制全折/全不折。
   */
  collapse?: 'auto' | 'none' | boolean;
  /**
   * 「按时间自动休息」的档位。默认 `'yesterday'`（开启）：昨天及更早打开、
   * 今天没碰过、且不在保护名单里的 tab，会被 discard。
   *
   * `'off'` 完全关闭自动休息 —— 此时只有显式的 `rest` / `rest_group` op 才动手。
   * 扩展设置页有对应的开关，用户可随时关掉。
   */
  restMode?: BrowserTabRestMode;
}

/**
 * 让 tab「休息」（discard）：释放渲染进程内存，标题/位置/分组都留在标签栏，
 * 点开时 Chrome 自动按原 URL 重新加载。
 *
 * 只对明确的 op（'rest' / 'rest_group'）生效；'rest_auto' 还要看下面的开关
 * 与自动判据。
 */
export type BrowserTabRestMode = 'off' | 'yesterday';

/** `applied` 里与「休息」相关的结果。 */
export interface BrowserTabOrganizeRestApplied {
  /** 实际被 discard 的 tab。 */
  rested: number[];
  /**
   * 明确评估过、但按规则决定不动的 tab，附原因（可预期的）。
   * 与 restedFailed 分开，调用方才能区分「按设计没动」和「动手失败了」。
   */
  restSkipped: { tabId: number; reason: string }[];
  /** 尝试 discard 但失败的 tab（tab 已消失、discard API 报错等）。 */
  restFailed: { tabId: number; reason: string }[];
}

export interface BrowserTabOrganizeApplied {
  closed: number[];
  grouped: { title: string; groupId: number; tabs: number[] }[];
  ungrouped: number[];
  /** 实际折叠成功的组。 */
  collapsed: number[];
  /**
   * 有意没折的组，且原因是**可预期的**：'auto' 模式下含活跃 tab。
   * 与 collapseFailed 分开，调用方才能区分「按设计没折」和「折失败了」。
   */
  collapseSkipped: number[];
  /** 尝试折叠但失败的组（组已消失、tabGroups API 报错）。 */
  collapseFailed: number[];
  /** 被 discard 的 tab、按规则跳过的、以及动手失败的。 */
  rest: BrowserTabOrganizeRestApplied;
}

export interface BrowserTabOrganizeResult {
  organized: true;
  applied: BrowserTabOrganizeApplied;
  skipped?: { tabId: number; reason: string }[];
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
