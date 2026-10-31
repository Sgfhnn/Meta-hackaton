// Headless smoke test of the web build: fake camera, demo mode (no server). Taps twice.
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
  const ctx = await browser.newContext({ permissions: ['camera'], viewport: { width: 412, height: 860 } });
  const page = await ctx.newPage();
  const spoken = [];
  await page.exposeFunction('__spoke', (t) => spoken.push(t));
  await page.addInitScript(() => {
    const orig = window.speechSynthesis && window.speechSynthesis.speak.bind(window.speechSynthesis);
    if (window.speechSynthesis) window.speechSynthesis.speak = (u) => { window.__spoke(u.text); try { orig(u); } catch (e) {} };
  });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('http://localhost:8099/', { waitUntil: 'networkidle' });
  await page.waitForSelector('text=Tap anywhere to count your money.', { timeout: 20000 });
  const demo = await page.isVisible('text=Demo mode (no server)');
  await page.screenshot({ path: process.argv[2] + '/app_idle.png' });
  const tap = page.getByRole('button', { name: 'Count money' });
  await tap.click();
  await page.waitForSelector('text=You have 350 birr: one 200, one 100 and one 50.', { timeout: 20000 });
  await page.screenshot({ path: process.argv[2] + '/app_total.png' });
  await tap.click();
  await page.waitForSelector('text=One note is covered, at the far left. Slide it out so I can see all of it, then tap again.', { timeout: 20000 });
  console.log(JSON.stringify({ demoLabel: demo, spoken, errors }, null, 1));
  await browser.close();
})().catch((e) => { console.error('SMOKE FAILED:', e.message); process.exit(1); });
