const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('vela', {
  action: (command, value) => ipcRenderer.send('vela:action', command, value),
  onState: callback => ipcRenderer.on('vela:state', (_event, state) => callback(state)),
  onSuggestions: callback => ipcRenderer.on('vela:suggestions', (_event, state) => callback(state)),
  onFocusAddress: callback => ipcRenderer.on('vela:focus-address', (_event, openSuggestions) => callback(openSuggestions)),
  onSettingsFeedback: callback => ipcRenderer.on('vela:settings-feedback', (_event, message) => callback(message)),
  onInvalidAddress: callback => ipcRenderer.on('vela:invalid-address', () => callback())
});
