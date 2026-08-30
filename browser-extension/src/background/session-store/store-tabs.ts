import type {
  BrowserSessionTab,
  BrowserTabAttachBatchParams,
  BrowserTabAttachBatchResult,
  BrowserTabAttachParams,
  BrowserTabAttachResult,
  BrowserTabCloseParams,
  BrowserTabCloseResult,
  BrowserTabDetachParams,
  BrowserTabDetachResult,
} from '../../shared';
import { BrowserSessionStoreSessions } from './store-sessions';
import { toSessionTab } from './utils';
import type { StoredSession } from './types';
import { TAB_GROUP_ID_NONE } from './constants';
import { BROWSER_RPC_ERROR_CODE } from '../../shared';
import { BrowserExtensionRpcError, BrowserTabAttachError } from './errors';
import {
  getTab,
  groupTabs,
  moveTabToWindow,
  removeTabs,
  ungroupTabs,
} from './chrome-api';

/** 单个 tab 的 attach 计划：搬运前先把状态摸清，避免边改边发现错误。 */
interface AttachPlan {
  tabId: number;
  sourceTab: chrome.tabs.Tab;
  /** 搬运前所在的窗口，失败兜底时用来还原位置。 */
  originalWindowId: number | undefined;
  /** 该 tab 原本归属的另一个 session；若本就属于目标 session 则为 undefined。 */
  releasedFrom: StoredSession | undefined;
  /** 我们是否主动把它摘出了旧 group（跨窗口移动前），失败时需要塞回去。 */
  ungrouped: boolean;
}

/**
 * 同一 tab 上的 attach 串行化。
 *
 * attach 内部有多处 `await`，会让出事件循环：两个并发的 attach 打同一个 tab 时，
 * 第二个可能在第一个改完之前就通过了占用检查，最终两个调用都返回 `attached: true`，
 * 而 tab 实际只挂在其中一个 group 下 —— 后一个拿到的是假结果，后续基于这个
 * session 的操作全打偏。这里用 in-flight promise 把对同一 tab 的 attach 排队，
 * 保证后一次看到的是前一次写完的状态。
 */
const inFlightAttachByTab = new Map<number, Promise<void>>();

function withTabAttachLock<T>(
  tabId: number,
  task: () => Promise<T>,
): Promise<T> {
  const previous = inFlightAttachByTab.get(tabId) ?? Promise.resolve();
  // 前一个失败也要继续跑，不能把队列卡死
  const next = previous.then(task, task);
  const settled: Promise<void> = next.then(
    () => undefined,
    () => undefined,
  );
  inFlightAttachByTab.set(tabId, settled);
  void settled.then(() => {
    if (inFlightAttachByTab.get(tabId) === settled) {
      inFlightAttachByTab.delete(tabId);
    }
  });
  return next;
}

/** 批量按 tabId 升序依次加锁：固定顺序，避免两个批量互相死锁。 */
function withTabAttachLocks<T>(
  tabIds: number[],
  task: () => Promise<T>,
): Promise<T> {
  const ordered = Array.from(new Set(tabIds)).sort((a, b) => a - b);
  const run = (index: number): Promise<T> =>
    index === ordered.length
      ? task()
      : withTabAttachLock(ordered[index], () => run(index + 1));
  return run(0);
}

export class BrowserSessionStoreTabs extends BrowserSessionStoreSessions {
  async attachTab(
    params: BrowserTabAttachParams,
  ): Promise<BrowserTabAttachResult> {
    const result = await withTabAttachLock(params.tabId, () =>
      this.attachTabsInternal(params.sessionId, [params.tabId]),
    );

    const tab = result.tabs[0];
    if (!tab) {
      throw new BrowserExtensionRpcError(
        BROWSER_RPC_ERROR_CODE.browserTabNotFound,
        `Tab ${params.tabId} disappeared while attaching`,
      );
    }

    const firstReleased = result.releasedFrom[0];
    return {
      attached: true,
      sessionId: result.sessionId,
      tab,
      ...(firstReleased ? { releasedFrom: firstReleased.sessionId } : {}),
    };
  }

  async attachBatchTabs(
    params: BrowserTabAttachBatchParams,
  ): Promise<BrowserTabAttachBatchResult> {
    const result = await withTabAttachLocks(params.tabIds, () =>
      this.attachTabsInternal(params.sessionId, params.tabIds),
    );

    return {
      attached: true,
      sessionId: result.sessionId,
      tabs: result.tabs,
      ...(result.releasedFrom.length
        ? { releasedFrom: result.releasedFrom }
        : {}),
    };
  }

  /**
   * attach 的公共实现：tab 已被别的 session 占用时不再报错要求先手动 release，
   * 而是自动把它从旧 session 接管过来（保留 tab），并记进 `releasedFrom`。
   *
   * 分三段，保证失败路径不留「已经改过但没告诉你」的状态：
   *   1. 预校验 —— 所有 tab 都 getTab 得到，此时还一行状态都没动；
   *   2. 物理搬运 —— 跨窗口移动 / 归入目标 group，失败则尽力塞回旧 group；
   *   3. 落账本 —— 只有 group 成功后才清理被抽空的旧 session 并统一 persist。
   */
  private async attachTabsInternal(
    sessionId: string,
    tabIds: number[],
  ): Promise<{
    sessionId: string;
    tabs: BrowserSessionTab[];
    releasedFrom: { tabId: number; sessionId: string }[];
  }> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(sessionId);
    await this.reconcileSessionOrThrow(session);

    // 1. 预校验：任一个 tabId 不存在就整批失败，此时还没动过任何状态
    const plans = await this.buildAttachPlans(session, tabIds);

    // 2. 物理搬运：只有这一步会真的改浏览器状态
    const touchedTabIds: number[] = [];
    try {
      await this.prepareTabs(session, plans, touchedTabIds);
      await groupTabs(
        plans.map(plan => plan.tabId),
        session.groupId,
      );
      // group 调用没报错不代表 tab 真进去了，回头校验一次，别静默返回成功
      await this.assertTabsInGroup(
        session,
        plans.map(plan => plan.tabId),
      );
    } catch (error) {
      // 失败兜底：把被我们摘出来的 tab 尽量塞回旧 group，别留下游离 tab
      await this.restoreTouchedTabs(plans, touchedTabIds);
      throw toAttachError(error, touchedTabIds);
    }

    // 3. 到这一步才算接管成功，此时才动账本
    const releasedFrom = await this.finalizeReleasedSessions(plans);

    const attachedTabs: BrowserSessionTab[] = [];
    for (const plan of plans) {
      attachedTabs.push(toSessionTab(await getTab(plan.tabId)));
    }

    session.activeTabId = plans[plans.length - 1]?.tabId ?? session.activeTabId;
    session.updatedAt = Date.now();
    await this.persist();

    return { sessionId, tabs: attachedTabs, releasedFrom };
  }

  /** 逐个 getTab 摸清来源状态并去重；这里抛错时还没有任何副作用。 */
  private async buildAttachPlans(
    session: StoredSession,
    tabIds: number[],
  ): Promise<AttachPlan[]> {
    const plans: AttachPlan[] = [];
    const seen = new Set<number>();
    for (const tabId of tabIds) {
      if (seen.has(tabId)) {
        continue;
      }
      seen.add(tabId);
      const sourceTab = await getTab(tabId);
      const owner = this.findSessionByGroup(
        sourceTab.groupId,
        sourceTab.windowId,
      );
      plans.push({
        tabId,
        sourceTab,
        originalWindowId: sourceTab.windowId,
        // 本来就归目标 session 的不算「释放」
        releasedFrom:
          owner && owner.sessionId !== session.sessionId ? owner : undefined,
        ungrouped: false,
      });
    }

    return plans;
  }

  /** 把需要跨窗口的 tab 先摘出旧 group 再移动；group 不能跨窗口，否则会把旧 group 一起拖过去。 */
  private async prepareTabs(
    session: StoredSession,
    plans: AttachPlan[],
    touchedTabIds: number[],
  ): Promise<void> {
    for (const plan of plans) {
      if (plan.sourceTab.windowId === session.windowId) {
        continue;
      }
      if (
        typeof plan.sourceTab.groupId === 'number' &&
        plan.sourceTab.groupId !== TAB_GROUP_ID_NONE
      ) {
        await ungroupTabs([plan.tabId]);
        plan.ungrouped = true;
      }
      touchedTabIds.push(plan.tabId);
      plan.sourceTab = await moveTabToWindow(plan.tabId, session.windowId);
    }
  }

  private async assertTabsInGroup(
    session: StoredSession,
    tabIds: number[],
  ): Promise<void> {
    for (const tabId of tabIds) {
      const tab = await getTab(tabId);
      if (tab.windowId !== session.windowId || tab.groupId !== session.groupId) {
        throw new BrowserExtensionRpcError(
          BROWSER_RPC_ERROR_CODE.browserTabGroupFailed,
          `Tab ${tabId} did not land in group ${session.groupId} of session ${session.sessionId}`,
        );
      }
    }
  }

  /**
   * 尽力把改动过的 tab 还原：摘出过旧 group 的塞回旧 group，只是被挪了窗口的挪回原窗口。
   * 旧 group / 旧窗口可能已被 Chrome 销毁，失败就放弃 —— 兜底不能盖掉原始错误。
   */
  private async restoreTouchedTabs(
    plans: AttachPlan[],
    touchedTabIds: number[],
  ): Promise<void> {
    const touched = new Set(touchedTabIds);
    for (const plan of plans) {
      if (!touched.has(plan.tabId)) {
        continue;
      }
      const oldSession = plan.ungrouped ? plan.releasedFrom : undefined;
      const backWindowId = oldSession?.windowId ?? plan.originalWindowId;
      if (backWindowId == null) {
        continue;
      }
      try {
        const tab = await getTab(plan.tabId);
        if (tab.windowId !== backWindowId) {
          await moveTabToWindow(plan.tabId, backWindowId);
        }
        if (oldSession) {
          await groupTabs([plan.tabId], oldSession.groupId);
        }
      } catch {
        // 旧 group / 旧窗口可能已经没了，兜底失败忽略
      }
    }
  }

  /**
   * 清理被抽走 tab 的旧 session：空了就删记录（与 close/detach 的空组清理一致），
   * 否则刷新其 activeTabId。只在 attach 已经成功之后调用。
   */
  private async finalizeReleasedSessions(
    plans: AttachPlan[],
  ): Promise<{ tabId: number; sessionId: string }[]> {
    const released: { tabId: number; sessionId: string }[] = [];
    const handled = new Set<string>();
    for (const plan of plans) {
      const oldSession = plan.releasedFrom;
      if (!oldSession) {
        continue;
      }
      released.push({ tabId: plan.tabId, sessionId: oldSession.sessionId });
      if (handled.has(oldSession.sessionId)) {
        continue;
      }
      handled.add(oldSession.sessionId);
      if (!this.sessions.has(oldSession.sessionId)) {
        continue;
      }
      const remaining = await this.getSessionTabs(oldSession);
      if (!remaining.length) {
        this.sessions.delete(oldSession.sessionId);
      } else {
        oldSession.activeTabId = this.resolveActiveTabId(
          remaining,
          oldSession.activeTabId,
        );
        oldSession.updatedAt = Date.now();
      }
    }

    return released;
  }

  async closeTab(
    params: BrowserTabCloseParams,
  ): Promise<BrowserTabCloseResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);
    await this.assertTabInSessionGroup(session, params.tabId);
    await removeTabs([params.tabId]);

    const remainingTabs = await this.getSessionTabs(session);
    if (!remainingTabs.length) {
      this.sessions.delete(params.sessionId);
      await this.persist();
      return {
        closed: true,
        sessionId: params.sessionId,
        closedTabId: params.tabId,
        sessionClosed: true,
      };
    }

    if (session.activeTabId === params.tabId) {
      session.activeTabId = this.resolveActiveTabId(remainingTabs);
    }
    session.updatedAt = Date.now();
    await this.persist();

    return {
      closed: true,
      sessionId: params.sessionId,
      closedTabId: params.tabId,
    };
  }

  async detachTab(
    params: BrowserTabDetachParams,
  ): Promise<BrowserTabDetachResult> {
    await this.ensureLoaded();
    const session = this.getSessionOrThrow(params.sessionId);
    await this.reconcileSessionOrThrow(session);
    await this.assertTabInSessionGroup(session, params.tabId);

    await ungroupTabs([params.tabId]);

    const remainingTabs = await this.getSessionTabs(session);
    if (!remainingTabs.length) {
      // Group 已空，Chrome 会自动销毁 Group，清理 session
      this.sessions.delete(params.sessionId);
      await this.persist();
      return {
        detached: true,
        sessionId: params.sessionId,
        detachedTabId: params.tabId,
      };
    }

    // If the detached tab was the active one, pick another
    if (session.activeTabId === params.tabId) {
      session.activeTabId = this.resolveActiveTabId(remainingTabs);
    }
    session.updatedAt = Date.now();
    await this.persist();

    return {
      detached: true,
      sessionId: params.sessionId,
      detachedTabId: params.tabId,
    };
  }
}

function toAttachError(error: unknown, touchedTabIds: number[]): unknown {
  if (error instanceof BrowserExtensionRpcError) {
    return new BrowserTabAttachError(error.code, error.message, touchedTabIds);
  }
  const message = error instanceof Error ? error.message : String(error);
  return new BrowserTabAttachError(
    BROWSER_RPC_ERROR_CODE.browserOperationFailed,
    message,
    touchedTabIds,
  );
}
