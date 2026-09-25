/* eslint-disable */
// 指令管理页：增删改自定义指令、选 model，并管理「弹窗里展示什么」。
//
// 三件事在这里汇合，但职责分得很开：
//   1. **指令本身**（增删改提示词/图标/范围/模型）→ 读写 storage 的 'commands'
//   2. **展示顺序** → 就是 'commands' 数组的次序，拖动/上移下移都改它，不另存一份
//   3. **弹窗展示偏好**（移出弹窗 / 展示数量）→ 'hiddenCommandIds' + 'popupCommandLimit'
//
// 「移出弹窗」不是删除：指令仍留在 'commands' 里，右键菜单和选中工具条照常能用，
// 这里随时能加回来。所以列表里被移出的卡片要一直显示、并明确标出状态。
//
// 纯逻辑（排序/裁剪/移出集合的语义）都在 shared/command-prefs.ts，带单测；
// 这个文件只负责把它接到 DOM 上。

import {
  readCommands, saveCommands, resetCommands, DEFAULT_COMMANDS,
  readCommandPrefs, saveCommandPrefs,
  selectPopupCommands, togglePopupVisibility, moveItem,
  pruneHiddenIds, normalizeLimit,
} from '../shared';

const $ = id => document.getElementById(id);

let commands = [];
let prefs = { hiddenIds: [], limit: 0 };
let models = [];   // [{id, description}]
let dragFromIndex = null;   // 拖动中的源下标

function status(text) {
  $('status').textContent = text;
  if (text) setTimeout(() => { if ($('status').textContent === text) $('status').textContent = ''; }, 2000);
}

function genId() {
  return 'cmd-' + Math.random().toString(36).slice(2, 8);
}

// 模型下拉：一个「服务端默认」空选项 + 拉到的模型 + 当前值（即使不在列表也保留）
function modelOptions(selected) {
  const opts = ['<option value="">（服务端默认）</option>'];
  const seen = new Set();
  for (const m of models) {
    seen.add(m.id);
    const label = m.description && m.description !== m.id ? `${m.id} · ${m.description}` : m.id;
    opts.push(`<option value="${escapeAttr(m.id)}"${m.id === selected ? ' selected' : ''}>${escapeHtml(label)}</option>`);
  }
  if (selected && !seen.has(selected)) {
    opts.push(`<option value="${escapeAttr(selected)}" selected>${escapeHtml(selected)}（未在列表）</option>`);
  }
  return opts.join('');
}

function escapeHtml(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function escapeAttr(s) { return escapeHtml(s).replace(/"/g, '&quot;'); }

/** 弹窗当前实际展示的条数（用于顶部摘要，让「展示数量」这个设置看得见效果）。 */
function popupSummary() {
  const shown = selectPopupCommands(commands, prefs).length;
  const hidden = commands.length - selectPopupCommands(commands, { hiddenIds: prefs.hiddenIds, limit: 0 }).length;
  const parts = [`弹窗展示 ${shown} / ${commands.length} 条`];
  if (hidden > 0) parts.push(`其中 ${hidden} 条已移出`);
  return parts.join('，');
}

function render() {
  const list = $('list');
  list.innerHTML = '';

  commands.forEach((cmd, i) => {
    const hidden = prefs.hiddenIds.includes(cmd.id);
    const card = document.createElement('div');
    card.className = 'card' + (hidden ? ' hidden-cmd' : '');
    card.draggable = true;
    card.dataset.index = String(i);

    // 序号 + 拖动把手 + 上移/下移：三种方式都能改顺序（拖动是给鼠标，
    // 上下移是给键盘/触屏，也方便精确定位到「上一条/下一条」）。
    card.innerHTML = `
      <div class="card-head">
        <span class="drag-handle" title="按住拖动调整顺序">⠿</span>
        <span class="pos">${i + 1}</span>
        <span style="font-size:18px">${escapeHtml(cmd.icon || '⚙️')}</span>
        <span class="name">${escapeHtml(cmd.label || '(未命名)')}</span>
        ${cmd.builtin ? '<span class="badge">内置</span>' : '<span class="badge">自定义</span>'}
        ${hidden ? '<span class="badge badge-hidden">已移出弹窗</span>' : ''}
      </div>
      <div class="grid">
        <label>图标</label>
        <div class="row-inline">
          <div style="flex:none"><input class="icon-in" data-f="icon" value="${escapeAttr(cmd.icon || '')}" maxlength="4" /></div>
          <div><input data-f="label" value="${escapeAttr(cmd.label || '')}" placeholder="指令名，如 摘要" /></div>
        </div>
        <label>作用范围</label>
        <div class="row-inline">
          <div>
            <select data-f="scope">
              <option value="page"${cmd.scope === 'page' ? ' selected' : ''}>整页正文 {content}</option>
              <option value="selection"${cmd.scope === 'selection' ? ' selected' : ''}>选中文字 {selection}</option>
            </select>
          </div>
          <div>
            <select data-f="model">${modelOptions(cmd.model || '')}</select>
          </div>
        </div>
        <label>提示词</label>
        <div>
          <textarea data-f="promptTemplate" placeholder="用 {content}/{selection}/{query} 引用上下文">${escapeHtml(cmd.promptTemplate || '')}</textarea>
          <div class="ph-list">
            <span class="ph" data-ph="{content}">{content}</span>
            <span class="ph" data-ph="{selection}">{selection}</span>
            <span class="ph" data-ph="{query}">{query}</span>
          </div>
        </div>
      </div>
      <div class="card-actions">
        <button data-act="up" title="上移">↑ 上移</button>
        <button data-act="down" title="下移">↓ 下移</button>
        <button data-act="vis">${hidden ? '加入弹窗' : '移出弹窗'}</button>
        <button class="danger" data-act="del">${cmd.builtin ? '重置此项' : '删除'}</button>
      </div>
    `;

    // 字段编辑：即时写回内存对象 + 防抖保存
    card.querySelectorAll('[data-f]').forEach(el => {
      el.addEventListener('input', () => { cmd[el.dataset.f] = el.value; scheduleSave(); });
      el.addEventListener('change', () => { cmd[el.dataset.f] = el.value; scheduleSave(); });
    });
    // 占位符点击 → 插入到提示词末尾
    const ta = card.querySelector('[data-f="promptTemplate"]');
    card.querySelectorAll('.ph').forEach(ph => {
      ph.addEventListener('click', () => {
        const pos = ta.selectionStart ?? ta.value.length;
        ta.value = ta.value.slice(0, pos) + ph.dataset.ph + ta.value.slice(pos);
        cmd.promptTemplate = ta.value;
        ta.focus();
      });
    });

    // 上移 / 下移（边界上禁用，避免点了没反应却不知道是到头了）
    const up = card.querySelector('[data-act="up"]');
    const down = card.querySelector('[data-act="down"]');
    up.disabled = i === 0;
    down.disabled = i === commands.length - 1;
    up.addEventListener('click', () => reorder(i, i - 1));
    down.addEventListener('click', () => reorder(i, i + 1));

    // 移出/加入弹窗 —— 不是删除
    card.querySelector('[data-act="vis"]').addEventListener('click', async () => {
      prefs = togglePopupVisibility(cmd.id, prefs);
      await saveCommandPrefs(prefs);
      render();
      status(hidden ? '已加入弹窗' : '已移出弹窗（指令保留，可在下方加回）');
    });

    // 删除 / 重置
    card.querySelector('[data-act="del"]').addEventListener('click', async () => {
      if (cmd.builtin) {
        // 内置项不能删，重置为默认集里的同 id 项
        await resetOne(cmd.id);
      } else {
        commands.splice(i, 1);
        // 删掉的指令要把它的「移出」标记一起清掉，否则 id 集合里会留垃圾
        prefs = pruneHiddenIds(prefs, commands.map(c => c.id));
        await persistAll();
        render();
      }
    });

    // 拖拽排序
    card.addEventListener('dragstart', (e) => {
      dragFromIndex = i;
      card.classList.add('dragging');
      try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(i)); } catch {}
    });
    card.addEventListener('dragend', () => {
      dragFromIndex = null;
      card.classList.remove('dragging');
      list.querySelectorAll('.drop-target').forEach(n => n.classList.remove('drop-target'));
    });
    card.addEventListener('dragover', (e) => {
      if (dragFromIndex === null || dragFromIndex === i) return;
      e.preventDefault();
      card.classList.add('drop-target');
    });
    card.addEventListener('dragleave', () => card.classList.remove('drop-target'));
    card.addEventListener('drop', (e) => {
      e.preventDefault();
      card.classList.remove('drop-target');
      if (dragFromIndex === null) return;
      reorder(dragFromIndex, i);
    });

    list.appendChild(card);
  });

  renderHiddenSection();
}

/**
 * 「已移出弹窗」区：把这些指令列出来，一键加回。
 *
 * 单独成区的原因：移出之后它们的卡片还在主列表里（带「已移出」标记），但如果
 * 指令很多，用户会想「有哪些被移出了」——这里给一份直接的清单，不用一条条去找。
 */
function renderHiddenSection() {
  const wrap = $('hiddenSection');
  if (!wrap) return;
  const hiddenCmds = prefs.hiddenIds
    .map(id => commands.find(c => c.id === id))
    .filter(Boolean);

  if (!hiddenCmds.length) {
    wrap.style.display = 'none';
    wrap.innerHTML = '';
    return;
  }
  wrap.style.display = '';
  wrap.innerHTML = `
    <div class="hidden-head">已移出弹窗（${hiddenCmds.length} 条，指令本身仍在右键菜单/选中工具条里可用）</div>
    <div class="hidden-list" id="hiddenList"></div>
  `;
  const hl = $('hiddenList');
  for (const cmd of hiddenCmds) {
    const row = document.createElement('div');
    row.className = 'hidden-row';
    row.innerHTML = `
      <span style="font-size:15px">${escapeHtml(cmd.icon || '⚙️')}</span>
      <span class="hidden-name">${escapeHtml(cmd.label || '(未命名)')}</span>
      <button data-id="${escapeAttr(cmd.id)}">加回弹窗</button>
    `;
    row.querySelector('button').addEventListener('click', async () => {
      prefs = togglePopupVisibility(cmd.id, prefs);
      await saveCommandPrefs(prefs);
      render();
      status('已加入弹窗');
    });
    hl.appendChild(row);
  }
}

/** 上下移 / 拖拽都落到这里：改 commands 次序 → 落库 → 重绘。 */
async function reorder(from, to) {
  const next = moveItem(commands, from, to);
  // 位置没变就别白写一次 storage、也别重绘（会打断正在编辑的输入）
  if (next.every((c, i) => c === commands[i])) return;
  commands = next;
  await saveCommands(commands);
  render();
}

/** 展示数量：读写 popupCommandLimit。0 = 不限。 */
function renderLimit() {
  const input = $('limitInput');
  if (!input) return;
  input.value = String(prefs.limit);
  const summary = $('limitSummary');
  if (summary) summary.textContent = popupSummary();
}

async function applyLimit(raw) {
  prefs = { ...prefs, limit: normalizeLimit(raw) };
  await saveCommandPrefs(prefs);
  renderLimit();
  render();
}

async function resetOne(id) {
  // 从默认集取该 id 的原始定义覆盖当前项
  const def = DEFAULT_COMMANDS.find(c => c.id === id);
  if (!def) return;
  const idx = commands.findIndex(c => c.id === id);
  if (idx >= 0) commands[idx] = { ...def };
  await persistAll();
  render();
  status('已重置');
}

async function persist() {
  await saveCommands(commands);
}

/** 指令与偏好一起落库（两者有联动时用，比如删除） */
async function persistAll() {
  await Promise.all([saveCommands(commands), saveCommandPrefs(prefs)]);
}

// 编辑字段时防抖保存，避免每次按键都写 storage
let saveTimer = null;
function scheduleSave() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => { void persist(); status('已保存'); }, 600);
}

async function addCommand() {
  commands.push({
    id: genId(), label: '新指令', icon: '⚙️', scope: 'page',
    promptTemplate: '{content}', builtin: false,
  });
  await persist();
  render();
  // 滚到底部新卡片
  window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
}

async function resetAll() {
  if (!confirm('确定恢复默认指令集？所有自定义指令、顺序和弹窗展示设置都会被清除。')) return;
  await resetCommands();
  commands = await readCommands();
  prefs = await readCommandPrefs();
  render();
  renderLimit();
  status('已恢复默认');
}

// 只刷新各卡片的 model 下拉，不整树 render，避免冲掉用户正在编辑的 textarea 焦点/未存输入
function refreshModelSelects() {
  document.querySelectorAll('select[data-f="model"]').forEach((sel, i) => {
    const cmd = commands[i];
    if (!cmd) return;
    sel.innerHTML = modelOptions(cmd.model || '');
  });
}

async function loadModels() {
  try {
    const resp = await chrome.runtime.sendMessage({ type: 'list-models' });
    if (resp?.ok && Array.isArray(resp.models)) {
      models = resp.models;
      refreshModelSelects();  // 仅更新下拉选项，保留正在编辑的输入
    }
  } catch { /* 拉不到就只能手填，忽略 */ }
}

$('add').addEventListener('click', addCommand);
$('reset').addEventListener('click', resetAll);

// 展示数量：输入即应用（防抖），并在失焦时归位成规范化后的值
let limitTimer = null;
$('limitInput')?.addEventListener('input', (e) => {
  const raw = e.target.value;
  if (limitTimer) clearTimeout(limitTimer);
  limitTimer = setTimeout(() => { void applyLimit(raw); }, 400);
});
$('limitInput')?.addEventListener('change', (e) => {
  if (limitTimer) { clearTimeout(limitTimer); limitTimer = null; }
  void applyLimit(e.target.value);
});

// 离开/切走时保存一次（编辑 input 时已写回，但 promptTemplate 可能没触发 change）
window.addEventListener('blur', () => { void persist(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) void persist(); });

(async function init() {
  commands = await readCommands();
  prefs = await readCommandPrefs();
  render();
  renderLimit();
  loadModels();
})();
