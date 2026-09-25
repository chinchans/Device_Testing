const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("platformConfig", {
  apiBaseUrl: process.env.API_BASE_URL || "http://127.0.0.1:8000"
});

contextBridge.exposeInMainWorld("deviceTestingAPI", {
  openFileDialog: async (options) => {
    return ipcRenderer.invoke("show-open-file-dialog", options || {});
  }
});
