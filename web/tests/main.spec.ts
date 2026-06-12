import { test, expect } from '@playwright/test';

test.describe('Ethan Web UI E2E Tests', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the base URL
    await page.goto('/');
  });

  test('Test 1: Chat flow', async ({ page }) => {
    // Click "对话" (Chat) in the sidebar. Look for the link with href "/" or text "对话"
    // Since it's a generic word, let's look for a navigation element that has this text
    const chatLink = page.getByRole('link', { name: '对话' });
    if (await chatLink.isVisible()) {
      await chatLink.click();
    }

    // Verify the title says "Ethan"
    await expect(page).toHaveTitle(/Ethan/);

    // Verify there is "最新对话" text visible
    await expect(page.getByText('最新对话')).toBeVisible();
  });

  test('Test 2: Memory flow', async ({ page }) => {
    // Click "记忆 (Memory)" in the sidebar
    await page.getByRole('link', { name: '记忆' }).click();

    // Verify the "长期记忆 (Facts)" tab is visible
    await expect(page.getByText('长期记忆 (Facts)')).toBeVisible();

    // Wait for the memory cards to load - assuming there's a grid or specific items
    // If the list might be empty, we just wait for the container or the fact that no error is shown
    // We'll wait for any list item or a specific layout container
    const memoryGrid = page.locator('.grid').first();
    await expect(memoryGrid).toBeVisible();

    // Click on the first card (assuming cards are actionable items)
    const firstCard = memoryGrid.locator('> div').first();

    // Wait for at least one card to exist (if data is populated)
    // If we have data, we click and verify detail view
    if (await firstCard.isVisible()) {
      await firstCard.click();

      // Verify transition to detail view
      // This could be "返回记忆列表" or "记忆详情"
      const detailIndicator = page.locator('text=返回记忆列表').or(page.locator('text=记忆详情'));
      await expect(detailIndicator).toBeVisible();
    }
  });
});
