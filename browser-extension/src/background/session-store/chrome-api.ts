import { BROWSER_RPC_ERROR_CODE } from '../../shared';
import { BrowserExtensionRpcError } from './errors';
import { rejectWithRuntimeError } from './utils';

export function createTab(
  params: chrome.tabs.CreateProperties,
): Promise<chrome.tabs.Tab> {
  return new Promise((resolve, reject) => {
    chrome.tabs.create(params, tab => {
      if (rejectWithRuntimeError(reject, 'Failed to create tab')) {
        return;
      }
      resolve(tab);
    });
  });
}

export function getTab(tabId: number): Promise<chrome.tabs.Tab> {
  return new Promise<chrome.tabs.Tab>((resolve, reject) => {
    chrome.tabs.get(tabId, tab => {
      if (rejectWithRuntimeError(reject, `Tab ${tabId} not found`)) {
        return;
      }
      resolve(tab);
    });
  }).catch(error => {
    const message = error instanceof Error ? error.message : String(error);
    throw new BrowserExtensionRpcError(
      BROWSER_RPC_ERROR_CODE.browserTabNotFound,
      message,
    );
  });
}

export function getCurrentActiveTab(): Promise<chrome.tabs.Tab> {
  return new Promise((resolve, reject) => {
    chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
      if (rejectWithRuntimeError(reject, 'Failed to query active tab')) {
        return;
      }

      const tab = tabs[0];
      if (!tab) {
        reject(
          new BrowserExtensionRpcError(
            BROWSER_RPC_ERROR_CODE.browserTabNotFound,
            'Current active tab not found',
          ),
        );
        return;
      }

      resolve(tab);
    });
  });
}

export function moveTabToWindow(
  tabId: number,
  windowId: number,
): Promise<chrome.tabs.Tab> {
  return new Promise((resolve, reject) => {
    chrome.tabs.move(tabId, { windowId, index: -1 }, tab => {
      if (rejectWithRuntimeError(reject, 'Failed to move tab')) {
        return;
      }

      resolve(Array.isArray(tab) ? tab[0] : tab);
    });
  });
}

export function queryTabs(
  queryInfo: chrome.tabs.QueryInfo,
): Promise<chrome.tabs.Tab[]> {
  return new Promise((resolve, reject) => {
    chrome.tabs.query(queryInfo, tabs => {
      if (rejectWithRuntimeError(reject, 'Failed to query tabs')) {
        return;
      }
      resolve(tabs);
    });
  });
}

export function groupTabs(tabIds: number[], groupId?: number): Promise<number> {
  const groupTabIds = tabIds as [number, ...number[]];
  return new Promise<number>((resolve, reject) => {
    chrome.tabs.group(
      {
        tabIds: groupTabIds,
        ...(typeof groupId === 'number' ? { groupId } : {}),
      },
      nextGroupId => {
        if (rejectWithRuntimeError(reject, 'Failed to group tabs')) {
          return;
        }
        resolve(nextGroupId);
      },
    );
  }).catch(error => {
    const message = error instanceof Error ? error.message : String(error);
    throw new BrowserExtensionRpcError(
      BROWSER_RPC_ERROR_CODE.browserTabGroupFailed,
      message,
    );
  });
}

export function updateGroup(groupId: number, title: string): Promise<void> {
  return new Promise((resolve, reject) => {
    chrome.tabGroups.update(groupId, { title }, () => {
      if (rejectWithRuntimeError(reject, 'Failed to update tab group')) {
        return;
      }
      resolve();
    });
  });
}

export function updateGroupFull(
  groupId: number,
  props: {
    title?: string;
    color?: chrome.tabGroups.ColorEnum;
    collapsed?: boolean;
  },
): Promise<void> {
  return new Promise((resolve, reject) => {
    chrome.tabGroups.update(groupId, props, () => {
      if (rejectWithRuntimeError(reject, 'Failed to update tab group')) {
        return;
      }
      resolve();
    });
  });
}

export function updateTab(
  tabId: number,
  updateProperties: chrome.tabs.UpdateProperties,
): Promise<chrome.tabs.Tab> {
  return new Promise((resolve, reject) => {
    chrome.tabs.update(tabId, updateProperties, tab => {
      if (rejectWithRuntimeError(reject, 'Failed to update tab')) {
        return;
      }
      if (!tab) {
        reject(
          new BrowserExtensionRpcError(
            BROWSER_RPC_ERROR_CODE.browserTabNotFound,
            `Tab ${tabId} not found`,
          ),
        );
        return;
      }
      resolve(tab);
    });
  });
}

export function removeTabs(tabIds: number[]): Promise<void> {
  return new Promise((resolve, reject) => {
    chrome.tabs.remove(tabIds, () => {
      if (rejectWithRuntimeError(reject, 'Failed to remove tabs')) {
        return;
      }
      resolve();
    });
  });
}

export function ungroupTabs(tabIds: number[]): Promise<void> {
  return new Promise((resolve, reject) => {
    chrome.tabs.ungroup(tabIds, () => {
      if (rejectWithRuntimeError(reject, 'Failed to ungroup tabs')) {
        return;
      }
      resolve();
    });
  });
}

export function queryGroups(
  filter: chrome.tabGroups.QueryInfo = {},
): Promise<chrome.tabGroups.TabGroup[]> {
  return new Promise((resolve, reject) => {
    chrome.tabGroups.query(filter, groups => {
      if (rejectWithRuntimeError(reject, 'Failed to query tab groups')) {
        return;
      }
      resolve(groups);
    });
  });
}

/**
 * 最近关闭的 tab/窗口。
 *
 * 用 sessions 而不是 history：sessions 就是「最近关掉的 tab」这个语义，
 * 不需要 history 那条更重的权限（"在所有已登录设备上读取和更改浏览历史"）。
 * 上限由浏览器固定为 25 条（MAX_SESSION_RESULTS），我们不需要也无法调大。
 */
export function getRecentlyClosed(
  maxResults = 25,
): Promise<chrome.sessions.Session[]> {
  return new Promise(resolve => {
    // query 为 {} 而非 filter：只要最近关闭的 tab，不需要按窗口过滤。
    // 这个 API 取不到结果不算错误，失败时返回空数组即可，不该让搜索整个挂掉。
    try {
      chrome.sessions.getRecentlyClosed({ maxResults }, sessions => {
        void chrome.runtime.lastError;
        resolve(sessions ?? []);
      });
    } catch {
      resolve([]);
    }
  });
}

export function moveTabToIndex(
  tabId: number,
  index: number,
): Promise<chrome.tabs.Tab> {
  return new Promise((resolve, reject) => {
    chrome.tabs.move(tabId, { index }, tab => {
      if (rejectWithRuntimeError(reject, 'Failed to move tab')) {
        return;
      }
      resolve(Array.isArray(tab) ? tab[0] : tab);
    });
  });
}

/**
 * 让 tab 休息：释放渲染进程内存，标题留在标签栏，点开时重新加载。
 *
 * 注意 Chrome 的两条限制（文档明说）：**活跃 tab 不会被 discard**，已 discard 的
 * 也不会重复处理。命中这两种情况不报错，但调用方要自己先判掉（见 tab-rest.ts），
 * 否则会以为「rested 了」其实没动。
 */
export function discardTab(tabId: number): Promise<chrome.tabs.Tab> {
  return new Promise<chrome.tabs.Tab>((resolve, reject) => {
    chrome.tabs.discard(tabId, tab => {
      if (rejectWithRuntimeError(reject, 'Failed to discard tab')) {
        return;
      }
      if (!tab) {
        reject(
          new BrowserExtensionRpcError(
            BROWSER_RPC_ERROR_CODE.browserTabNotFound,
            `Tab ${tabId} could not be discarded`,
          ),
        );
        return;
      }
      resolve(tab);
    });
  });
}
