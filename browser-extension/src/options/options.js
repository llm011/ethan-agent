/* eslint-disable */
// 指令管理页：增删改自定义指令、选 model。读写 chrome.storage.local 的 'commands'。
// model 候选从 background 转发的 /api/models 拉取（拉不到也能手填）。

import { readCommands, saveCommands, resetCommands, DEFAULT_COMMANDS } from '../shared';

const $ = id => document.getElementById(id);

let commands = [];
let models = [];   // [{id, description}]

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

function render() {
  const list = $('list');
  list.innerHTML = '';
  commands.forEach((cmd, i) => {
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <div class="card-head">
        <span style="font-size:18px">${escapeHtml(cmd.icon || '⚙️')}</span>
        <span class="name">${escapeHtml(cmd.label || '(未命名)')}</span>
        ${cmd.builtin ? '<span class="badge">内置</span>' : '<span class="badge">自定义</span>'}
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
    // 删除 / 重置
    card.querySelector('[data-act="del"]').addEventListener('click', () => {
      if (cmd.builtin) {
        // 内置项不能删，重置为默认集里的同 id 项
        resetOne(cmd.id);
      } else {
        commands.splice(i, 1);
        persist();
        render();
      }
    });

    list.appendChild(card);
  });
}

async function resetOne(id) {
  // 从默认集取该 id 的原始定义覆盖当前项
  const def = DEFAULT_COMMANDS.find(c => c.id === id);
  if (!def) return;
  const idx = commands.findIndex(c => c.id === id);
  if (idx >= 0) commands[idx] = { ...def };
  await persist();
  render();
  status('已重置');
}

async function persist() {
  await saveCommands(commands);
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
  if (!confirm('确定恢复默认指令集？所有自定义指令将被清除。')) return;
  await resetCommands();
  commands = await readCommands();
  render();
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

// 保存按钮：每次编辑已即时写回内存 + persist，这里做一次显式保存兜底
$('add').addEventListener('click', addCommand);
$('reset').addEventListener('click', resetAll);

// 离开/切走时保存一次（编辑 input 时已写回，但 promptTemplate 可能没触发 change）
window.addEventListener('blur', () => { void persist(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) void persist(); });

(async function init() {
  commands = await readCommands();
  render();
  loadModels();
})();
