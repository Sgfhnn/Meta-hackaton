// node render.js <svg> <png> <size> : rasterize an SVG with Chromium, keeping transparency.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const jobs = [];
  for (let i = 2; i < process.argv.length; i += 3) jobs.push(process.argv.slice(i, i + 3));
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  for (const [svgPath, pngPath, sizeText] of jobs) {
    const size = Number(sizeText);
    const svg = fs.readFileSync(svgPath, 'utf8').replace(/width="\d+" height="\d+"/, `width="${size}" height="${size}"`);
    await page.setViewportSize({ width: size, height: size });
    await page.setContent(`<html><body style="margin:0;background:transparent">${svg}</body></html>`);
    await page.screenshot({ path: pngPath, omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } });
    console.log('rendered', pngPath, size);
  }
  await browser.close();
})();
