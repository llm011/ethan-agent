import { test, expect } from '@playwright/test';

// Helper: set the auth token in localStorage and cookie so the app
// skips the login screen on load.
async function setAuthToken(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    const TOKEN = 'ethan-dev-token';
    localStorage.setItem('ethan_token', TOKEN);
    document.cookie = `ethan_token=${encodeURIComponent(TOKEN)}; max-age=2592000; path=/`;
  });
}

test.describe('Ethan Web UI E2E Tests', () => {
  test.beforeEach(async ({ page }) => {
    // Inject auth token before any page script runs, then navigate.
    await setAuthToken(page);
    await page.goto('/');
    // Wait until the loading spinner disappears — the app either shows the
    // chat view or (if the backend is down) stays on the loading screen.
    // Either way, we proceed; individual tests assert what they need.
    await page.waitForLoadState('networkidle');
  });

  // ── Test 1: Chat flow ────────────────────────────────────────────────────

  test('Test 1: Chat flow - sidebar shows latest sessions header', async ({ page }) => {
    // The sidebar is always rendered inside ChatView once authenticated.
    // If the backend is unreachable we may still see the sidebar structure.
    await expect(page).toHaveTitle(/Ethan/);

    // "最新对话" section header is rendered in the sidebar when not searching.
    await expect(page.getByText('最新对话')).toBeVisible();
  });

  // ── Test 2: Memory view ──────────────────────────────────────────────────

  test('Test 2: Memory view - 个人信息 tab loads', async ({ page }) => {
    // Click the Memory button in the sidebar navigation.
    await page.getByRole('button', { name: /记忆.*Memory/ }).click();

    // The default tab (个人信息) is rendered in the memory view header.
    await expect(page.getByRole('button', { name: '个人信息' })).toBeVisible();
  });

  test('Test 3: Memory view - 苏念记忆 tab loads', async ({ page }) => {
    await page.getByRole('button', { name: /记忆.*Memory/ }).click();

    // Confirm the default tab is active first.
    await expect(page.getByRole('button', { name: '个人信息' })).toBeVisible();

    // Click the companion tab.
    await page.getByRole('button', { name: '苏念记忆' }).click();

    // The companion tab should now be visible in the header.
    await expect(page.getByRole('button', { name: '苏念记忆' })).toBeVisible();
  });

  // ── Test 3: Schedule view ────────────────────────────────────────────────

  test('Test 4: Schedule view - page loads without error', async ({ page }) => {
    await page.getByRole('button', { name: /定时任务.*Schedule/ }).click();

    // The schedule view renders a refresh button and a loading/content area.
    // We verify neither a crash page nor an unhandled error is shown.
    // The simplest stable check: no "Application error" text.
    await expect(page.getByText(/Application error/i)).not.toBeVisible();

    // The schedule view header area uses a RefreshCw icon button; the
    // surrounding page should be rendered (body visible).
    await expect(page.locator('body')).toBeVisible();
  });

  // ── Test 4: Knowledge view ───────────────────────────────────────────────

  test('Test 5: Knowledge view - search bar is present', async ({ page }) => {
    await page.getByRole('button', { name: /知识库.*Knowledge/ }).click();

    // The knowledge view renders an Input with placeholder "Search knowledge..."
    await expect(page.getByPlaceholder('Search knowledge...')).toBeVisible();
  });

  // ── Test 5: Settings view ────────────────────────────────────────────────

  test('Test 6: Settings view - General tab is visible', async ({ page }) => {
    await page.getByRole('button', { name: /设置.*Settings/ }).click();

    // The settings sidebar renders "通用设置 (General)" as the first tab.
    await expect(page.getByText('通用设置 (General)')).toBeVisible();
  });

  // ── Test 6: Session search ───────────────────────────────────────────────

  test('Test 7: Session search - input accepts text', async ({ page }) => {
    const searchInput = page.getByPlaceholder('搜索历史...');
    await expect(searchInput).toBeVisible();

    await searchInput.fill('test query');

    // Verify the value was accepted.
    await expect(searchInput).toHaveValue('test query');
  });

  // ── Test 7: All sessions grid ────────────────────────────────────────────

  test('Test 8: All sessions grid - cards grid is visible after navigation', async ({ page }) => {
    // The "全部对话" button is a React SPA navigation (sets view state),
    // not a real URL change. Click it and check for AllSessionsView content.
    await page.getByRole('button', { name: /全部对话/ }).click();

    // AllSessionsView renders a search input with placeholder "搜索对话..."
    // or the sessions grid / empty state. Wait for any of these to confirm
    // the view mounted without crashing.
    const searchBar = page.getByPlaceholder('搜索对话...');
    const grid = page.locator('.grid').first();
    const emptyState = page.getByText(/No sessions found|暂无对话/i);

    await expect(searchBar.or(grid).or(emptyState)).toBeVisible({ timeout: 8000 });
  });
});
