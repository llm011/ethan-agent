// @ts-nocheck
/* eslint-disable */

  const PANEL_ID = '__ethan_reading_panel';
  const READER_ID = '__ethan_reading_reader';
  const CONTENT_ID = '__ethan_reading_content';
  const TOOLBAR_ID = '__ethan_reading_toolbar';
  const FORMAT_BAR_ID = '__ethan_reading_format_bar';
  const PROGRESS_ID = '__ethan_reading_progress';
  const REENTER_ID = '__ethan_reading_reenter';
  const EXPAND_TAB_ID = '__ethan_reading_expand_tab';
  const DELETE_POPUP_ID = '__ethan_reading_delete_popup';
  const Z_READER = 2147483640;
  const Z_PANEL = 2147483645;
  const Z_TOOLBAR = 2147483647;
  const Z_FORMAT_BAR = 2147483643;
  const Z_PROGRESS = 2147483646;
  const Z_REENTER = 2147483620;

  let active = false;
  let contentEl: HTMLElement | null = null;
  let cleanedText = '';
  let summaryText = '';
  let currentUrl = location.href;
  let scrollHandler: (() => void) | null = null;
  let panelCollapsed = false;
  let activeChatHandlers: Set<(msg: any) => void> = new Set();
  let saveTimer: number | null = null;
  let refreshTimer: number | null = null;
  // 内联多轮对话：每次进入阅读模式生成一个 session（服务端按此维护上下文），
  // 首轮把正文塞进 prompt，后续轮只发问题、历史由服务端拼。
  let chatSessionId = '';
  let chatBusy = false;
  // 代码块高亮注入 span 时会触发 input 事件，用此标志抑制 saveContent / scheduleRefresh
  let suppressInput = false;
