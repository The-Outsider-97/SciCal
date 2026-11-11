// Build the browser client: compile TypeScript, then copy the page and style sheet into dist/.
//
// The build is safe: it compiles into a scratch folder and only replaces dist/ once the compile has succeeded, so a failed build
// (for example TypeScript not being installed) leaves the last good dist/ exactly as it was. Before this was safe, a failed build
// had already deleted dist/js and SciCal opened as a blank "Starting SciCal..." page.
//
// TypeScript is taken from this project (run `npm install` once) or, failing that, from a `tsc` on the PATH.
// Icons are NOT copied: the server serves them from the SLAI-wide applications/assets folder.
import { execFileSync, spawnSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, mkdtempSync, renameSync, rmSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(root, 'dist');

function fail(message) {
  console.error(`\nBuild failed: ${message}\nThe existing dist/ folder was left untouched.`);
  process.exit(1);
}

function findTsc() {
  try { return { cmd: process.execPath, pre: [createRequire(join(root, 'package.json')).resolve('typescript/bin/tsc')] }; } catch { /* not installed here */ }
  const name = process.platform === 'win32' ? 'tsc.cmd' : 'tsc';
  const probe = spawnSync(name, ['--version'], { shell: process.platform === 'win32', encoding: 'utf8' });
  if (probe.status === 0) return { cmd: name, pre: [], shell: process.platform === 'win32' };
  return null;
}

const tsc = findTsc();
if (!tsc) fail('TypeScript is not installed. Run `npm install` in this folder once, then `npm run build` again.');

// Compile into a scratch folder next to dist/ (same drive, so the final swap is a plain rename).
const scratchRoot = mkdtempSync(join(existsSync(root) ? root : tmpdir(), '.build-'));
const out = join(scratchRoot, 'js');
try {
  execFileSync(tsc.cmd, [...tsc.pre, '-p', join(root, 'tsconfig.build.json'), '--outDir', out], { stdio: 'inherit', cwd: root, shell: Boolean(tsc.shell) });
} catch {
  rmSync(scratchRoot, { recursive: true, force: true });
  fail('the TypeScript compiler reported errors (see above).');
}
if (!existsSync(join(out, 'client', 'main.js'))) {
  rmSync(scratchRoot, { recursive: true, force: true });
  fail('the compiler did not produce client/main.js.');
}

// Swap by renaming, never by deleting first: the old folder is moved aside and only removed once the new one is in place,
// and it is moved back if anything goes wrong, so there is no moment (or failure) that leaves dist/ without a working js/.
mkdirSync(dist, { recursive: true });
const live = join(dist, 'js');
const aside = join(dist, `.js-previous-${process.pid}`);
const hadOld = existsSync(live);
try {
  if (hadOld) renameSync(live, aside);
  renameSync(out, live);
} catch (error) {
  try { if (hadOld && !existsSync(live) && existsSync(aside)) renameSync(aside, live); } catch { /* nothing more to do */ }
  try { rmSync(scratchRoot, { recursive: true, force: true }); } catch { /* best effort */ }
  fail(`the new files could not be put in place (${error.code ?? error.message}).`);
}
try { rmSync(aside, { recursive: true, force: true }); } catch { /* a leftover .js-previous-* folder is harmless */ }
try { rmSync(scratchRoot, { recursive: true, force: true }); } catch { /* best effort */ }
cpSync(join(root, 'src', 'client', 'index.html'), join(dist, 'index.html'));
cpSync(join(root, 'src', 'client', 'styles.css'), join(dist, 'styles.css'));
console.log('Built dist/');

// Standalone distributions include the published loader in dist/startup.
const shared = process.env.SLAI_ROOT
  ? join(process.env.SLAI_ROOT, 'applications', 'tools')
  : join(root, '..', 'tools');
const publisher = join(shared, 'build', 'publish-startup.mjs');
if (existsSync(publisher)) {
  const { publishStartup } = await import(pathToFileURL(publisher).href);
  publishStartup(dist);
} else if (!['loader.js', 'loader.css'].every(file => existsSync(join(dist, 'startup', file)))) {
  throw new Error('Set SLAI_ROOT to build with the shared SLAI startup assets.');
}
