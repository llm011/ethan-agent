import type {
  BrowserPageActionResult,
  BrowserPagePressParams,
  BrowserPageUploadParams,
} from '../../shared';
import type { PageControllerContext, RuntimeStatus } from './types';
import {
  callFunctionOn,
  dispatchMouseButton,
  dispatchMouseMove,
} from './cdp-helpers';
import { resolveRef } from './ref-resolver';
import { ensureRuntimeOk } from './errors';
import { getKeyDefinition } from './key-mapping';

export async function clickAction(
  ctx: PageControllerContext,
  params: { sessionId: string; ref: string },
): Promise<BrowserPageActionResult> {
  return ctx.withPage(params.sessionId, async ({ tab, client }) => {
    const resolved = await resolveRef(
      ctx.refStore,
      client,
      tab,
      params.ref,
      true,
    );
    await dispatchMouseMove(client, resolved.center.x, resolved.center.y);
    await dispatchMouseButton(
      client,
      'mousePressed',
      resolved.center,
      'left',
    );
    await dispatchMouseButton(
      client,
      'mouseReleased',
      resolved.center,
      'left',
    );
    ctx.lastMousePositionByTab.set(tab.tabId, resolved.center);
    return ctx.createActionResult(params.sessionId, tab, params.ref);
  });
}

export async function hoverAction(
  ctx: PageControllerContext,
  params: { sessionId: string; ref: string },
): Promise<BrowserPageActionResult> {
  return ctx.withPage(params.sessionId, async ({ tab, client }) => {
    const resolved = await resolveRef(
      ctx.refStore,
      client,
      tab,
      params.ref,
      false,
    );
    await dispatchMouseMove(client, resolved.center.x, resolved.center.y);
    ctx.lastMousePositionByTab.set(tab.tabId, resolved.center);
    return ctx.createActionResult(params.sessionId, tab, params.ref);
  });
}

export async function fillAction(
  ctx: PageControllerContext,
  params: { sessionId: string; ref: string; text: string },
): Promise<BrowserPageActionResult> {
  return runInsertText(ctx, params.sessionId, params.ref, 'fill', params.text);
}

export async function typeAction(
  ctx: PageControllerContext,
  params: { sessionId: string; ref: string; text: string },
): Promise<BrowserPageActionResult> {
  return runInsertText(ctx, params.sessionId, params.ref, 'type', params.text);
}

export async function selectAction(
  ctx: PageControllerContext,
  params: { sessionId: string; ref: string; value: string },
): Promise<BrowserPageActionResult> {
  return runDomAction(
    ctx,
    params.sessionId,
    params.ref,
    'select',
    params.value,
  );
}

export async function scrollIntoViewAction(
  ctx: PageControllerContext,
  params: { sessionId: string; ref: string },
): Promise<BrowserPageActionResult> {
  return runDomAction(ctx, params.sessionId, params.ref, 'scrollIntoView');
}

export async function pressAction(
  ctx: PageControllerContext,
  params: BrowserPagePressParams,
): Promise<BrowserPageActionResult> {
  return ctx.withPage(params.sessionId, async ({ tab, client }) => {
    const definition = getKeyDefinition(params.key);
    await client.send('Input.dispatchKeyEvent', {
      type: 'rawKeyDown',
      key: definition.key,
      code: definition.code,
      windowsVirtualKeyCode: definition.windowsVirtualKeyCode,
      modifiers: definition.modifiers,
      ...(definition.text ? { text: definition.text } : {}),
    });
    await client.send('Input.dispatchKeyEvent', {
      type: 'keyUp',
      key: definition.key,
      code: definition.code,
      windowsVirtualKeyCode: definition.windowsVirtualKeyCode,
      modifiers: definition.modifiers,
    });
    return ctx.createActionResult(params.sessionId, tab);
  });
}

export async function uploadAction(
  ctx: PageControllerContext,
  params: BrowserPageUploadParams,
): Promise<BrowserPageActionResult> {
  return ctx.withPage(params.sessionId, async ({ tab, client }) => {
    const resolved = await resolveRef(
      ctx.refStore,
      client,
      tab,
      params.ref,
      false,
    );
    // DOM.setFileInputFiles 从本地路径读取真实文件内容，效果等同用户手动选文件。
    await client.send('DOM.setFileInputFiles', {
      backendNodeId: resolved.entry.backendNodeId,
      files: params.files,
    });
    return ctx.createActionResult(params.sessionId, tab, params.ref);
  });
}

async function runInsertText(
  ctx: PageControllerContext,
  sessionId: string,
  ref: string,
  mode: 'fill' | 'type',
  text: string,
): Promise<BrowserPageActionResult> {
  return ctx.withPage(sessionId, async ({ tab, client }) => {
    const resolved = await resolveRef(ctx.refStore, client, tab, ref, false);
    // 1) 聚焦元素并按 mode 设置选区：fill=全选(随后 insertText 替换)，type=光标移到末尾(追加)。
    const prep = await callFunctionOn<RuntimeStatus>(
      client,
      resolved.objectId,
      `function(mode) {
        if (typeof this.focus === 'function') this.focus();
        const isInput = ('value' in this) && typeof this.select === 'function';
        if (mode === 'fill') {
          if (isInput) {
            this.select();
          } else if (this.isContentEditable) {
            const range = document.createRange();
            range.selectNodeContents(this);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
          }
        } else if (isInput) {
          const len = (this.value || '').length;
          try { this.setSelectionRange(len, len); } catch (e) {}
        } else if (this.isContentEditable) {
          const range = document.createRange();
          range.selectNodeContents(this);
          range.collapse(false);
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.addRange(range);
        }
        return { ok: true };
      }`,
      [mode],
    );
    ensureRuntimeOk(prep, ref);
    // 2) 经 CDP Input.insertText 注入文本——走真实输入管线，触发 beforeinput/input(InputEvent)，
    //    CodeMirror/Lexical/React 受控组件都能识别；直接改 value/textContent 这些框架不认，
    //    会出现「框里看着有字、内部 model 仍为空」的发送失败。
    if (mode === 'fill' && text === '') {
      // insertText('') 不保证清空已选内容，单独发一次 Delete 删除选区。
      await client.send('Input.dispatchKeyEvent', {
        type: 'keyDown', key: 'Delete', code: 'Delete', windowsVirtualKeyCode: 46,
      });
      await client.send('Input.dispatchKeyEvent', {
        type: 'keyUp', key: 'Delete', code: 'Delete', windowsVirtualKeyCode: 46,
      });
    } else {
      await client.send('Input.insertText', { text });
    }
    return ctx.createActionResult(sessionId, tab, ref);
  });
}

async function runDomAction(
  ctx: PageControllerContext,
  sessionId: string,
  ref: string,
  action: 'fill' | 'type' | 'select' | 'scrollIntoView',
  value?: string,
): Promise<BrowserPageActionResult> {
  return ctx.withPage(sessionId, async ({ tab, client }) => {
    const resolved = await resolveRef(ctx.refStore, client, tab, ref, false);
    const result = await callFunctionOn<RuntimeStatus>(
      client,
      resolved.objectId,
      `function(action, value) {
        const dispatch = type => this.dispatchEvent(new Event(type, { bubbles: true }));
        if (action === 'scrollIntoView') {
          this.scrollIntoView({ block: 'center', inline: 'center', behavior: 'auto' });
          return { ok: true };
        }
        if (action === 'select') {
          this.value = value || '';
          dispatch('input');
          dispatch('change');
          return { ok: true };
        }
        if (typeof this.focus === 'function') this.focus();
        if (this.isContentEditable) {
          this.textContent = action === 'fill'
            ? value || ''
            : String(this.textContent || '') + (value || '');
          dispatch('input');
          return { ok: true };
        }
        if ('value' in this) {
          this.value = action === 'fill'
            ? value || ''
            : String(this.value || '') + (value || '');
          dispatch('input');
          dispatch('change');
          return { ok: true };
        }
        return { ok: false, error: 'UNSUPPORTED_ELEMENT' };
      }`,
      [action, value || ''],
    );
    ensureRuntimeOk(result, ref);
    return ctx.createActionResult(sessionId, tab, ref);
  });
}
