# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: main.spec.ts >> Ethan Web UI E2E Tests >> Test 2: Memory flow
- Location: tests/main.spec.ts:24:7

# Error details

```
Error: page.goto: net::ERR_CONNECTION_REFUSED at http://localhost:3000/
Call log:
  - navigating to "http://localhost:3000/", waiting until "load"

```

# Test source

```ts
  1  | import { test, expect } from '@playwright/test';
  2  | 
  3  | test.describe('Ethan Web UI E2E Tests', () => {
  4  |   test.beforeEach(async ({ page }) => {
  5  |     // Navigate to the base URL
> 6  |     await page.goto('/');
     |                ^ Error: page.goto: net::ERR_CONNECTION_REFUSED at http://localhost:3000/
  7  |   });
  8  | 
  9  |   test('Test 1: Chat flow', async ({ page }) => {
  10 |     // Click "对话" (Chat) in the sidebar. Look for the link with href "/" or text "对话"
  11 |     // Since it's a generic word, let's look for a navigation element that has this text
  12 |     const chatLink = page.getByRole('link', { name: '对话' });
  13 |     if (await chatLink.isVisible()) {
  14 |       await chatLink.click();
  15 |     }
  16 | 
  17 |     // Verify the title says "Ethan"
  18 |     await expect(page).toHaveTitle(/Ethan/);
  19 | 
  20 |     // Verify there is "最新对话" text visible
  21 |     await expect(page.getByText('最新对话')).toBeVisible();
  22 |   });
  23 | 
  24 |   test('Test 2: Memory flow', async ({ page }) => {
  25 |     // Click "记忆 (Memory)" in the sidebar
  26 |     await page.getByRole('link', { name: '记忆' }).click();
  27 | 
  28 |     // Verify the "长期记忆 (Facts)" tab is visible
  29 |     await expect(page.getByText('长期记忆 (Facts)')).toBeVisible();
  30 | 
  31 |     // Wait for the memory cards to load - assuming there's a grid or specific items
  32 |     // If the list might be empty, we just wait for the container or the fact that no error is shown
  33 |     // We'll wait for any list item or a specific layout container
  34 |     const memoryGrid = page.locator('.grid').first();
  35 |     await expect(memoryGrid).toBeVisible();
  36 | 
  37 |     // Click on the first card (assuming cards are actionable items)
  38 |     const firstCard = memoryGrid.locator('> div').first();
  39 | 
  40 |     // Wait for at least one card to exist (if data is populated)
  41 |     // If we have data, we click and verify detail view
  42 |     if (await firstCard.isVisible()) {
  43 |       await firstCard.click();
  44 | 
  45 |       // Verify transition to detail view
  46 |       // This could be "返回记忆列表" or "记忆详情"
  47 |       const detailIndicator = page.locator('text=返回记忆列表').or(page.locator('text=记忆详情'));
  48 |       await expect(detailIndicator).toBeVisible();
  49 |     }
  50 |   });
  51 | });
  52 | 
```