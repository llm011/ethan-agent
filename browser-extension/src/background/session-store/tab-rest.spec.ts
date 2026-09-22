/**
 * 「让 tab 休息」的判据。
 *
 * 这层判错一次就是用户丢数据（discard 会丢掉填了一半的表单），所以每条
 * 保护规则都单独钉一个用例，而不是只测「正常路径能过」。
 */
import { describe, it, expect } from 'vitest';
import {
  decideRest,
  isProtectedUrl,
  shouldAutoRest,
  startOfLocalDay,
  type RestCandidateTab,
} from './tab-rest';

const NOON = new Date(2026, 8, 22, 12, 0, 0).getTime(); // 2026-09-22 12:00 本地
const START_OF_TODAY = startOfLocalDay(NOON);
const YESTERDAY = START_OF_TODAY - 60 * 60 * 1000; // 昨天 23:00

const tab = (over: Partial<RestCandidateTab> = {}): RestCandidateTab => ({
  id: 1,
  url: 'https://example.com/article',
  title: 'Article',
  active: false,
  ...over,
});

const decide = (
  over: Partial<RestCandidateTab> = {},
  opts: {
    openedAt?: number;
    live?: number[];
    cdp?: number[];
    /** 默认按自动模式（卡时间）；显式点名场景传 false。 */
    enforceRecency?: boolean;
  } = {},
) =>
  decideRest({
    tab: tab(over),
    openedAt: 'openedAt' in opts ? opts.openedAt : YESTERDAY,
    startOfToday: START_OF_TODAY,
    liveSessionTabIds: new Set(opts.live ?? []),
    cdpAttachedTabIds: new Set(opts.cdp ?? []),
    enforceRecency: opts.enforceRecency ?? true,
  });

describe('decideRest 保护名单', () => {
  it('昨天打开的普通标签可以休息', () => {
    expect(decide()).toBeNull();
  });

  it('当前正在看的标签不动（discard 会当场触发重新加载）', () => {
    expect(decide({ active: true })).toBe('active-tab');
  });

  it('出声的标签不动（可能在放视频或开会）', () => {
    expect(decide({ audible: true })).toBe('audible');
  });

  it('用户固定住的标签不动', () => {
    expect(decide({ pinned: true })).toBe('pinned');
  });

  it('已经休息过的标签不重复处理', () => {
    expect(decide({ discarded: true })).toBe('already-discarded');
  });

  it('显式关掉自动丢弃的标签不动', () => {
    expect(decide({ autoDiscardable: false })).toBe('auto-discard-disabled');
  });

  it('正被 Ethan 会话使用的标签不动（会打断自动化）', () => {
    expect(decide({}, { live: [1] })).toBe('live-session-tab');
  });

  it('挂着调试器的标签不动（discard 会中途 detach）', () => {
    expect(decide({}, { cdp: [1] })).toBe('live-session-tab');
  });

  it('今天打开的标签先不处理', () => {
    expect(decide({}, { openedAt: START_OF_TODAY + 1000 })).toBe('opened-today');
  });

  it('恰好零点打开的算今天（边界包含）', () => {
    expect(decide({}, { openedAt: START_OF_TODAY })).toBe('opened-today');
  });

  it('拿不到打开时间时按今天算（保守，不误伤）', () => {
    expect(decide({}, { openedAt: undefined })).toBe('opened-today');
  });

  it('没有 id 的标签不动', () => {
    expect(decide({ id: undefined })).toBe('protected-url');
  });
});

describe('enforceRecency（自动档才卡时间）', () => {
  it('显式点名时，今天打开的标签照样可以休息', () => {
    expect(
      decide({}, { openedAt: START_OF_TODAY + 1000, enforceRecency: false }),
    ).toBeNull();
  });

  it('显式点名时，拿不到打开时间也不拦（时间不是拒绝理由）', () => {
    expect(decide({}, { openedAt: undefined, enforceRecency: false })).toBeNull();
  });

  it('关掉时间判据不影响其他保护名单', () => {
    const opts = { openedAt: START_OF_TODAY + 1000, enforceRecency: false };
    expect(decide({ active: true }, opts)).toBe('active-tab');
    expect(decide({ audible: true }, opts)).toBe('audible');
    expect(decide({ pinned: true }, opts)).toBe('pinned');
    expect(decide({ url: 'chrome://settings' }, opts)).toBe('protected-url');
    expect(decide({}, { ...opts, cdp: [1] })).toBe('live-session-tab');
  });
});

describe('isProtectedUrl', () => {
  it.each([
    ['chrome://settings', true],
    ['chrome-extension://abc/popup.html', true],
    ['devtools://devtools/bundled/inspector.html', true],
    ['about:blank', true],
    ['file:///Users/x/notes.md', true],
    ['http://localhost:3000', true],
    ['http://127.0.0.1:8900', true],
    ['http://[::1]:8080', true],
    ['https://example.com', false],
    ['https://localhost.example.com', false],
    ['', false],
    [undefined, false],
  ])('%s → %s', (url, expected) => {
    expect(isProtectedUrl(url as string | undefined)).toBe(expected);
  });

  it('内部页统一走 protected-url', () => {
    expect(decide({ url: 'chrome://settings' })).toBe('protected-url');
    expect(decide({ url: 'http://localhost:5173' })).toBe('protected-url');
  });
});

describe('shouldAutoRest', () => {
  it('默认开启', () => {
    expect(shouldAutoRest(undefined)).toBe(true);
  });

  it('yesterday 档开启', () => {
    expect(shouldAutoRest('yesterday')).toBe(true);
  });

  it('off 档关闭（只有显式 op 才动手）', () => {
    expect(shouldAutoRest('off')).toBe(false);
  });
});

describe('startOfLocalDay', () => {
  it('取本地时区的零点，而不是 UTC 的', () => {
    const t = new Date(2026, 8, 22, 5, 30, 0).getTime();
    const s = new Date(startOfLocalDay(t));
    expect(s.getHours()).toBe(0);
    expect(s.getMinutes()).toBe(0);
    expect(s.getDate()).toBe(22);
  });
});
