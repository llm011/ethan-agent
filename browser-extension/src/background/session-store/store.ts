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
      return; // tabGroups API 不可用，静默跳过
    }
    const byId = new Map(groups.map(g => [g.id, g]));

    for (const groupId of groupIds) {
      if (!byId.has(groupId)) {
        continue; // 组已不存在（tab 被关光 / 被解散）
      }
      if (!force && (await this.groupHasActiveTab(groupId))) {
        applied.collapseSkipped.push(groupId);
        continue;
      }
      try {
        await updateGroupFull(groupId, { collapsed: true });
        applied.collapsed.push(groupId);
      } catch {
        // 折叠失败不影响整理结果本身，不向上抛
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
}
