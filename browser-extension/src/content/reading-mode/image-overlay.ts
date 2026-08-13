// @ts-nocheck
/* eslint-disable */

  // ========== Image Overlay（图片放大 / 删除） ==========

  /** 给正文容器里的每个 <img> 包一层 wrapper，hover 显示放大 + 删除按钮。
   *  放大：全屏黑色背景查看；删除：从 DOM 移除该图片。 */
  function setupImageOverlays() {
    if (!contentEl) return;
    const imgs = contentEl.querySelectorAll('img');
    imgs.forEach(img => {
      const parent = img.parentElement;
      if (!parent) return;
      if (parent.classList && parent.classList.contains('__ethan_img_wrap')) return; // 已处理
      if (parent.classList && parent.classList.contains('__ethan_img_broken')) return;

      // 处理加载失败的图片
      const handleError = () => {
        const alt = img.getAttribute('alt') || '';
        const placeholder = document.createElement('div');
        placeholder.className = '__ethan_img_broken';
        Object.assign(placeholder.style, {
          padding: '16px 20px', borderRadius: '8px', margin: '12px 0',
          background: 'rgba(127,127,127,0.06)', border: '1px solid rgba(127,127,127,0.12)',
        } as any);
        if (alt && alt.length > 10) {
          const p = document.createElement('p');
          p.style.cssText = 'font-size:13px;color:#6b7280;line-height:1.6;margin:0';
          p.textContent = alt;
          placeholder.appendChild(p);
        } else {
          placeholder.innerHTML = `<p style="font-size:13px;color:#9ca3af;margin:0">⚠️ 图片无法加载</p>`;
        }
        // 如果已经被 wrap 包裹，替换整个 wrap
        const wrap = img.closest('.__ethan_img_wrap');
        if (wrap) {
          wrap.replaceWith(placeholder);
        } else {
          img.replaceWith(placeholder);
        }
      };

      // 检测 src 不是有效 URL 的情况（只是 token）
      const src = img.getAttribute('src') || '';
      if (src && !src.startsWith('http') && !src.startsWith('data:') && !src.startsWith('/') && !src.startsWith('./')) {
        // src 是 media token，尝试用 href 属性
        const href = img.getAttribute('href') || '';
        if (href && href.startsWith('http')) {
          img.src = href;
        } else {
          handleError();
          return;
        }
      }

      img.addEventListener('error', handleError, { once: true });
      // Handle images that already failed before listener was attached
      if (img.complete && img.naturalWidth === 0) { handleError(); return; }

      // 包装
      const wrap = document.createElement('div');
      wrap.className = '__ethan_img_wrap';
      const insideFigure = parent.tagName === 'FIGURE';
      Object.assign(wrap.style, {
        position: 'relative', display: 'inline-block',
        maxWidth: '100%', margin: insideFigure ? '0' : '20px 0', lineHeight: '0',
      } as any);

      parent.insertBefore(wrap, img);
      wrap.appendChild(img);
      img.style.margin = '0';
      img.style.display = 'block';
      img.style.maxWidth = '100%';
      img.style.height = 'auto';
      img.style.borderRadius = '8px';

      // 放大按钮（中间）
      const zoomBtn = document.createElement('button');
      zoomBtn.type = 'button';
      zoomBtn.title = '放大查看';
      zoomBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>';
      Object.assign(zoomBtn.style, {
        position: 'absolute', top: '50%', left: '50%',
        transform: 'translate(-50%, -50%)',
        width: '36px', height: '36px', borderRadius: '50%',
        border: 'none', padding: '0', cursor: 'pointer',
        background: 'rgba(0,0,0,0.55)', color: '#fff',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        opacity: '0', transition: 'opacity 0.15s ease',
        backdropFilter: 'blur(2px)',
      } as any);

      // 删除按钮（右上角）
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.title = '删除图片';
      delBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
      Object.assign(delBtn.style, {
        position: 'absolute', top: '8px', right: '8px',
        width: '28px', height: '28px', borderRadius: '50%',
        border: 'none', padding: '0', cursor: 'pointer',
        background: 'rgba(0,0,0,0.55)', color: '#fff',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        opacity: '0', transition: 'opacity 0.15s ease',
        backdropFilter: 'blur(2px)',
      } as any);

      wrap.appendChild(zoomBtn);
      wrap.appendChild(delBtn);

      wrap.addEventListener('mouseenter', () => {
        zoomBtn.style.opacity = '1';
        delBtn.style.opacity = '1';
      });
      wrap.addEventListener('mouseleave', () => {
        zoomBtn.style.opacity = '0';
        delBtn.style.opacity = '0';
      });

      zoomBtn.addEventListener('click', (e: Event) => {
        e.stopPropagation();
        openImageLightbox(img.src, img.alt);
      });
      delBtn.addEventListener('click', (e: Event) => {
        e.stopPropagation();
        wrap.remove();
        saveContent();
        scheduleRefresh();
      });
    });
  }

  /** 轻量图片 Lightbox：全屏黑色背景 + ESC/点击关闭。 */
  function openImageLightbox(src: string, alt?: string) {
    const overlay = document.createElement('div');
    overlay.id = '__ethan_img_lightbox';
    Object.assign(overlay.style, {
      position: 'fixed', top: '0', left: '0', right: '0', bottom: '0',
      zIndex: String(Z_READER + 100),
      background: 'rgba(0,0,0,0.92)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      cursor: 'zoom-out', backdropFilter: 'blur(4px)',
      opacity: '0', transition: 'opacity 0.2s ease',
    } as any);

    const img = document.createElement('img');
    img.src = src;
    img.alt = alt || '';
    Object.assign(img.style, {
      maxWidth: '92vw', maxHeight: '92vh', objectFit: 'contain',
      borderRadius: '4px', boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
    } as any);

    overlay.appendChild(img);
    document.body.appendChild(overlay);
    requestAnimationFrame(() => { overlay.style.opacity = '1'; });

    const close = () => {
      overlay.style.opacity = '0';
      setTimeout(() => overlay.remove(), 200);
      document.removeEventListener('keydown', escHandler, true);
    };

    overlay.addEventListener('click', close);

    const escHandler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        close();
      }
    };
    document.addEventListener('keydown', escHandler, true);
  }
