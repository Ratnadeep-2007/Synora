const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('C:/Users/ratna/AppData/Local/hermes/hermes-agent/venv/Lib/site-packages/playwright/driver/package');
const root = path.resolve(__dirname, '..');
const dir = path.join(root, 'artifacts/meeting_notes_workflow_20261018');
fs.mkdirSync(dir, { recursive: true });
const env = name => Object.fromEntries(fs.readFileSync(path.join(root, name), 'utf8').replace(/^\uFEFF/, '').split(/\r?\n/).filter(line => /^[A-Z_]+=/.test(line)).map(line => { const i = line.indexOf('='); return [line.slice(0, i), line.slice(i + 1).replace(/^['"]|['"]$/g, '')]; }));
const credentials = env('.env.sample-admin');
const report = { checked_at: new Date().toISOString(), errors: [], requests: [] };
async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
    page.on('pageerror', error => report.errors.push(error.message.slice(0, 300)));
    page.on('response', response => { if (response.url().includes('/meetings/mtg_1e3590b49b4b')) report.requests.push({ path: new URL(response.url()).pathname, status: response.status() }); });
    page.on('response', async response => {
      if (response.url().endsWith('/meetings/mtg_1e3590b49b4b/canvas') && response.ok()) {
        try {
          const data = await response.json();
          report.canvas_seen = { version: data.artifact?.version, ai_status: data.artifact?.app_state?.meeting_canvas?.ai_status,
            translation_pending: data.artifact?.app_state?.meeting_canvas?.translation_pending_count };
        } catch {}
      }
    });
    page.on('response', response => { if (/\/sign-in\/|\/workspace-access|\/workspace\/access/.test(response.url())) report.requests.push({ path: new URL(response.url()).pathname, status: response.status() }); });
    await page.goto('https://synora-frontend.onrender.com', { waitUntil: 'domcontentloaded', timeout: 120000 });
    await page.getByLabel('Email', { exact: true }).fill(credentials.SAMPLE_ADMIN_EMAIL);
    await page.getByLabel('Password', { exact: true }).fill(credentials.SAMPLE_ADMIN_PASSWORD);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.getByRole('button', { name: 'Open meetings', exact: true }).waitFor({ timeout: 45000 }).catch(async error => {
      await page.screenshot({ path: path.join(dir, 'browser_login_diagnostic.png'), fullPage: true });
      fs.writeFileSync(path.join(dir, 'browser_login_diagnostic.txt'), await page.locator('body').innerText());
      throw error;
    });
    await page.getByRole('button', { name: 'Open meetings', exact: true }).click();
    await page.getByPlaceholder('Search meetings by title or ID...').fill('mtg_1e3590b49b4b');
    await page.getByText('Inspect Memory', { exact: true }).click({ timeout: 60000 });
    await page.locator('.excalidraw canvas').first().waitFor({ timeout: 90000 });
    await page.waitForTimeout(8000);
    await page.screenshot({ path: path.join(dir, 'render_meeting_canvas.png'), fullPage: true });
    report.canvas_count = await page.locator('.excalidraw canvas').count();
    const zoom = page.locator('.excalidraw').getByRole('button', { name: /zoom in/i });
    if (await zoom.count() === 1) {
      await zoom.click(); await zoom.click();
      await page.waitForTimeout(500);
      await page.screenshot({ path: path.join(dir, 'render_meeting_canvas_detail.png'), fullPage: true });
    }
    report.transcript_turns = await page.locator('#meeting-transcript article').count();
    report.bullet_notes = await page.locator('#meeting-bullet-notes li').count();
    report.source_buttons = await page.getByRole('button', { name: /^Show transcript source for:/ }).count();
    if (report.source_buttons) {
      await page.getByRole('button', { name: /^Show transcript source for:/ }).first().click();
      report.source_highlights = await page.getByText('Source for selected note', { exact: true }).count();
    }
    if (!report.transcript_turns || !report.bullet_notes || !report.source_highlights) throw Error('Transcript, notes or source navigation is missing');
    report.old_surface_switches = await page.getByRole('button', { name: /^(Meeting Canvas|Meeting Intelligence)$/ }).count();
    await page.screenshot({ path: path.join(dir, 'meeting_workflow.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(500);
    report.mobile_overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    await page.screenshot({ path: path.join(dir, 'meeting_workflow_mobile.png'), fullPage: true });
    fs.writeFileSync(path.join(dir, 'render_meeting_visible_text.txt'), await page.locator('body').innerText());
  } finally { await browser.close(); }
}
main().catch(error => { report.error = error.message; process.exitCode = 1; }).finally(() => { fs.writeFileSync(path.join(dir, 'browser_verification.json'), JSON.stringify(report, null, 2)); console.log(JSON.stringify(report, null, 2)); });
