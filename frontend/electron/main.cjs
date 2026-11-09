const { app, BrowserWindow, ipcMain, shell } = require('electron')
const path = require('node:path')

const PROJECT_ROOT = path.resolve(__dirname, '..', '..')

function safePath(target) {
  const resolved = path.resolve(String(target || ''))
  if (
    resolved !== PROJECT_ROOT &&
    !resolved.startsWith(PROJECT_ROOT + path.sep)
  ) {
    throw new Error('路径不在项目目录内')
  }
  return resolved
}

ipcMain.handle('show-item-in-folder', (_event, target) => {
  shell.showItemInFolder(safePath(target))
})

ipcMain.handle('open-path', async (_event, target) => {
  return shell.openPath(safePath(target))
})

function createWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 920,
    title: 'zhibiao 标书工作台',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  window.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
}

app.whenReady().then(() => {
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
