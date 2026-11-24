// node render.js stills 3,10,20   |  node render.js all 24
const { chromium } = require('playwright-core');
const path = require('path');
const fs = require('fs');
(async () => {
  const mode = process.argv[2] || 'stills';
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 540, height: 960 }, deviceScaleFactor: 2 });
  page.on('console', m => console.log('console:', m.text()));
  page.on('pageerror', e => console.log('PAGEERROR:', e.message));
  await page.goto('file:///' + path.join(__dirname, 'guide.html').replace(/\\/g, '/'));
  let total = await page.evaluate(() => window.TOTAL);
  if (fs.existsSync(path.join(__dirname, 'timeline.json')) && !process.env.NO_WARP) {
    const warp = JSON.parse(fs.readFileSync(path.join(__dirname, 'timeline.json'), 'utf8'));
    total = await page.evaluate(w => window.setWarp(w), warp);
  }
  console.log('total seconds', total);
  if (mode === 'stills') {
    const times = (process.argv[3] || '3').split(',').map(Number);
    fs.mkdirSync(path.join(__dirname, 'stills'), { recursive: true });
    for (const t of times) {
      await page.evaluate(t => window.render(t), t);
      await page.screenshot({ path: path.join(__dirname, 'stills', `t${String(t).replace('.', '_')}.png`) });
    }
  } else {
    const fps = Number(process.argv[3] || 24);
    const dir = path.join(__dirname, 'frames');
    fs.rmSync(dir, { recursive: true, force: true });
    fs.mkdirSync(dir, { recursive: true });
    const n = Math.round(total * fps);
    for (let i = 0; i < n; i++) {
      await page.evaluate(t => window.render(t), i / fps);
      await page.screenshot({ path: path.join(dir, `f${String(i).padStart(5, '0')}.jpg`), type: 'jpeg', quality: 92 });
      if (i % 240 === 0) console.log('frame', i, '/', n);
    }
  }
  await browser.close();
})();
