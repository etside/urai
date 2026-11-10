'use strict';

/**
 * Urai desktop shell.
 *
 * The window is a thin Chromium shell around the Urai API server. On launch we
 * locate a Python interpreter, start `python -m jev.cli api --port <free>`,
 * wait for /health, then load the Studio from that origin. If no backend can be
 * started we show setup.html with instructions and a Retry button.
 *
 * Config (optional) ~/.urai/desktop.json:
 *   { "python": "/usr/bin/python3", "home": "/opt/urai",
 *     "port": 8777, "noServer": false }
 *
 * Env overrides: URAI_PYTHON, URAI_HOME, URAI_PORT, URAI_NO_SERVER=1
 */

const { app, BrowserWindow, Menu, shell, dialog, ipcMain } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');

let win = null;
let backend = null;
let backendLog = [];
let quitting = false;

const isWin = process.platform === 'win32';

// ── config ───────────────────────────────────────────────────────────────────
function loadConfig() {
  const cfg = { port: 0, noServer: false };
  try {
    const f = path.join(os.homedir(), '.urai', 'desktop.json');
    if (fs.existsSync(f)) Object.assign(cfg, JSON.parse(fs.readFileSync(f, 'utf8')));
  } catch (e) { /* ignore malformed config */ }
  cfg.python = process.env.URAI_PYTHON || cfg.python || (isWin ? 'python' : 'python3');
  cfg.home = process.env.URAI_HOME || cfg.home || '';
  cfg.port = Number(process.env.URAI_PORT || cfg.port || 0);
  if (process.env.URAI_NO_SERVER === '1') cfg.noServer = true;
  return cfg;
}

// ── ports ────────────────────────────────────────────────────────────────────
function portFree(port) {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.once('error', () => resolve(false));
    s.once('listening', () => s.close(() => resolve(true)));
    s.listen(port, '127.0.0.1');
  });
}

async function pickPort(preferred) {
  if (preferred && await portFree(preferred)) return preferred;
  for (let p = 8777; p < 8800; p++) {
    if (await portFree(p)) return p;
  }
  throw new Error('no free port in 8777-8799');
}

// ── health ───────────────────────────────────────────────────────────────────
function getJson(url, timeoutMs = 1500) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      let body = '';
      res.on('data', (d) => { body += d; });
      res.on('end', () => {
        try { resolve({ status: res.statusCode, json: JSON.parse(body) }); }
        catch { resolve({ status: res.statusCode, json: null }); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

async function waitHealthy(port, ms = 45000, child = null) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    // A backend that already exited will never answer: fail fast instead of
    // waiting out the full timeout.
    if (child && child.exitCode !== null) return false;
    try {
      const r = await getJson(`http://127.0.0.1:${port}/health`);
      if (r.status === 200) return true;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

// ── backend ──────────────────────────────────────────────────────────────────
function candidateHomes(cfg) {
  const out = [];
  if (cfg.home) out.push(cfg.home);
  out.push(path.join(__dirname, '..'));   // running from the repo
  out.push(process.cwd());
  if (!isWin) out.push('/opt/urai');
  return out;
}

function startBackend(cfg, port) {
  // Prefer a checkout, but a pip-installed `jev` package works from any cwd.
  const home = candidateHomes(cfg).find((h) => {
    try { return fs.existsSync(path.join(h, 'jev', 'cli.py')); } catch { return false; }
  }) || os.homedir();

  const args = ['-m', 'jev.cli', 'api', '--port', String(port)];
  const env = Object.assign({}, process.env, { PYTHONUNBUFFERED: '1' });
  if (isWin) env.PYTHONIOENCODING = 'utf-8';

  const child = spawn(cfg.python, args, { cwd: home, env, windowsHide: true });
  backendLog = [];

  const capture = (buf) => {
    backendLog.push(buf.toString());
    if (backendLog.length > 400) backendLog.shift();
  };
  child.stdout.on('data', capture);
  child.stderr.on('data', capture);
  child.on('error', (e) => capture(`spawn error: ${e.message}\n`));
  child.on('exit', (code, sig) => {
    capture(`backend exited code=${code} sig=${sig}\n`);
    if (!quitting && win) showSetup('The Urai backend stopped unexpectedly.');
  });
  return child;
}

// ── UI ───────────────────────────────────────────────────────────────────────
function showSetup(reason) {
  if (!win || win.isDestroyed()) return;
  const staticDir = path.join(process.resourcesPath || '', 'static');
  const localSetup = path.join(__dirname, 'setup.html');
  const q = new URLSearchParams({ reason: reason || '' });
  if (fs.existsSync(localSetup)) {
    win.loadFile(localSetup, { query: Object.fromEntries(q) });
  } else {
    win.loadURL('data:text/html,' + encodeURIComponent(
      `<body style="font-family:system-ui;padding:40px;background:#FAF9F7;color:#111">
       <h1>Urai</h1><p>${reason || 'Backend not reachable.'}</p>
       <p>Install Urai with <code>pip install urai</code>, then set
       <code>URAI_HOME</code> to the repo and retry.</p></body>`));
  }
  void staticDir;
}

function createWindow() {
  win = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 900,
    minHeight: 620,
    backgroundColor: '#FAF9F7',
    title: 'Urai',
    icon: path.join(__dirname, 'build', 'icon.png'),
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (e, url) => {
    if (!url.startsWith('http://127.0.0.1')) {
      e.preventDefault();
      shell.openExternal(url);
    }
  });
  win.on('closed', () => { win = null; });
}

async function boot() {
  createWindow();
  const cfg = loadConfig();

  if (cfg.noServer) {
    const p = cfg.port || 8777;
    if (await waitHealthy(p, 4000)) win.loadURL(`http://127.0.0.1:${p}/`);
    else showSetup('No Urai server is running on port ' + p + '.');
    return;
  }

  const port = await pickPort(cfg.port);
  backend = startBackend(cfg, port);

  const ok = await waitHealthy(port, 45000, backend);
  if (ok) {
    win.loadURL(`http://127.0.0.1:${port}/`);
  } else {
    showSetup('The backend did not answer /health within 45s. See the log below.');
  }
}

ipcMain.handle('urai:retry', async () => {
  if (backend) { try { backend.kill(); } catch {} backend = null; }
  if (win) { win.destroy(); }
  createWindow();
  await boot();
  return true;
});
ipcMain.handle('urai:log', () => backendLog.join(''));
ipcMain.handle('urai:openExternal', (_e, url) => shell.openExternal(url));

// ── lifecycle ────────────────────────────────────────────────────────────────
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) { if (win.isMinimized()) win.restore(); win.focus(); }
  });

  app.whenReady().then(() => {
    Menu.setApplicationMenu(null);
    boot().catch((e) => showSetup(String(e)));
    app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) boot(); });
  });

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });

  app.on('before-quit', () => {
    quitting = true;
    if (backend) {
      try { backend.kill('SIGTERM'); } catch {}
      setTimeout(() => { try { backend && backend.kill('SIGKILL'); } catch {} }, 4000);
    }
  });
}
