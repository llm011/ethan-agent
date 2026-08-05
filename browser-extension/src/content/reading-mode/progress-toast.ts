// @ts-nocheck
/* eslint-disable */

  // ========== Progress Bar ==========

  function createProgressBar() {
    if (document.getElementById(PROGRESS_ID)) return;
    const bar = document.createElement('div');
    bar.id = PROGRESS_ID;
    Object.assign(bar.style, {
      position: 'fixed', top: '0', left: '0', height: '3px',
      background: 'linear-gradient(90deg, #0d9488, #06b6d4)',
      zIndex: String(Z_PROGRESS), width: '0%', transition: 'width 0.15s linear',
      borderRadius: '0 2px 2px 0',
    });
    document.body.appendChild(bar);
  }

  function updateProgress() {
    const bar = document.getElementById(PROGRESS_ID);
    const reader = document.getElementById(READER_ID);
    if (!bar || !reader) return;
    const pct = reader.scrollHeight > reader.clientHeight
      ? Math.min(100, (reader.scrollTop / (reader.scrollHeight - reader.clientHeight)) * 100) : 0;
    bar.style.width = pct + '%';
  }

  function removeProgressBar() { document.getElementById(PROGRESS_ID)?.remove(); }

  // ========== Toast ==========

  function showToast(msg: string) {
    const existing = document.getElementById('__ethan_reading_toast');
    if (existing) existing.remove();
    const toast = document.createElement('div');
    toast.id = '__ethan_reading_toast';
    Object.assign(toast.style, {
      position: 'fixed', bottom: '24px', left: '50%', transform: 'translateX(-50%) translateY(10px)',
      zIndex: String(Z_TOOLBAR), background: '#1f2937', color: '#fff',
      padding: '8px 16px', borderRadius: '8px', fontSize: '13px', fontWeight: '500',
      boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
      opacity: '0', transition: 'opacity 0.2s, transform 0.2s',
    });
    toast.textContent = msg;
    document.body.appendChild(toast);
    requestAnimationFrame(() => { toast.style.opacity = '1'; toast.style.transform = 'translateX(-50%) translateY(0)'; });
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 200); }, 1800);
  }
