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
  props: { title?: string; color?: chrome.tabGroups.ColorEnum },
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
