import { chromium } from '@playwright/test';

const shot = async (page, name) => {
  await page.screenshot({ path: `/home/user/finora-mobile/shots/${name}.png` });
  console.log('shot:', name);
};

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
});
const errors = [];
page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message));
page.on('console', (m) => {
  if (m.type() === 'error') errors.push('CONSOLE: ' + m.text().slice(0, 200));
});

await page.goto('http://127.0.0.1:4321/', { waitUntil: 'networkidle' });
await page.waitForTimeout(1200);
await shot(page, '01-landing');

// search + autocomplete
const input = page.getByRole('combobox');
await input.tap();
await input.fill('appl');
await page.waitForTimeout(900);
await shot(page, '02-autocomplete');
await page.getByRole('option', { name: /apple/i }).click();
await page.waitForTimeout(800);
await shot(page, '03-auth-pending');

// sign up
await page.getByRole('tab', { name: /sign up/i }).click().catch(() => {});
await page.locator('#name').fill('Test User');
await page.locator('#email').fill('test@example.com');
await page.locator('#password').fill('Password123');
await shot(page, '04-auth-filled');
await page.getByRole('button', { name: /create account/i }).click();
// processing
await page.waitForTimeout(2500);
await shot(page, '05-processing');
// wait for dashboard (9 stages ~7s)
await page.waitForURL(/dashboard/, { timeout: 30000 });
await page.waitForTimeout(1500);
await shot(page, '06-dashboard-overview');

// swipe/scroll + open evidence from KPI
await page.getByRole('button', { name: /revenue.*open evidence/i }).first().click();
await page.waitForTimeout(800);
await shot(page, '07-evidence-sheet');
await page.getByRole('button', { name: /close panel/i }).click();

// income tab + statement table
await page.getByRole('tab', { name: /^income$/i }).click();
await page.waitForTimeout(800);
await shot(page, '08-income-table');

// valuation tab
await page.getByRole('tab', { name: /^valuation$/i }).click();
await page.waitForTimeout(600);
await shot(page, '09-valuation');

// sources tab
await page.getByRole('tab', { name: /^sources$/i }).click();
await page.waitForTimeout(600);
await shot(page, '10-sources');

// Ask Finora sheet
await page.getByRole('button', { name: /ask finora/i }).click();
await page.waitForTimeout(800);
await shot(page, '11-ask-sheet');
await page.getByRole('button', { name: /close panel/i }).click();

// history via tab bar
await page.getByRole('button', { name: /^history$/i }).click();
await page.waitForTimeout(1000);
await shot(page, '12-history');

// chat
await page.getByRole('button', { name: /ask ai/i }).click();
await page.waitForTimeout(800);
await page.getByPlaceholder(/ask about any company/i).fill('Explain ROIC simply');
await page.getByRole('button', { name: /send message/i }).click();
await page.waitForTimeout(3500);
await shot(page, '13-chat');

// profile
await page.getByRole('button', { name: /^me$/i }).click();
await page.waitForTimeout(800);
await shot(page, '14-profile');

// letter page (direct)
await page.goto('http://127.0.0.1:4321/#/limit', { waitUntil: 'networkidle' });
await page.waitForTimeout(800);
await shot(page, '15-letter');

// reviews
await page.goto('http://127.0.0.1:4321/#/reviews', { waitUntil: 'networkidle' });
await page.waitForTimeout(800);
await shot(page, '16-reviews');

// no horizontal overflow check on key routes
for (const r of ['/', '/methodology', '/about', '/research', '/history', '/profile']) {
  await page.goto(`http://127.0.0.1:4321/#${r}`, { waitUntil: 'load' });
  await page.waitForTimeout(400);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  console.log(`overflow ${r}: ${overflow}px`);
}

console.log('ERRORS:', errors.length ? errors : 'none');
await browser.close();
