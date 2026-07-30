/* eslint-disable */
// Cookie 弹窗自动关闭助手
// 注入到 Ethan session 的 tab 中，检测并关闭常见的 cookie consent 对话框。
// 优先点击 "Reject"/"Decline"/"仅必要" 按钮，退而求其次点击 "Accept"/"同意"。

interface CookieRule {
  // CSS 选择器定位按钮
  selector: string;
  // 优先级：reject > accept（优先拒绝追踪）
  type: 'reject' | 'accept';
}

// 常见 cookie consent 平台的按钮选择器
const RULES: CookieRule[] = [
  // OneTrust
  { selector: '#onetrust-reject-all-handler', type: 'reject' },
  { selector: '#onetrust-accept-btn-handler', type: 'accept' },
  // Cookiebot
  { selector: '#CybotCookiebotDialogBodyButtonDeclineButton', type: 'reject' },
  { selector: '#CybotCookiebotDialogBodyLevelButtonLevelOptinDeclineAll', type: 'reject' },
  { selector: '#CybotCookiebotDialogBodyButtonAccept', type: 'accept' },
  // Cookie Consent JS (osano/insites)
  { selector: '.cc-deny', type: 'reject' },
  { selector: '.cc-accept-all', type: 'accept' },
  { selector: '.cc-btn.cc-dismiss', type: 'accept' },
  { selector: '#ccc-reject-settings', type: 'reject' },
  { selector: '#ccc-accept-all', type: 'accept' },
  // Sourcepoint
  { selector: 'button[title*="Reject"]', type: 'reject' },
  { selector: 'button[title*="Accept"]', type: 'accept' },
  // Quantcast
  { selector: '.qc-cmp2-summary-buttons button[mode="primary"]', type: 'accept' },
  { selector: '.qc-cmp2-summary-buttons button:nth-child(1)', type: 'reject' },
  // Didomi
  { selector: '#didomi-notice-disagree-button', type: 'reject' },
  { selector: '#didomi-notice-agree-button', type: 'accept' },
  // TrustArc
  { selector: '#truste-consent-button', type: 'accept' },
  { selector: '#truste-consent-required', type: 'reject' },
  // Sibbo
  { selector: '#sb-reject-all', type: 'reject' },
  { selector: '#sb-accept-all', type: 'accept' },
  // Generic
  { selector: '[data-testid="reject-all"]', type: 'reject' },
  { selector: '[data-testid="accept-all"]', type: 'accept' },
  { selector: '[data-testid="cookie-policy-dialog-reject-button"]', type: 'reject' },
  { selector: '[data-testid="cookie-policy-dialog-accept-button"]', type: 'accept' },
];

// 按文本匹配（兜底）
const TEXT_RULES: { text: string; type: 'reject' | 'accept' }[] = [
  { text: 'Reject all', type: 'reject' },
  { text: 'Reject All', type: 'reject' },
  { text: 'Decline all', type: 'reject' },
  { text: 'Decline All', type: 'reject' },
  { text: '仅限必要', type: 'reject' },
  { text: '仅必要', type: 'reject' },
  { text: '拒绝全部', type: 'reject' },
  { text: '拒绝', type: 'reject' },
  { text: '必要のみ', type: 'reject' },
  { text: 'Refuser', type: 'reject' },
  { text: 'Ablehnen', type: 'reject' },
  { text: 'Accept all', type: 'accept' },
  { text: 'Accept All', type: 'accept' },
  { text: '全部接受', type: 'accept' },
  { text: '同意', type: 'accept' },
  { text: 'I agree', type: 'accept' },
  { text: 'Got it', type: 'accept' },
  { text: 'OK', type: 'accept' },
  { text: '理解した', type: 'accept' },
];

const MAX_ATTEMPTS = 5;
const INTERVAL_MS = 2000;
let attempts = 0;

function tryClose(): boolean {
  // 先试 CSS 选择器规则
  const rejectBtns: HTMLElement[] = [];
  const acceptBtns: HTMLElement[] = [];

  for (const rule of RULES) {
    const els = document.querySelectorAll<HTMLElement>(rule.selector);
    els.forEach(el => {
      if (el.offsetParent !== null || el.getClientRects().length > 0) {  // 可见
        (rule.type === 'reject' ? rejectBtns : acceptBtns).push(el);
      }
    });
  }

  // 文本匹配兜底
  // 短 token（如 "OK"/"同意"/"拒绝"）只允许精确相等——用 includes 会误伤
  // "BOOKING"/"不同意" 之类的无关或语义相反按钮，在 Ethan 控制的 tab 上可能触发错误跳转/提交。
  // 仅长度 >=5 的明确短语（"Reject all"/"Accept all"/"I agree" 等）才放宽到 includes。
  const allBtns = document.querySelectorAll<HTMLElement>('button, a, [role="button"]');
  for (const btn of allBtns) {
    const text = (btn.textContent || '').trim();
    if (!text || text.length > 30) continue;
    for (const rule of TEXT_RULES) {
      const matched = text === rule.text
        || (rule.text.length >= 5 && text.includes(rule.text));
      if (matched) {
        if (btn.offsetParent !== null || btn.getClientRects().length > 0) {
          (rule.type === 'reject' ? rejectBtns : acceptBtns).push(btn);
        }
        break;
      }
    }
  }

  // 优先 reject，其次 accept
  const target = rejectBtns[0] || acceptBtns[0];
  if (target) {
    target.click();
    return true;
  }
  return false;
}

function tick() {
  if (attempts >= MAX_ATTEMPTS) return;
  attempts++;
  if (tryClose()) return;
  setTimeout(tick, INTERVAL_MS);
}

tick();

export {};
