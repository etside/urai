'use strict';

const { contextBridge, ipcRenderer } = require('electron');

// Minimal, explicit surface. No filesystem or process access is exposed.
contextBridge.exposeInMainWorld('urai', {
  retry: () => ipcRenderer.invoke('urai:retry'),
  log: () => ipcRenderer.invoke('urai:log'),
  open: (url) => ipcRenderer.invoke('urai:openExternal', String(url)),
  versions: {
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    node: process.versions.node,
  },
});
