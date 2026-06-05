# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: tests/electron-smoke.spec.js >> BetterFingers Electron App Tests >> Launches and shows main dashboard header
- Location: tests/electron-smoke.spec.js:41:3

# Error details

```
Error: electron.launch: Target page, context or browser has been closed
Browser logs:

<launching> /home/roygslade/Desktop/BetterFingers/app/node_modules/electron/dist/electron -r /home/roygslade/Desktop/BetterFingers/app/node_modules/playwright-core/lib/server/electron/loader.js --no-sandbox --inspect=0 --remote-debugging-port=0 .
<launched> pid=34121
[pid=34121][err] Debugger listening on ws://127.0.0.1:44805/d4622c42-785e-4bf7-b792-961cdae7869e
[pid=34121][err] For help, see: https://nodejs.org/en/docs/inspector
[pid=34121][err] Debugger attached.
[pid=34121][err] 
[pid=34121][err] DevTools listening on ws://127.0.0.1:40703/devtools/browser/56869a2f-0d4b-48e5-8e15-eeac26ec091c
Call log:
  - <launching> /home/roygslade/Desktop/BetterFingers/app/node_modules/electron/dist/electron -r /home/roygslade/Desktop/BetterFingers/app/node_modules/playwright-core/lib/server/electron/loader.js --no-sandbox --inspect=0 --remote-debugging-port=0 .
  - <launched> pid=34121
  - [pid=34121][err] Debugger listening on ws://127.0.0.1:44805/d4622c42-785e-4bf7-b792-961cdae7869e
  - [pid=34121][err] For help, see: https://nodejs.org/en/docs/inspector
  - <ws connecting> ws://127.0.0.1:44805/d4622c42-785e-4bf7-b792-961cdae7869e
  - <ws connected> ws://127.0.0.1:44805/d4622c42-785e-4bf7-b792-961cdae7869e
  - [pid=34121][err] Debugger attached.
  - [pid=34121][err]
  - [pid=34121][err] DevTools listening on ws://127.0.0.1:40703/devtools/browser/56869a2f-0d4b-48e5-8e15-eeac26ec091c
  - <ws connecting> ws://127.0.0.1:40703/devtools/browser/56869a2f-0d4b-48e5-8e15-eeac26ec091c
  - <ws connected> ws://127.0.0.1:40703/devtools/browser/56869a2f-0d4b-48e5-8e15-eeac26ec091c
  - <ws disconnected> ws://127.0.0.1:44805/d4622c42-785e-4bf7-b792-961cdae7869e code=1005 reason=
  - <ws disconnected> ws://127.0.0.1:40703/devtools/browser/56869a2f-0d4b-48e5-8e15-eeac26ec091c code=1006 reason=
  - [pid=34121] <kill>
  - [pid=34121] <will force kill>
  - [pid=34121] <process did exit: exitCode=0, signal=null>
  - [pid=34121] starting temporary directories cleanup
  - [pid=34121] finished temporary directories cleanup

```

# Test source

```ts
  1   | const { test, expect } = require('@playwright/test');
  2   | const { _electron: electron } = require('playwright');
  3   | const path = require('node:path');
  4   | 
  5   | test.describe('BetterFingers Electron App Tests', () => {
  6   |   let app;
  7   |   let window;
  8   | 
  9   |   test.beforeAll(async () => {
  10  |     // Launch Electron app
> 11  |     app = await electron.launch({
      |           ^ Error: electron.launch: Target page, context or browser has been closed
  12  |       cwd: path.resolve(__dirname, '..'),
  13  |       args: ['.'],
  14  |       env: {
  15  |         ...process.env,
  16  |         BETTERFINGERS_PYTHON: 'python3', // Use system python3
  17  |       },
  18  |     });
  19  | 
  20  |     // Wait for the main window (index.html) to open and load
  21  |     const windows = app.windows();
  22  |     window = windows.find(w => w.url().includes('index.html'));
  23  |     if (!window) {
  24  |       window = await app.waitForEvent('window', {
  25  |         predicate: (w) => w.url().includes('index.html'),
  26  |         timeout: 20000,
  27  |       });
  28  |     }
  29  | 
  30  |     await window.waitForLoadState('domcontentloaded');
  31  |     await window.waitForSelector('#backendStatus', { state: 'attached', timeout: 15000 });
  32  |   });
  33  | 
  34  |   test.afterAll(async () => {
  35  |     // Close Electron app
  36  |     if (app) {
  37  |       await app.close();
  38  |     }
  39  |   });
  40  | 
  41  |   test('Launches and shows main dashboard header', async () => {
  42  |     await expect(window.locator('text=Backend Status Dashboard')).toBeVisible();
  43  |     await expect(window.locator('#backendStatus')).toBeVisible();
  44  |   });
  45  | 
  46  |   test('Backend transitions to active/ready state', async () => {
  47  |     const statusLocator = window.locator('#backendStatus');
  48  |     await expect(statusLocator).toHaveText(/ready|active|running|external/i, { timeout: 15000 });
  49  |   });
  50  | 
  51  |   test('Tab navigation switching works', async () => {
  52  |     await expect(window.locator('#tabDashboard')).toBeVisible();
  53  |     await expect(window.locator('#tabSettings')).not.toBeVisible();
  54  | 
  55  |     await window.click('#tabButtonSettings');
  56  |     await expect(window.locator('#tabSettings')).toBeVisible();
  57  |     await expect(window.locator('#tabDashboard')).not.toBeVisible();
  58  | 
  59  |     await window.click('#tabButtonModels');
  60  |     await expect(window.locator('#tabModels')).toBeVisible();
  61  |     await expect(window.locator('#tabSettings')).not.toBeVisible();
  62  | 
  63  |     await window.click('#tabButtonDiagnostics');
  64  |     await expect(window.locator('#tabDiagnostics')).toBeVisible();
  65  |     await expect(window.locator('#tabModels')).not.toBeVisible();
  66  |   });
  67  | 
  68  |   test('Settings page renders and category switching works', async () => {
  69  |     await window.click('#tabButtonSettings');
  70  | 
  71  |     // Verify a couple of nav buttons are visible
  72  |     const generalNavBtn = window.locator('.settings-nav-button[data-section="general"]');
  73  |     const recordingNavBtn = window.locator('.settings-nav-button[data-section="recording"]');
  74  |     await expect(generalNavBtn).toBeVisible();
  75  |     await expect(recordingNavBtn).toBeVisible();
  76  | 
  77  |     // General section is active by default
  78  |     await expect(window.locator('.settings-section[data-section="general"]')).toHaveClass(/active/);
  79  |     await expect(window.locator('.settings-section[data-section="recording"]')).toHaveClass(/hidden/);
  80  | 
  81  |     // Switch to Recording section
  82  |     await recordingNavBtn.click();
  83  |     await expect(window.locator('.settings-section[data-section="recording"]')).toHaveClass(/active/);
  84  |     await expect(window.locator('.settings-section[data-section="general"]')).toHaveClass(/hidden/);
  85  |   });
  86  | 
  87  |   test('Search filters rows', async () => {
  88  |     await window.click('#tabButtonSettings');
  89  |     const searchInput = window.locator('#settingsSearchInput');
  90  |     await expect(searchInput).toBeVisible();
  91  | 
  92  |     // Query a specific settings row
  93  |     await searchInput.fill('instant typing');
  94  |     
  95  |     // Search Results header should appear
  96  |     await expect(window.locator('#settingsSearchHeader')).toBeVisible();
  97  | 
  98  |     // Instant Typing row should be visible
  99  |     const instantTypingRow = window.locator('.setting-row:has-text("Instant Typing")');
  100 |     await expect(instantTypingRow).toBeVisible();
  101 | 
  102 |     // Non-matching row should be hidden
  103 |     const whisperChunkRow = window.locator('.setting-row:has-text("Whisper Chunk Size")');
  104 |     await expect(whisperChunkRow).not.toBeVisible();
  105 | 
  106 |     // Clear search
  107 |     await searchInput.fill('');
  108 |     await expect(window.locator('#settingsSearchHeader')).toHaveClass(/hidden/);
  109 |   });
  110 | 
  111 |   test('Invalid token limit blocks save', async () => {
```