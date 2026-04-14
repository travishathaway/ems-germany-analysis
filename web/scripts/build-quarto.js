/**
 * build-quarto.js
 *
 * Pre-build step that runs `quarto render full_report.qmd`, extracts the
 * rendered <main> body, and injects it into web/index.html (generated from
 * web/index.template.html) as the content of #full-report-body.  This
 * happens before vite build so the static HTML Vite processes already has
 * the report content embedded.
 *
 * index.template.html is the source of truth and is never modified.
 * index.html is the generated output — do not edit it directly.
 *
 * Usage (called automatically by `npm run build`):
 *   node scripts/build-quarto.js
 *
 * In dev mode this script is called automatically by the Vite plugin in
 * vite.config.js whenever full_report.qmd changes.
 *
 * If `quarto` is not on PATH or full_report.qmd does not exist the script
 * returns false / exits with a warning but does NOT fail the build — the
 * report page will simply be empty.
 */

import { execSync } from 'child_process';
import { existsSync, readFileSync, writeFileSync, copyFileSync } from 'fs';
import { mkdtempSync, rmSync } from 'fs';
import { join, resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { tmpdir } from 'os';

const __dirname      = dirname(fileURLToPath(import.meta.url));
export const ROOT           = resolve(__dirname, '../..');   // repo root
export const QMD_SRC        = join(ROOT, 'full_report.qmd');
const BIB_SRC        = join(ROOT, 'bibliography.bib');
export const INDEX_TEMPLATE = join(__dirname, '../index.template.html');
export const INDEX_HTML     = join(__dirname, '../index.html');

function hasQuarto() {
  try { execSync('quarto --version', { stdio: 'ignore' }); return true; }
  catch { return false; }
}

/**
 * Run Quarto, extract <main>, inject into index.html from index.template.html.
 * Returns true on success, false if prerequisites are missing.
 */
export async function buildQuarto() {
  if (!existsSync(QMD_SRC)) {
    console.warn('[build-quarto] full_report.qmd not found — skipping Quarto render.');
    return false;
  }

  if (!hasQuarto()) {
    console.warn('[build-quarto] quarto not found on PATH — skipping Quarto render.');
    return false;
  }

  const tmp = mkdtempSync(join(tmpdir(), 'quarto-'));

  try {
    copyFileSync(QMD_SRC, join(tmp, 'full_report.qmd'));
    if (existsSync(BIB_SRC)) copyFileSync(BIB_SRC, join(tmp, 'bibliography.bib'));

    console.log('[build-quarto] Rendering full_report.qmd…');
    execSync('quarto render full_report.qmd --to html --no-cache', {
      cwd: tmp,
      stdio: 'inherit',
    });

    const renderedPath = join(tmp, 'full_report.html');
    if (!existsSync(renderedPath)) {
      console.warn('[build-quarto] Quarto did not produce full_report.html — skipping.');
      return false;
    }

    // Extract <main> body from the rendered HTML
    const rendered = readFileSync(renderedPath, 'utf8');
    const match = rendered.match(/<main\b[^>]*>([\s\S]*?)<\/main>/i);
    const reportBody = match ? match[1].trim() : '';

    if (!reportBody) {
      console.warn('[build-quarto] Could not extract <main> from rendered HTML.');
      return false;
    }

    // Read the template (never mutated) and write the result to index.html
    let indexHtml = readFileSync(INDEX_TEMPLATE, 'utf8');
    indexHtml = indexHtml.replace(
      /<div class="full-report-body" id="full-report-body"><\/div>/,
      `<div class="full-report-body" id="full-report-body">${reportBody}</div>`,
    );
    writeFileSync(INDEX_HTML, indexHtml, 'utf8');

    console.log('[build-quarto] Injected full report into index.html.');
    return true;
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

// ── Run directly (npm run build calls: node scripts/build-quarto.js) ────────
// Detect whether this module is the entry point
const isMain = process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url));
if (isMain) {
  buildQuarto().then(ok => { if (!ok) process.exit(0); });
}
