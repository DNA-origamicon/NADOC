const { app, BrowserWindow, Menu, dialog, session, shell } = require('electron')
const { spawn } = require('node:child_process')
const { randomBytes } = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')
const readline = require('node:readline')
const { parseOptions, localURL, launchURL } = require('./runtime.cjs')

const options = parseOptions(process.argv)
if (options.profile) app.setPath('userData', options.profile)
if (!app.requestSingleInstanceLock()) { app.quit(); process.exit(0) }
let child, origin, log, quitting = false, stopPromise
const token = randomBytes(32).toString('hex')
const root = app.isPackaged ? path.join(process.resourcesPath, 'payload') : path.resolve(__dirname, '..')

function record(event, data = {}) {
  const entry = JSON.stringify({ at: new Date().toISOString(), event, ...data })
  log?.write(entry + '\n')
  console.log(entry)
}

async function stopBackend() {
  if (stopPromise) return stopPromise
  stopPromise = new Promise(resolve => {
    if (!child || child.exitCode !== null) return resolve()
    const timeout = setTimeout(() => { child.kill('SIGKILL') }, 20000)
    child.once('exit', () => { clearTimeout(timeout); resolve() })
    child.kill('SIGTERM')
  })
  return stopPromise
}

function openWindow(url) {
  const win = new BrowserWindow({ width: 1440, height: 1000, show: false, backgroundColor: '#161b22',
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true } })
  win.webContents.on('will-navigate', (event, target) => { if (!localURL(target, origin)) event.preventDefault() })
  win.webContents.on('will-prevent-unload', event => {
    const leave = options.validation || dialog.showMessageBoxSync(win, {
      type: 'question', buttons: ['Keep editing', 'Close window'], defaultId: 0, cancelId: 0,
      message: 'Close this NADOC document?', detail: 'A document operation or unsaved change may still be pending. Save before closing to keep your work.',
    }) === 1
    if (leave) event.preventDefault()
  })
  win.webContents.setWindowOpenHandler(({ url: target }) => {
    if (localURL(target, origin)) openWindow(target)
    else if (/^https?:\/\//.test(target)) shell.openExternal(target)
    return { action: 'deny' }
  })
  win.webContents.on('render-process-gone', (_, details) => {
    record('renderer-exited', details)
    dialog.showErrorBox('NADOC renderer stopped', `${details.reason}. Diagnostics: ${app.getPath('logs')}`)
  })
  win.webContents.on('console-message', (_, level, message) => { if (level >= 2) record('renderer-log', { level, message }) })
  win.once('ready-to-show', () => { win.show(); record('window-visible') })
  win.loadURL(url).catch(error => { record('navigation-error', { message: error.message }); dialog.showErrorBox('NADOC could not open', error.message) })
  return win
}

async function startBackend(workspace) {
  const pythonHome = path.join(process.resourcesPath, 'python')
  const python = app.isPackaged ? path.join(pythonHome, 'bin', 'python3') : path.join(root, '.venv', 'bin', 'python')
  const args = ['-m', 'desktop.backend', '--workspace', workspace]
  if (options.validation) args.push('--validation')
  const env = { ...process.env, PYTHONPATH: root, PYTHONUNBUFFERED: '1', PYTHONDONTWRITEBYTECODE: '1', NADOC_DESKTOP_TOKEN: token }
  if (app.isPackaged) env.PYTHONHOME = pythonHome
  child = spawn(python, args, { cwd: root, env, stdio: ['ignore', 'pipe', 'pipe'] })
  record('backend-started', { pid: child.pid })
  child.stderr.on('data', chunk => log.write(chunk))
  const address = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Backend startup timed out; see desktop.log')), 120000)
    child.once('error', error => { clearTimeout(timer); reject(error) })
    child.once('exit', code => { clearTimeout(timer); reject(new Error(`Backend exited (${code}); see desktop.log`)) })
    readline.createInterface({ input: child.stdout }).on('line', line => {
      log.write(line + '\n')
      try {
        const value = JSON.parse(line)
        if (value.event === 'desktop-listening') { clearTimeout(timer); resolve(`http://127.0.0.1:${value.port}`) }
      } catch { /* Backend also emits ordinary diagnostic lines. */ }
    })
  })
  for (let attempt = 0; attempt < 600; attempt++) {
    if (child.exitCode !== null) throw new Error('Backend exited during startup')
    try {
      const response = await fetch(`${address}/api/desktop/ready`, { headers: { 'X-NADOC-Desktop': token }, signal: AbortSignal.timeout(1000) })
      if (response.ok) { record('backend-ready', await response.json()); return address }
    } catch { /* Wait for uvicorn and the normal application lifespan. */ }
    await new Promise(resolve => setTimeout(resolve, 200))
  }
  throw new Error('Backend readiness timed out')
}

// Let document beforeunload/save handlers finish while the backend is alive.
app.on('will-quit', event => {
  if (quitting) return
  event.preventDefault()
  quitting = true
  stopBackend().finally(() => { record('shutdown-complete'); log?.end(); app.quit() })
})
app.on('window-all-closed', () => app.quit())
app.whenReady().then(async () => {
  app.setAppLogsPath(path.join(app.getPath('userData'), 'logs'))
  fs.mkdirSync(app.getPath('logs'), { recursive: true })
  log = fs.createWriteStream(path.join(app.getPath('logs'), 'desktop.log'), { flags: 'a' })
  let savedWorkspace
  try { savedWorkspace = JSON.parse(fs.readFileSync(path.join(app.getPath('userData'), 'workspace.json'), 'utf8')).workspace } catch { /* First launch. */ }
  const workspace = options.workspace || savedWorkspace || path.join(app.getPath('documents'), 'NADOC')
  origin = await startBackend(workspace)
  session.defaultSession.webRequest.onBeforeSendHeaders((details, callback) => {
    const headers = { ...details.requestHeaders }
    if (localURL(details.url.replace(/^ws:/, 'http:'), origin)) headers['X-NADOC-Desktop'] = token
    callback({ requestHeaders: headers })
  })
  session.defaultSession.setPermissionRequestHandler((contents, permission, callback) => callback(
    localURL(contents.getURL(), origin) && ['clipboard-sanitized-write', 'fullscreen'].includes(permission)))
  session.defaultSession.on('will-download', (_, item, contents) => {
    item.setSaveDialogOptions({ title: 'Save NADOC export' })
  })
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: 'NADOC', submenu: [
      { label: 'New window', accelerator: 'CmdOrCtrl+Shift+N', click: () => openWindow(launchURL(origin, null, options)) },
      { label: 'Show workspace folder', click: () => shell.openPath(workspace) },
      { label: 'Choose workspace for next launch…', click: async () => {
        const result = await dialog.showOpenDialog({ properties: ['openDirectory', 'createDirectory'] })
        if (!result.canceled) {
          fs.writeFileSync(path.join(app.getPath('userData'), 'workspace.json'), JSON.stringify({ workspace: result.filePaths[0] }))
          dialog.showMessageBox({ message: 'Workspace saved. Restart NADOC to use it.' })
        }
      } },
      { type: 'separator' }, { role: 'quit' }] },
    { role: 'editMenu' },
    { label: 'Diagnostics', submenu: [{ role: 'toggleDevTools' }, { role: 'reload' },
      { label: 'Open diagnostic logs', click: () => shell.openPath(app.getPath('logs')) },
      { label: 'Capture window…', click: async (_, win) => {
        const result = await dialog.showSaveDialog(win, { defaultPath: 'nadoc-window.png' })
        if (!result.canceled && win) fs.writeFileSync(result.filePath, (await win.webContents.capturePage()).toPNG())
      } }] },
  ]))
  openWindow(launchURL(origin, options.open, options))
  child.on('exit', code => {
    if (!quitting) { record('backend-exited', { code }); dialog.showErrorBox('NADOC backend stopped', `Exit ${code}. See ${app.getPath('logs')}`); app.quit() }
  })
}).catch(error => { record('startup-failed', { message: error.message }); dialog.showErrorBox('NADOC startup failed', error.message); app.quit() })
