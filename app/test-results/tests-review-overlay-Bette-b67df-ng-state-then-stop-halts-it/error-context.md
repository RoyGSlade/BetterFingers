# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: tests/review-overlay.spec.js >> BetterFingers Review Overlay Tests >> Read button calls TTS path and enters speaking state, then stop halts it
- Location: tests/review-overlay.spec.js:83:3

# Error details

```
Error: expect(locator).toHaveText(expected) failed

Locator: locator('#statusBadge')
Expected pattern: /Draft Pending/i
Received string:  "Speaking"
Timeout: 5000ms

Call log:
  - Expect "toHaveText" with timeout 5000ms
  - waiting for locator('#statusBadge')
    14 × locator resolved to <span id="statusBadge" class="status-badge state-speaking">Speaking</span>
       - unexpected value "Speaking"

```

```yaml
- text: Speaking
```

# Test source

```ts
  1   | const { test, expect } = require('@playwright/test');
  2   | const { _electron: electron } = require('playwright');
  3   | const path = require('node:path');
  4   | 
  5   | test.describe('BetterFingers Review Overlay Tests', () => {
  6   |   let app;
  7   |   let mainWindow;
  8   |   let reviewWindow;
  9   | 
  10  |   test.beforeAll(async () => {
  11  |     // Launch Electron app
  12  |     app = await electron.launch({
  13  |       cwd: path.resolve(__dirname, '..'),
  14  |       args: ['.'],
  15  |       env: {
  16  |         ...process.env,
  17  |         BETTERFINGERS_PYTHON: 'python3', // Use system python3
  18  |       },
  19  |     });
  20  | 
  21  |     // Wait for the main window (index.html) to open and load
  22  |     const windows = app.windows();
  23  |     mainWindow = windows.find(w => w.url().includes('index.html'));
  24  |     if (!mainWindow) {
  25  |       mainWindow = await app.waitForEvent('window', {
  26  |         predicate: (w) => w.url().includes('index.html'),
  27  |         timeout: 20000,
  28  |       });
  29  |     }
  30  | 
  31  |     await mainWindow.waitForLoadState('domcontentloaded');
  32  |     await mainWindow.waitForSelector('#backendStatus', { state: 'attached', timeout: 15000 });
  33  |     const statusLocator = mainWindow.locator('#backendStatus');
  34  |     await expect(statusLocator).toHaveText(/ready|active|running|external/i, { timeout: 15000 });
  35  |     
  36  |     // Wait for WebSocket stream connection to be fully connected
  37  |     const wsConnection = mainWindow.locator('#wsConnection');
  38  |     await expect(wsConnection).toHaveText(/connected/i, { timeout: 15000 });
  39  |   });
  40  | 
  41  |   test.afterAll(async () => {
  42  |     // Close Electron app
  43  |     if (app) {
  44  |       await app.close();
  45  |     }
  46  |   });
  47  | 
  48  |   test('Review overlay opens and displays correct elements when mock draft is triggered', async () => {
  49  |     // Trigger a mock draft via FastAPI endpoint
  50  |     const token = await mainWindow.evaluate(() => window.betterFingers.authToken);
  51  |     const response = await fetch('http://127.0.0.1:8000/drafts/test-mock', { 
  52  |       method: 'POST',
  53  |       headers: { 'Authorization': `Bearer ${token}` }
  54  |     });
  55  |     expect(response.ok).toBe(true);
  56  | 
  57  |     // Wait for review window to open
  58  |     reviewWindow = await app.waitForEvent('window', {
  59  |       predicate: (w) => w.url().includes('review-overlay.html'),
  60  |       timeout: 10000,
  61  |     });
  62  | 
  63  |     await reviewWindow.waitForLoadState('domcontentloaded');
  64  | 
  65  |     // Confirm state badge exists and shows 'Draft Pending'
  66  |     const statusBadge = reviewWindow.locator('#statusBadge');
  67  |     await expect(statusBadge).toBeVisible();
  68  |     await expect(statusBadge).toHaveText(/Draft Pending/i);
  69  | 
  70  |     // Confirm TTS backend badge exists
  71  |     const ttsBadge = reviewWindow.locator('#ttsBackendBadge');
  72  |     await expect(ttsBadge).toBeVisible();
  73  |     await expect(ttsBadge).toHaveText(/TTS:/i);
  74  | 
  75  |     // Confirm essential buttons exist
  76  |     await expect(reviewWindow.locator('#acceptButton')).toBeVisible();
  77  |     await expect(reviewWindow.locator('#changeButton')).toBeVisible();
  78  |     await expect(reviewWindow.locator('#instructButton')).toBeVisible();
  79  |     await expect(reviewWindow.locator('#readButton')).toBeVisible();
  80  |     await expect(reviewWindow.locator('#cancelButton')).toBeVisible();
  81  |   });
  82  | 
  83  |   test('Read button calls TTS path and enters speaking state, then stop halts it', async () => {
  84  |     const readButton = reviewWindow.locator('#readButton');
  85  |     const statusBadge = reviewWindow.locator('#statusBadge');
  86  | 
  87  |     // Click Read button
  88  |     await readButton.click();
  89  | 
  90  |     // The status badge should visibly change to 'Speaking'
  91  |     await expect(statusBadge).toHaveText(/Speaking/i);
  92  |     // The button text should change to 'Stop'
  93  |     await expect(readButton).toHaveText(/Stop/i);
  94  | 
  95  |     // Clicking Stop should halt TTS and return to pending/normal state
  96  |     await readButton.click();
> 97  |     await expect(statusBadge).toHaveText(/Draft Pending/i);
      |                               ^ Error: expect(locator).toHaveText(expected) failed
  98  |     await expect(readButton).toHaveText(/Read/i);
  99  |   });
  100 | 
  101 |   test('Change button triggers rewrite and enters rewriting state', async () => {
  102 |     const changeButton = reviewWindow.locator('#changeButton');
  103 |     const statusBadge = reviewWindow.locator('#statusBadge');
  104 | 
  105 |     // Click Change button
  106 |     await changeButton.click();
  107 | 
  108 |     // It should transiently enter 'Rewriting' or quickly complete to 'Rewritten'
  109 |     await expect(statusBadge).toHaveText(/Rewriting|Rewritten/i);
  110 |   });
  111 | 
  112 |   test('Instruct button toggles custom instruction row and typing run rewrite works', async () => {
  113 |     const instructButton = reviewWindow.locator('#instructButton');
  114 |     const instructionRow = reviewWindow.locator('#instructionRow');
  115 |     const instructionText = reviewWindow.locator('#instructionText');
  116 |     const runInstructionButton = reviewWindow.locator('#runInstructionButton');
  117 |     const statusBadge = reviewWindow.locator('#statusBadge');
  118 | 
  119 |     // Verify initially hidden
  120 |     await expect(instructionRow).toHaveClass(/hidden/);
  121 | 
  122 |     // Click Instruct button to reveal it
  123 |     await instructButton.click();
  124 |     await expect(instructionRow).not.toHaveClass(/hidden/);
  125 | 
  126 |     // Type custom instruction
  127 |     await instructionText.fill('make it professional');
  128 | 
  129 |     // Click Rewrite
  130 |     await runInstructionButton.click();
  131 | 
  132 |     // Verify it moves to rewriting or rewritten state
  133 |     await expect(statusBadge).toHaveText(/Rewriting|Rewritten/i);
  134 |   });
  135 | 
  136 |   test('Cancel button hides overlay', async () => {
  137 |     const cancelButton = reviewWindow.locator('#cancelButton');
  138 |     
  139 |     // Click Cancel
  140 |     await cancelButton.click();
  141 | 
  142 |     // Verify Electron window is hidden
  143 |     let isVisible = true;
  144 |     for (let i = 0; i < 10; i++) {
  145 |       isVisible = await app.evaluate(({ BrowserWindow }) => {
  146 |         const win = BrowserWindow.getAllWindows().find(w => w.getTitle() === 'BetterFingers Review');
  147 |         return win ? win.isVisible() : false;
  148 |       });
  149 |       if (!isVisible) break;
  150 |       await new Promise(resolve => setTimeout(resolve, 300));
  151 |     }
  152 |     expect(isVisible).toBe(false);
  153 |   });
  154 | 
  155 |   test('Dashboard still functions normally after overlay closes', async () => {
  156 |     // Verify dashboard is still visible and responsive
  157 |     await expect(mainWindow.locator('text=Backend Status Dashboard')).toBeVisible();
  158 |     
  159 |     // Check that we can navigate
  160 |     await mainWindow.click('#tabButtonSettings');
  161 |     await expect(mainWindow.locator('#tabSettings')).toBeVisible();
  162 |   });
  163 | });
  164 | 
```