const { contextBridge, ipcRenderer } = require("electron");

const monitorConfig = require("./monitor-config");

function normalizeMode(value) {
  const mode = String(value || "cloud").trim().toLowerCase();
  if (mode === "wifi" || mode === "lan" || mode === "local") return "wifi";
  return "cloud";
}

const monitorMode = normalizeMode(
  process.env.MONITOR_MODE || monitorConfig.mode
);

const wifiBaseUrl = (
  process.env.MONITOR_WIFI_API_BASE_URL ||
  monitorConfig.wifiBaseUrl ||
  "http://127.0.0.1:8000"
).replace(/\/$/, "");

const cloudBaseUrl = (
  process.env.MONITOR_CLOUD_API_BASE_URL ||
  monitorConfig.cloudBaseUrl ||
  "https://device-monitor-50047269636.development.catalystappsail.in"
).replace(/\/$/, "");

const monitorApiBaseUrl = (
  process.env.MONITOR_API_BASE_URL ||
  (monitorMode === "wifi" ? wifiBaseUrl : cloudBaseUrl)
).replace(/\/$/, "");

contextBridge.exposeInMainWorld("platformConfig", {
  // Main Device Testing backend (RAG / execution) — usually local FastAPI
  apiBaseUrl: process.env.API_BASE_URL || "http://127.0.0.1:8000",
  // Device Monitoring: wifi → local FastAPI, cloud → AppSail
  monitorMode,
  monitorWifiBaseUrl: wifiBaseUrl,
  monitorCloudBaseUrl: cloudBaseUrl,
  monitorApiBaseUrl,
});

contextBridge.exposeInMainWorld("deviceTestingAPI", {
  openFileDialog: async (options) => {
    return ipcRenderer.invoke("show-open-file-dialog", options || {});
  },
  openFilesDialog: async (options) => {
    return ipcRenderer.invoke("show-open-files-dialog", options || {});
  },
  openFolderDialog: async (options) => {
    return ipcRenderer.invoke("show-open-folder-dialog", options || {});
  }
});
