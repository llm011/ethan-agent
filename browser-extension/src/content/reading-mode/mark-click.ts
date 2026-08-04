// @ts-nocheck
/* eslint-disable */

  // ========== Click mark to show delete ==========

  let markClickListener: ((e: MouseEvent) => void) | null = null;

  function setupMarkClickListener() {
    markClickListener = (e: MouseEvent) => {
      if (!active || !contentEl) return;
      const mark = (e.target as HTMLElement).closest('mark') as HTMLElement | null;
      if (!mark || !contentEl.contains(mark)) { removeDeletePopup(); return; }
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed) return;
      showDeletePopup(mark);
    };
    document.addEventListener('click', markClickListener, true);
  }

  function teardownMarkClickListener() {
    if (markClickListener) document.removeEventListener('click', markClickListener, true);
    markClickListener = null;
  }

  function showDeletePopup(mark: HTMLElement) {
    removeDeletePopup();
    const rect = mark.getBoundingClientRect();
    const dark = isDarkMode();
    const popup = document.createElement('div');
    popup.id = DELETE_POPUP_ID;
    Object.assign(popup.style, {
      position: 'fixed', zIndex: String(Z_TOOLBAR),
      left: (rect.left + rect.width / 2 - 16) + 'px',
      top: (rect.top - 36) + 'px',
      background: dark ? '#374151' : '#ffffff',
      border: '1px solid ' + (dark ? '#4b5563' : '#e5e7eb'),
      borderRadius: '8px', padding: '2px 4px',
      boxShadow: '0 2px 12px rgba(0,0,0,0.15)',
      display: 'flex', alignItems: 'center',
      opacity: '0', transform: 'translateY(4px)',
      transition: 'opacity 0.12s, transform 0.12s',
    });
    const delBtn = document.createElement('button');
    delBtn.textContent = '\uD83D\uDDD1';
    Object.assign(delBtn.style, {
      border: 'none', background: 'none', fontSize: '15px', cursor: 'pointer',
      padding: '4px 8px', borderRadius: '4px', transition: 'background 0.1s',
    });
    delBtn.title = '\u5220\u9664\u9ad8\u4eae';
    delBtn.onmouseenter = () => { delBtn.style.background = dark ? '#4b5563' : '#fee2e2'; };
    delBtn.onmouseleave = () => { delBtn.style.background = ''; };
    delBtn.onclick = (ev) => {
      ev.stopPropagation();
      removeDeletePopup();
      const parent = mark.parentNode;
      if (parent) {
        while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
        parent.removeChild(mark);
        parent.normalize();
      }
      saveContent();
      refreshAnnotations();
    };
    popup.appendChild(delBtn);

    // Show comment if exists
    const note = mark.dataset.note;
    if (note) {
      const noteEl = document.createElement('span');
      noteEl.textContent = note.length > 30 ? note.slice(0, 30) + '\u2026' : note;
      Object.assign(noteEl.style, {
        fontSize: '11px', color: dark ? '#9ca3af' : '#6b7280',
        padding: '2px 6px', maxWidth: '180px', overflow: 'hidden',
        whiteSpace: 'nowrap', textOverflow: 'ellipsis',
      });
      popup.appendChild(noteEl);
    }

    document.body.appendChild(popup);
    requestAnimationFrame(() => { popup.style.opacity = '1'; popup.style.transform = 'translateY(0)'; });
    setTimeout(() => { if (document.getElementById(DELETE_POPUP_ID)) removeDeletePopup(); }, 3500);
  }

  function removeDeletePopup() {
    document.getElementById(DELETE_POPUP_ID)?.remove();
  }
