// @ts-nocheck
/* eslint-disable */

  // ========== Utilities ==========

  function genId(): string { return Math.random().toString(36).slice(2, 10) + Date.now().toString(36); }
  function escapeHtml(s: string): string { return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function estimateReadTime(text: string): number { return Math.max(1, Math.ceil(text.length / 400)); }
  function clamp(v: number, min: number, max: number): number { return Math.max(min, Math.min(max, v)); }
  function isDarkMode(): boolean { return window.matchMedia('(prefers-color-scheme: dark)').matches; }

  function storageKey(): string {
    let hash = 0;
    for (let i = 0; i < currentUrl.length; i++) hash = ((hash << 5) - hash + currentUrl.charCodeAt(i)) | 0;
    return 'reading_' + Math.abs(hash).toString(36);
  }

  function getPanelEl(id: string): HTMLElement | null {
    const panel = document.getElementById(PANEL_ID);
    if (panel && panel.shadowRoot) {
      return (panel.shadowRoot.getElementById(id) as HTMLElement | null) || document.getElementById(id);
    }
    return document.getElementById(id);
  }
