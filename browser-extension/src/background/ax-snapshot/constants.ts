export const INTERACTIVE_ROLES = new Set([
  'button',
  'link',
  'textbox',
  'combobox',
  'checkbox',
  'radio',
  'switch',
  'menuitem',
  'option',
  'tab',
  'treeitem',
  'Iframe',
]);
export const CONTENT_ROLES = new Set([
  'heading',
  'cell',
  'row',
  'paragraph',
  'text',
  'StaticText',
  'LabelText',
]);
export const STRUCTURAL_ROLES = new Set([
  'generic',
  'group',
  'list',
  'listitem',
  'navigation',
  'main',
  'banner',
  'contentinfo',
  'RootWebArea',
  'WebArea',
]);
export const MAX_NAME_LENGTH = 100;
export const EMPTY_SNAPSHOT = '(empty page)';
export const EMPTY_INTERACTIVE_SNAPSHOT = '(no interactive elements)';

// 不渲染的 role：InlineTextBox 是 StaticText 的子节点，文本完全重复
export const SKIP_ROLES = new Set(['InlineTextBox']);
