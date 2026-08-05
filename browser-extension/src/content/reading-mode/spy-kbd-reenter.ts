// @ts-nocheck
/* eslint-disable */

  // ========== Scroll Spy ==========

  function setupScrollSpy() {
    const reader = document.getElementById(READER_ID);
    if (!reader) return;
    let ticking = false;
    scrollHandler = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => { updateProgress(); highlightToc(); ticking = false; });
    };
    reader.addEventListener('scroll', scrollHandler, { passive: true });
  }

  function teardownScrollSpy() {
    if (scrollHandler) {
      const reader = document.getElementById(READER_ID);
      if (reader) reader.removeEventListener('scroll', scrollHandler);
    }
    scrollHandler = null;
  }

  function highlightToc() {
    if (!tocItemsRef.length) return;
    const tocEl = getPanelEl('__ethan_reading_toc');
    const reader = document.getElementById(READER_ID);
    if (!tocEl || !reader) return;
    const scrollTop = reader.scrollTop;
    let activeIdx = 0;
    for (let i = tocItemsRef.length - 1; i >= 0; i--) {
      if (tocItemsRef[i].el.offsetTop <= scrollTop + 120) { activeIdx = i; break; }
    }
    tocEl.querySelectorAll<HTMLElement>('[data-toc-idx]').forEach((el, i) => {
      el.style.fontWeight = i === activeIdx ? '600' : '';
      el.style.color = i === activeIdx ? '#0d9488' : '';
    });
  }

  // ========== Keyboard ==========

  let keydownListener: ((e: KeyboardEvent) => void) | null = null;

  function setupKeyboard() {
    keydownListener = (e: KeyboardEvent) => {
      if (!active) return;
      if (e.key === 'Escape') exitReading();
    };
    document.addEventListener('keydown', keydownListener);
  }

  function teardownKeyboard() {
    if (keydownListener) document.removeEventListener('keydown', keydownListener);
    keydownListener = null;
  }

  // ========== Re-enter Button ==========

  function showReenterButton() {
    if (document.getElementById(REENTER_ID)) return;
    const btn = document.createElement('button');
    btn.id = REENTER_ID;
    Object.assign(btn.style, {
      position: 'fixed', bottom: '20px', right: '20px', zIndex: String(Z_REENTER),
      width: '44px', height: '44px', borderRadius: '50%',
      background: 'linear-gradient(135deg,#0d9488,#06b6d4)', border: 'none',
      color: '#fff', fontSize: '18px', cursor: 'pointer',
      boxShadow: '0 4px 16px rgba(13,148,136,0.4)',
      transition: 'transform 0.2s',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    });
    btn.textContent = '\uD83D\uDCD6';
    btn.title = '\u91cd\u65b0\u8fdb\u5165\u9605\u8bfb\u6a21\u5f0f';
    btn.onmouseenter = () => { btn.style.transform = 'scale(1.1)'; };
    btn.onmouseleave = () => { btn.style.transform = ''; };
    btn.onclick = () => { btn.remove(); enterReading(); };
    document.body.appendChild(btn);
  }

  function removeReenterButton() { document.getElementById(REENTER_ID)?.remove(); }
