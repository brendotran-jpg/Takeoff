const { chromium } = require('playwright');
// usage: node scripts/e2e_ui.js <workdir>   (workdir holds sample.pdf + sample_revB.pdf; screenshots and
//        e2e.xlsx are written there). Start the app first: uvicorn app.main:app --port 8765
const SP = process.argv[2];
const URL = process.env.TAKEOFF_URL || 'http://localhost:8765/';
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1600, height: 950 }, acceptDownloads: true });
  const p = await ctx.newPage();
  const errs = [];
  p.on('pageerror', e => errs.push('pageerror: ' + e.message));
  p.on('console', m => m.type() === 'error' && errs.push('console: ' + m.text()));
  const step = (s) => console.log('·', s);
  await p.goto(URL);
  await p.waitForSelector('#drawingTree');
  // import
  await p.setInputFiles('#uploadInput', SP + '/sample.pdf');
  await p.waitForSelector('#scaleCands button');
  await p.waitForFunction(() => document.getElementById('pageImg').complete && document.getElementById('pageImg').naturalWidth > 0);
  step('imported');
  await p.click('#scaleCands button');
  await p.waitForSelector('#scaleStatus.ok');
  step('scale: ' + await p.textContent('#scaleStatus'));
  await p.waitForTimeout(400);

  const MM = 72 / 25.4, s = MM / 100, ox = 60 * MM, oy = 50 * MM;
  const P = (xmm, ymm) => [ox + xmm * s, oy + ymm * s];
  const toScreen = ([x, y]) => p.evaluate(([x, y]) => {
    const svg = document.getElementById('overlay'); const pt = svg.createSVGPoint(); pt.x = x; pt.y = y;
    const q = pt.matrixTransform(svg.getScreenCTM()); return [q.x, q.y]; }, [x, y]);
  const click = async (pt, off = 1.0) => { const [x, y] = await toScreen([pt[0] + off, pt[1] + off]); await p.mouse.move(x, y); await p.mouse.click(x, y); };
  async function newItem(ruleId, name, inputs = {}) {
    await p.click('#newItemBtn');
    await p.selectOption('#m_rule_id', ruleId);
    await p.click('#modalForm button[value=ok]');
    await p.waitForSelector('#m_name');
    await p.fill('#m_name', name);
    for (const [k, v] of Object.entries(inputs)) await p.fill('#m_' + k, String(v));
    await p.click('#modalForm button[value=ok]');
    await p.waitForFunction((n) => document.getElementById('ipName').textContent.includes(n), name);
  }
  const qty = () => p.textContent('#ipQty .main');

  // 1. ceiling area with cut-out
  await newItem('FIN-PLB-CEIL-001', 'GF ceiling 10mm plasterboard');
  for (const c of [P(0, 0), P(12000, 0), P(12000, 8000), P(0, 8000)]) await click(c);
  await p.keyboard.press('Enter');
  await p.waitForFunction(() => document.getElementById('ipQty').textContent.includes('96.000'));
  step('ceiling area: ' + await qty());
  await p.click('[data-tool=cutout]');
  for (const c of [P(2000, 2000), P(4000, 2000), P(4000, 3000), P(2000, 3000)]) await click(c, 0);
  await p.keyboard.press('Enter');
  await p.waitForFunction(() => !document.getElementById('ipQty').textContent.includes('96.000'));
  const afterCut = await qty();
  step('after cut-out (unsnapped hole, ~2 m2 expected): ' + afterCut);

  // 2. walls with height
  await newItem('MAS-WALL-001', 'External brick veneer', { height_m: 2.7 });
  await click(P(0, 0)); await click(P(12000, 0)); await click(P(12000, 8000));
  await p.keyboard.press('Enter');
  await p.waitForFunction(() => document.getElementById('ipQty').textContent.includes('54.000'));
  step('wall face area: ' + await qty());

  // 3. doors count
  await newItem('WD-DOOR-001', 'D1 820 hinged door');
  await click(P(1500, 8000)); await click(P(7000, 8000));
  await p.waitForFunction(() => document.getElementById('ipQty').textContent.includes('2.000'));
  step('doors: ' + await qty());

  // 4. select + drag vertex on the ceiling, then undo
  await p.click('.items .it >> text=GF ceiling');
  await p.click('[data-tool=select]');
  await click(P(6000, 6000), 0);
  await p.waitForSelector('#shapePanel:not([hidden])');
  const h = await p.$('svg .handle[data-vi="2"]');
  const hb = await h.boundingBox();
  const [tx, ty] = await toScreen(P(13000, 8000));
  await p.mouse.move(hb.x + hb.width / 2, hb.y + hb.height / 2);
  await p.mouse.down(); await p.mouse.move(tx, ty, { steps: 8 }); await p.mouse.up();
  await p.waitForFunction((v) => document.querySelector('#ipQty .main').textContent !== v, afterCut);
  step('after vertex drag: ' + await qty());
  await p.keyboard.press('Control+z');
  await p.waitForFunction((v) => document.querySelector('#ipQty .main').textContent === v, afterCut);
  step('after undo: ' + await qty());
  await p.screenshot({ path: SP + '/shot_takeoff.png' });

  // 5. estimate
  await p.click('.tabs button[data-tab=estimate]');
  await p.click('#fromItems');
  await p.waitForSelector('tr[data-row]');
  const rows = await p.$$eval('tr[data-row]', (r) => r.map((x) => x.dataset.row));
  const setCell = async (rid, f, v) => { const sel = `[data-key="r${rid}:${f}"]`; await p.fill(sel, String(v)); await p.press(sel, 'Enter'); await p.waitForTimeout(250); };
  await setCell(rows[0], 'material', 22.5); await setCell(rows[0], 'labour', 18);
  await setCell(rows[1], 'subcontract', 95); await setCell(rows[1], 'waste_pct', 5);
  await setCell(rows[2], 'material', 420); await setCell(rows[2], 'labour', 160);
  await p.fill('[data-key="m:margin_pct"]', '8'); await p.press('[data-key="m:margin_pct"]', 'Enter');
  await p.waitForTimeout(400);
  step('estimate total: ' + (await p.textContent('tr.grand')).replace(/\s+/g, ' '));
  await p.screenshot({ path: SP + '/shot_estimate.png' });

  // 6. revisions
  await p.click('.tabs button[data-tab=takeoff]');
  await p.setInputFiles('#uploadInput', SP + '/sample_revB.pdf');
  await p.waitForFunction(() => document.querySelectorAll('.tree .pg').length === 4);
  await p.click('.tabs button[data-tab=compare]');
  const opts = await p.$$eval('#cmpB option', (o) => o.map((x) => x.value));
  await p.selectOption('#cmpA', opts[0]); await p.selectOption('#cmpB', opts[opts.length - 1]);
  await p.click('#cmpGo');
  await p.waitForFunction(() => document.getElementById('cmpImg').naturalWidth > 0);
  step('compare: ' + await p.textContent('#cmpStats'));
  await p.screenshot({ path: SP + '/shot_compare.png' });
  await p.click('#cmpTransfer');
  await p.click('#modalForm button[value=ok]');
  await p.waitForTimeout(800);
  const shapesOnNew = await p.evaluate(async (v) => { const [d, pg] = v.split(':'); return (await (await fetch(`/api/shapes?drawing_id=${d}&page=${pg}`)).json()).length; }, opts[opts.length - 1]);
  step('shapes moved to rev B: ' + shapesOnNew);

  // 7. export
  const [dl] = await Promise.all([p.waitForEvent('download'), p.evaluate(() => document.querySelector('[data-act=xlsx]').click())]);
  await dl.saveAs(SP + '/e2e.xlsx');
  step('exported ' + dl.suggestedFilename());
  console.log('errors:', errs);
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
