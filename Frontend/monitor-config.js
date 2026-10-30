/**
 * Device Monitoring transport switch.
 * Set mode to "wifi" (same LAN → local FastAPI) or "cloud" (AppSail).
 * Env overrides (optional): MONITOR_MODE, MONITOR_WIFI_API_BASE_URL,
 * MONITOR_CLOUD_API_BASE_URL, MONITOR_API_BASE_URL (forces URL, ignores mode).
 */
module.exports = {
  mode: "cloud",
  wifiBaseUrl: "http://127.0.0.1:8000",
  cloudBaseUrl:
    "https://device-monitor-50047269636.development.catalystappsail.in",
};
