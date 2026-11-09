const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  showItemInFolder: (target) =>
    ipcRenderer.invoke('show-item-in-folder', target),
  openPath: (target) => ipcRenderer.invoke('open-path', target),
})
