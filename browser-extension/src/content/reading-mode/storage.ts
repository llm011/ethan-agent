// @ts-nocheck
/* eslint-disable */

  // ========== Local Storage (chrome.storage.local) ==========

  interface SavedData {
    url: string;
    title: string;
    html: string;
    summary?: string;
    savedAt: number;
  }

  function saveContent() {
    if (!contentEl) return;
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => {
      const data: SavedData = {
        url: currentUrl,
        title: document.title || '',
        html: contentEl!.innerHTML,
        summary: summaryText || undefined,
        savedAt: Date.now(),
      };
      chrome.storage.local.set({ [storageKey()]: data });
    }, 800);
  }

  // 防抖刷新 TOC + 标注列表，避免编辑时每键全量重建
  function scheduleRefresh() {
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = window.setTimeout(() => {
      refreshToc();
      refreshAnnotations();
    }, 250);
  }

  function loadContent(cb: (data: SavedData | null) => void) {
    chrome.storage.local.get([storageKey()], (result) => {
      const data = result[storageKey()] as SavedData | undefined;
      cb(data && data.url === currentUrl ? data : null);
    });
  }
