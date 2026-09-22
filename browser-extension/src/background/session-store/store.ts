import type {
  BrowserTabActivateParams,
  BrowserTabActivateResult,
  BrowserTabActiveParams,
  BrowserTabActiveResult,
  BrowserTabListParams,
  BrowserTabListResult,
  BrowserTabMoveParams,
  BrowserTabMoveResult,
  BrowserTabOpenParams,
  BrowserTabOpenResult,
  BrowserTabUserListResult,
  BrowserTabOrganizeParams,
  BrowserTabOrganizeResult,
  BrowserTabOrganizeApplied,
} from '../../shared';
import { createSessionNotFoundError, BrowserExtensionRpcError } from './errors';
import { BROWSER_RPC_ERROR_CODE } from '../../shared';
import { BrowserSessionStoreTabs } from './store-tabs';
import { getTabId, toSessionTab } from './utils';
import { TAB_GROUP_ID_NONE } from './constants';
import {
  createTab,
  discardTab,
  getTab,
  groupTabs,
  moveTabToIndex,
  moveTabToWindow,
  queryGroups,
  queryTabs,
  removeTabs,
  ungroupTabs,
  updateGroupFull,
  updateTab,
} from './chrome-api';
import {
  decideRest,
  shouldAutoRest,
  startOfLocalDay,
  type RestSkipReason,
} from './tab-rest';
import { getTabOpenedAt } from './tab-open-times';

export class BrowserSessionStore extends BrowserSessionStoreTabs {
  async openTab(params: BrowserTabOpenParams): Promise<BrowserTabOpenResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);

    const tab = await createTab({
      url: params.url,
      active: params.active ?? false,
      windowId: session.windowId,
    });
    const tabId = getTabId(tab, 'Cannot open a tab without tab id');
    await groupTabs([tabId], session.groupId);

    session.activeTabId = tabId;
    session.updatedAt = Date.now();

    const normalizedTab = await getTab(tabId);
    await this.persist();
    return {
      opened: true,
      sessionId: params.sessionId,
      tab: toSessionTab(normalizedTab),
    };
  }

  async listTabs(params: BrowserTabListParams): Promise<BrowserTabListResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    const info = await this.reconcileSessionOrThrow(session);
    await this.persist();

    return {
      sessionId: params.sessionId,
      tabs: info.tabs,
    };
  }

  async listUserTabs(): Promise<BrowserTabUserListResult> {
    const tabs = await queryTabs({});
    return {
      tabs: tabs.map(toSessionTab),
    };
  }

  async getActiveTab(
    params: BrowserTabActiveParams,
  ): Promise<BrowserTabActiveResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    const info = await this.reconcileSessionOrThrow(session);
    const tab =
      info.tabs.find(item => item.tabId === info.activeTabId) ?? info.tabs[0];
    if (!tab) {
      throw createSessionNotFoundError(params.sessionId);
    }

    await this.persist();
    return {
      sessionId: params.sessionId,
      tab,
    };
  }

  async activateTab(
    params: BrowserTabActivateParams,
  ): Promise<BrowserTabActivateResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);
    await this.assertTabInSessionGroup(session, params.tabId);
    const tab = await updateTab(params.tabId, { active: true });

    session.activeTabId = params.tabId;
    session.updatedAt = Date.now();
    await this.persist();

    return {
      activated: true,
      sessionId: params.sessionId,
      tab: toSessionTab(tab),
    };
  }

  async moveTab(
    params: BrowserTabMoveParams,
  ): Promise<BrowserTabMoveResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);
    await this.assertTabInSessionGroup(session, params.tabId);

    // params.index 是组内相对索引，需转为 window 下的绝对索引
    const tabsInGroup = await queryTabs({
      groupId: session.groupId,
      windowId: session.windowId,
    });
    tabsInGroup.sort((a, b) => (a.index ?? 0) - (b.index ?? 0));
    const groupStartIndex = tabsInGroup.length > 0 ? (tabsInGroup[0].index ?? 0) : 0;
    const absoluteIndex = groupStartIndex + Math.max(0, Math.min(params.index, tabsInGroup.length - 1));
    const movedTab = await moveTabToIndex(params.tabId, absoluteIndex);
    session.updatedAt = Date.now();
    await this.persist();

    return {
      moved: true,
      sessionId: params.sessionId,
      tab: toSessionTab(movedTab),
    };
  }

  async handleTabRemoved(_tabId: number): Promise<void> {
    await this.ensureLoaded();
    for (const session of Array.from(this.sessions.values())) {
      await this.reconcileSession(session);
    }
    await this.persist();
  }

  async organizeTabs(
    params: BrowserTabOrganizeParams,
  ): Promise<BrowserTabOrganizeResult> {
    const applied: BrowserTabOrganizeApplied = {
      closed: [],
      grouped: [],
      ungrouped: [],
      collapsed: [],
      collapseSkipped: [],
      collapseFailed: [],
      rest: { rested: [], restSkipped: [], restFailed: [] },
    };
    const skipped: { tabId: number; reason: string }[] = [];
    // 本次 touch 到的所有 group，收尾时统一折叠（去重）
    const touchedGroupIds = new Set<number>();

    for (const op of params.ops) {
      if (op.op === 'close') {
        const toClose: number[] = [];
        for (const tabId of op.tabs) {
          try {
            await getTab(tabId);
            toClose.push(tabId);
          } catch {
            skipped.push({ tabId, reason: 'tab not found' });
          }
        }
        if (toClose.length) {
          await removeTabs(toClose);
          applied.closed.push(...toClose);
          // 批量关闭后只调一次 handleTabRemoved 让 session 账本自愈，避免 N 次全量 reconcile
          await this.handleTabRemoved(toClose[0]);
        }
      } else if (op.op === 'group') {
        const validTabs: chrome.tabs.Tab[] = [];
        for (const tabId of op.tabs) {
          try {
            validTabs.push(await getTab(tabId));
          } catch {
            skipped.push({ tabId, reason: 'tab not found' });
          }
        }
        if (!validTabs.length) continue;

        // Determine target window: use first tab's window
        const targetWindowId = validTabs[0].windowId!;

        // Move cross-window tabs first
        const tabIds: number[] = [];
        for (const tab of validTabs) {
          let tid = tab.id!;
          if (tab.windowId !== targetWindowId) {
            const moved = await moveTabToWindow(tid, targetWindowId);
            tid = moved.id!;
          }
          tabIds.push(tid);
        }

        // Find or create group
        let groupId: number;
        if (op.groupId != null) {
          groupId = op.groupId;
          await groupTabs(tabIds, groupId);
          if (op.color) {
            await updateGroupFull(groupId, { color: op.color as chrome.tabGroups.ColorEnum });
          }
        } else {
          // Search for existing group by title in the target window
          const existing = await queryGroups({ title: op.title, windowId: targetWindowId });
          if (existing.length) {
            groupId = existing[0].id;
            await groupTabs(tabIds, groupId);
            if (op.color) {
              await updateGroupFull(groupId, { color: op.color as chrome.tabGroups.ColorEnum });
            }
          } else {
            groupId = await groupTabs(tabIds);
            await updateGroupFull(groupId, {
              title: op.title,
              ...(op.color ? { color: op.color as chrome.tabGroups.ColorEnum } : {}),
            });
          }
        }

        applied.grouped.push({ title: op.title, groupId, tabs: tabIds });
        touchedGroupIds.add(groupId);
      } else if (op.op === 'ungroup') {
        const validIds: number[] = [];
        for (const tabId of op.tabs) {
          try {
            const t = await getTab(tabId);
            if (typeof t.groupId === 'number' && t.groupId !== TAB_GROUP_ID_NONE) {
              validIds.push(tabId);
            }
            // already ungrouped → skip silently (desired state already reached)
          } catch {
            skipped.push({ tabId, reason: 'tab not found' });
          }
        }
        if (validIds.length) {
          await ungroupTabs(validIds);
          applied.ungrouped.push(...validIds);
        }
      } else if ((op as { op: string }).op === 'ungroup_all') {
        const ungroup_op = op as { op: 'ungroup_all'; groupId?: number; title?: string };
        let gid: number | undefined = ungroup_op.groupId;
        if (gid == null && ungroup_op.title) {
          const groups = await queryGroups({ title: ungroup_op.title });
          if (groups.length > 1) {
            // 多个窗口里存在同名组，无法确定目标，要求用 groupId 精确指定
            throw new BrowserExtensionRpcError(
              BROWSER_RPC_ERROR_CODE.invalidParams,
              `ungroup_all: title "${ungroup_op.title}" matches ${groups.length} groups across windows; use groupId to specify which one`,
            );
          }
          gid = groups[0]?.id;
        }
        if (gid == null) continue;
        // group 已不存在 → 视为已经达到「没有这个组」的目标状态，静默跳过
        const known = await queryGroups({});
        if (!known.some(g => g.id === gid)) continue;
        const tabs = await queryTabs({ groupId: gid });
        const tabIds = tabs.map(t => t.id).filter((id): id is number => id != null);
        if (tabIds.length) {
          await ungroupTabs(tabIds);
          applied.ungrouped.push(...tabIds);
        }
      } else if (op.op === 'rest') {
        await this.restTabs(op.tabs, applied, /* requireIdle */ false);
      } else if (op.op === 'rest_group' || op.op === 'rest_auto') {
        // rest_group：整组都休息（仍受保护名单约束）
        // rest_auto：整组里「按时间该休息的」才休息，且受开关约束
        const gid = await this.resolveGroupId(op.groupId, op.title);
        if (gid == null) continue;
        const tabs = await queryTabs({ groupId: gid });
        const tabIds = tabs
          .map(t => t.id)
          .filter((id): id is number => id != null);
        if (!tabIds.length) continue;
        if (op.op === 'rest_auto') {
          if (!shouldAutoRest(params.restMode)) {
            for (const tabId of tabIds) {
              applied.rest.restSkipped.push({ tabId, reason: 'auto-rest-disabled' });
            }
            continue;
          }
          await this.restTabs(tabIds, applied, /* requireIdle */ true);
        } else {
          await this.restTabs(tabIds, applied, /* requireIdle */ false);
        }
      }
    }

    await this.collapseOrganizedGroups(touchedGroupIds, params.collapse, applied);

    return {
      organized: true,
      applied,
      ...(skipped.length ? { skipped } : {}),
    };
  }

  /**
   * 折叠本次整理涉及的 TabGroup。
   *
   * 默认 `'auto'`：折所有本次动过的组，但跳过**包含当前活跃 tab 的组** ——
   * 用户正在看的那一组被折起来会当场消失，属于干扰而不是整理。
   * `true`/`false` 是强制开关（真要折当前组时才用），`'none'` 完全不折。
   *
   * 组可能在本轮被 Chrome 销毁（比如 tab 全被关掉），query 拿不到就跳过。
   */
  private async collapseOrganizedGroups(
    groupIds: Set<number>,
    mode: 'auto' | 'none' | boolean | undefined,
    applied: BrowserTabOrganizeApplied,
  ): Promise<void> {
    if (mode === 'none' || mode === false || groupIds.size === 0) {
      return;
    }

    const force = mode === true;
    let groups: chrome.tabGroups.TabGroup[];
    try {
      groups = await queryGroups({});
    } catch {
      // tabGroups API 不可用：整批都当作失败记录下来，别让调用方以为「都折好了」
      for (const groupId of groupIds) applied.collapseFailed.push(groupId);
      return;
    }
    const byId = new Map(groups.map(g => [g.id, g]));

    for (const groupId of groupIds) {
      if (!byId.has(groupId)) {
        // 组已不存在（tab 被关光 / 被解散）：这不算折叠失败，也不该折 —— 两边都不记。
        continue;
      }
      if (!force && (await this.groupHasActiveTab(groupId))) {
        applied.collapseSkipped.push(groupId);
        continue;
      }
      try {
        await updateGroupFull(groupId, { collapsed: true });
        applied.collapsed.push(groupId);
      } catch {
        // 折叠失败不影响整理结果本身，不向上抛；但要记进 collapseFailed，
        // 否则调用方无法区分「没折因为活跃组」/「折失败了」。
        applied.collapseFailed.push(groupId);
      }
    }
  }

  /** 该组里是否有用户当前正在看的 tab。 */
  private async groupHasActiveTab(groupId: number): Promise<boolean> {
    try {
      const tabs = await queryTabs({ groupId });
      return tabs.some(tab => tab.active === true);
    } catch {
      // 查不到就保守认为「有活跃 tab」，宁可少折一个组也不打断用户
      return true;
    }
  }

  /** 按 groupId 或 title 定位一个组；找不到返回 undefined。 */
  private async resolveGroupId(
    groupId: number | undefined,
    title: string | undefined,
  ): Promise<number | undefined> {
    if (groupId != null) return groupId;
    if (!title) return undefined;
    const groups = await queryGroups({ title });
    if (groups.length > 1) {
      throw new BrowserExtensionRpcError(
        BROWSER_RPC_ERROR_CODE.invalidParams,
        `"${title}" matches ${groups.length} groups across windows; use groupId to specify which one`,
      );
    }
    return groups[0]?.id;
  }

  /**
   * 当前被活跃 Ethan session 占用的 tab 集合。
   *
   * session 账本按 groupId 记 tab，所以取每个 session 组里的 tab 就是「正在被
   * 自动化操作」的那批 —— 它们绝不能被 discard（会打断正在跑的流程）。
   *
   * 必须同时带 windowId（和 store-core 里 findSessionByGroup 的键一致）：
   * Chrome 允许两个窗口各有一个同 id 的组，只按 groupId 查会把另一个窗口里
   * 用户的普通组也算进来，那个组就永远休息不了、还报「正被会话使用」。
   */
  private async liveSessionTabIds(): Promise<Set<number>> {
    const out = new Set<number>();
    for (const session of this.sessions.values()) {
      try {
        const tabs = await queryTabs({
          groupId: session.groupId,
          windowId: session.windowId,
        });
        for (const t of tabs) {
          if (typeof t.id === 'number') out.add(t.id);
        }
      } catch {
        // 组已消失/查询失败：跳过这个 session，不因此阻断整批判定
      }
    }
    return out;
  }

  /**
   * 让一批 tab 休息（discard）。
   *
   * `requireIdle` 为 true 时，多一道「打开时间在昨天及更早」的判据（自动模式）；
   * 为 false 时是用户显式点名，只要不踩保护名单就照做。
   *
   * 保护名单（tab-rest.ts 的 decideRest）优先于一切：活跃 tab、出声的、固定的、
   * 正在被 session/CDP 用的、特殊 scheme 的，一律不动，并记进 restSkipped。
   */
  private async restTabs(
    tabIds: number[],
    applied: BrowserTabOrganizeApplied,
    requireIdle: boolean,
  ): Promise<void> {
    if (!tabIds.length) return;

    const liveSessionTabIds = await this.liveSessionTabIds();
    let cdpAttachedTabIds: Set<number>;
    try {
      const { getCdpAttachedTabIds } = await import('../cdp-client');
      cdpAttachedTabIds = getCdpAttachedTabIds();
    } catch (error) {
      // 取不到 CDP 状态就没法保证不打断正在跑的操作 —— 整批放弃并如实上报，
      // 不能猜一个空集合继续动手（那可能把挂着调试器的 tab 给 discard 了）。
      const message = error instanceof Error ? error.message : String(error);
      for (const tabId of tabIds) {
        applied.rest.restFailed.push({
          tabId,
          reason: `无法确认调试器占用状态，已放弃本批休息：${message}`,
        });
      }
      return;
    }
    const startOfToday = startOfLocalDay(Date.now());

    for (const tabId of tabIds) {
      let tab: chrome.tabs.Tab;
      try {
        tab = await getTab(tabId);
      } catch {
        applied.rest.restFailed.push({ tabId, reason: 'tab not found' });
        continue;
      }

      // 打开时间只用自己记的账。
      //
      // 曾经的写法是「没有记录就退回 tab.lastAccessed」，那是错的：lastAccessed 是
      // 「最近一次被访问」而不是「打开」，而且拿不到用户交互的后台 tab 会长时间不刷新，
      // 所以它**偏旧**。这正好和这里需要的方向相反 —— 昨天开的、填了一半表单的 tab
      // 报的仍是昨天，就会被判成「昨天的」而 discard，草稿直接没了。
      // 没有记录就留 undefined，判据那边按「今天」处理（保守，不动）。
      const openedAt = await getTabOpenedAt(tabId);

      const reason = decideRest({
        tab: tab as unknown as Parameters<typeof decideRest>[0]['tab'],
        openedAt,
        startOfToday,
        liveSessionTabIds,
        cdpAttachedTabIds,
        // 只有自动模式才卡「今天打开的」；用户显式点名时时间不构成拒绝理由。
        enforceRecency: requireIdle,
      });

      if (reason) {
        applied.rest.restSkipped.push({
          tabId,
          reason: REST_SKIP_REASON_LABEL[reason] ?? reason,
        });
        continue;
      }

      try {
        await discardTab(tabId);
        applied.rest.rested.push(tabId);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        applied.rest.restFailed.push({ tabId, reason: message });
      }
    }
  }
}

/** 把内部原因码转成给人看的中文说明（会一路出现在工具输出里）。 */
const REST_SKIP_REASON_LABEL: Record<RestSkipReason, string> = {
  'already-discarded': '已经处于休息状态',
  'active-tab': '是当前正在看的标签',
  audible: '正在播放声音',
  pinned: '已被固定',
  'auto-discard-disabled': '该标签关闭了自动丢弃',
  'unsupported-scheme': '该类型的页面不支持',
  'protected-url': '受保护的页面（内部页/本地文件/本地服务）',
  'live-session-tab': '正被 Ethan 会话或调试器使用',
  'opened-today': '是今天打开的，先不处理',
};
