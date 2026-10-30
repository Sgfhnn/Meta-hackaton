// App (web build) <-> backend (local) <-> fake Muse/Gemini. Fake camera and microphone.
// Flow: Ask -> speak -> send -> change intent in Amharic -> tap -> change scan -> answer.
const { chromium } = require('playwright');
(async () => {
  const out = process.argv[2];
  const browser = await chromium.launch({
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--autoplay-policy=no-user-gesture-required'],
  });
  const ctx = await browser.newContext({ permissions: ['camera', 'microphone'], viewport: { width: 412, height: 860 } });
  const page = await ctx.newPage();
  const spoken = [];
  const clips = [];
  const requests = [];
  const errors = [];
  await page.exposeFunction('__spoke', (t) => spoken.push(t));
  await page.exposeFunction('__clip', (src) => clips.push(src));
  await page.addInitScript(() => {
    if (window.speechSynthesis) {
      const orig = window.speechSynthesis.speak.bind(window.speechSynthesis);
      window.speechSynthesis.speak = (u) => {
        window.__spoke(u.text);
        try { orig(u); } catch (e) {}
      };
    }
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      window.__clip(this.currentSrc || this.src);
      return play.call(this);
    };
  });
  page.on('request', (r) => {
    const u = new URL(r.url());
    if (u.port === '8000') {
      let detail = '';
      if (r.method() === 'POST' && u.pathname === '/scan') {
        const body = r.postData() || '';
        const field = (name) => (body.match(new RegExp(`name="${name}"\\r\\n\\r\\n([^\\r]*)`)) || [])[1];
        detail = ` intent=${field('intent')} paid=${field('paid')} price=${field('price')} lang=${field('lang')}`;
      }
      requests.push(`${r.method()} ${u.pathname}${detail}`);
    }
  });
  page.on('response', (r) => {
    const u = new URL(r.url());
    if (u.port === '8000') requests.push(`  <- ${r.status()} ${u.pathname}`);
  });
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto('http://localhost:8099/', { waitUntil: 'networkidle' });
  await page.waitForSelector('text=Hold to ask a question', { timeout: 20000 });
  await page.waitForTimeout(1500); // /health -> languages
  const langButton = await page.getByRole('button', { name: /Language:/ }).getAttribute('aria-label');

  // Ask by voice: tap Ask, "speak" (the fake microphone beeps), tap again to send.
  await page.getByRole('button', { name: 'Ask a question' }).click();
  await page.waitForSelector('text=Listening… tap to send', { timeout: 10000 });
  await page.waitForTimeout(1800);
  await page.getByRole('button', { name: 'Ask a question' }).click();
  await page.waitForSelector('text=Checking change: paid 500, price 320', { timeout: 30000 });
  const afterIntent = await page.locator('body').innerText();
  await page.screenshot({ path: out + '/voice_intent.png' });

  // Tap to scan the change.
  await page.getByRole('button', { name: 'Count money' }).click();
  await page.waitForFunction(() => document.body.innerText.includes('30 birr short'), null, { timeout: 60000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: out + '/voice_change.png' });
  const afterScan = await page.locator('body').innerText();
  console.log(JSON.stringify({ langButton, requests, spoken, clips, errors, afterIntent, afterScan }, null, 1));
  await browser.close();
})().catch((e) => {
  console.error('INTEGRATION FAILED:', e.message);
  process.exit(1);
});
