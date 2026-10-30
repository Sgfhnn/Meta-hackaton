// App <-> Hark's PR #10 backend (local, fake upstream). Web build, fake camera, one tap.
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--disable-web-security'] });
  const ctx = await browser.newContext({ permissions: ['camera'], viewport: { width: 412, height: 860 } });
  const page = await ctx.newPage();
  const spoken = [], requests = [];
  await page.exposeFunction('__spoke', (t) => spoken.push(t));
  await page.addInitScript(() => {
    const orig = window.speechSynthesis && window.speechSynthesis.speak.bind(window.speechSynthesis);
    if (window.speechSynthesis) window.speechSynthesis.speak = (u) => { window.__spoke(u.text); try { orig(u); } catch (e) {} };
  });
  page.on('response', (r) => { if (r.url().includes(':8000/scan')) requests.push(`${r.request().method()} ${new URL(r.url()).pathname} -> ${r.status()}`); });
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('http://localhost:8099/', { waitUntil: 'networkidle' });
  await page.waitForSelector('text=Tap anywhere to count your money.', { timeout: 20000 });
  const demo = await page.isVisible('text=Demo mode (no server)');
  await page.getByRole('button', { name: 'Count money' }).click();
  await page.waitForFunction(() => document.body.innerText.includes('150'), null, { timeout: 30000 });
  await page.screenshot({ path: process.argv[2] + '/app_integration.png' });
  console.log(JSON.stringify({ demoLabel: demo, requests, spoken, errors }, null, 1));
  await browser.close();
})().catch((e) => { console.error('INTEGRATION FAILED:', e.message); process.exit(1); });
