package com.devicetesting.app

import android.content.Context
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.wifi.SupplicantState
import android.net.wifi.WifiConfiguration
import android.net.wifi.WifiManager
import android.os.SystemClock

/**
 * Turns Wi-Fi on and waits until Android joins a network that is already saved
 * on the phone. The hotspot is turned off first, because the radio cannot be a
 * Wi-Fi client while it is hosting the hotspot. The network name is not recorded.
 */
class WifiConnector(context: Context) {
    private val app = context.applicationContext
    private val connectivity = app.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

    /** Null when a saved network is connected. Otherwise a Blocked reason. "stopped" when the user stops. */
    fun joinSavedNetwork(shouldStop: () -> Boolean, onStatus: (String) -> Unit): String? {
        if (shouldStop()) return STOPPED
        val manager = wifi() ?: return "This phone has no Wi-Fi."
        if (!app.packageManager.hasSystemFeature(PackageManager.FEATURE_WIFI)) {
            return "This phone has no Wi-Fi."
        }
        if (isConnected(manager)) return null
        if (hotspotOn(manager)) {
            onStatus("Turning the hotspot off so Wi-Fi can start")
            stopHotspot(manager)
            val hotspotDeadline = SystemClock.elapsedRealtime() + ENABLE_MS
            while (hotspotOn(wifi() ?: manager) && SystemClock.elapsedRealtime() < hotspotDeadline) {
                if (shouldStop()) return STOPPED
                sleep()
            }
            if (hotspotOn(wifi() ?: manager)) {
                return "Turn the hotspot off. Wi-Fi cannot turn on while the hotspot is using the radio."
            }
        }
        onStatus("Turning Wi-Fi on")
        val enableDeadline = SystemClock.elapsedRealtime() + ENABLE_MS
        var nextRequest = 0L
        while (SystemClock.elapsedRealtime() < enableDeadline) {
            if (shouldStop()) return STOPPED
            val current = wifi() ?: return "This phone has no Wi-Fi."
            if (current.isWifiEnabled) break
            if (SystemClock.elapsedRealtime() >= nextRequest) {
                try {
                    @Suppress("DEPRECATION")
                    current.setWifiEnabled(true)
                } catch (_: SecurityException) {
                    return "The app could not turn Wi-Fi on."
                }
                nextRequest = SystemClock.elapsedRealtime() + 2_000
            }
            onStatus("Turning Wi-Fi on")
            sleep()
        }
        val enabled = wifi()
        if (enabled == null || !enabled.isWifiEnabled) return "The app could not turn Wi-Fi on."
        try {
            enabled.reconnect()
        } catch (_: Exception) {
        }
        val deadline = SystemClock.elapsedRealtime() + WAIT_MS
        while (SystemClock.elapsedRealtime() < deadline) {
            if (shouldStop()) return STOPPED
            val current = wifi() ?: return "This phone has no Wi-Fi."
            if (isConnected(current)) return null
            onStatus("Waiting for a saved Wi-Fi network")
            sleep()
        }
        return "Wi-Fi is on, but the phone did not join a saved network."
    }

    @Suppress("DEPRECATION")
    private fun isConnected(manager: WifiManager): Boolean {
        val network = connectivity.getNetworkInfo(ConnectivityManager.TYPE_WIFI)
        if (network?.isConnected == true) return true
        val info = manager.connectionInfo ?: return false
        return info.supplicantState == SupplicantState.COMPLETED && info.ipAddress != 0
    }

    private fun hotspotOn(manager: WifiManager): Boolean {
        val state = try {
            val method = manager.javaClass.getMethod("getWifiApState")
            method.invoke(manager) as? Int
        } catch (_: Exception) {
            null
        } ?: return false
        return state == AP_ENABLING || state == AP_ENABLED
    }

    private fun stopHotspot(manager: WifiManager) {
        try {
            val stop = ConnectivityManager::class.java.getMethod("stopTethering", Int::class.javaPrimitiveType)
            stop.invoke(connectivity, TETHERING_WIFI)
        } catch (_: Exception) {
        }
        try {
            val method = manager.javaClass.getMethod(
                "setWifiApEnabled",
                WifiConfiguration::class.java,
                Boolean::class.javaPrimitiveType,
            )
            method.invoke(manager, null, false)
        } catch (_: Exception) {
        }
    }

    private fun wifi(): WifiManager? = app.getSystemService(Context.WIFI_SERVICE) as? WifiManager

    private fun sleep() {
        try {
            Thread.sleep(500)
        } catch (_: InterruptedException) {
        }
    }

    companion object {
        const val STOPPED = "stopped"
        private const val ENABLE_MS = 20_000L
        private const val WAIT_MS = 45_000L
        private const val TETHERING_WIFI = 0
        private const val AP_ENABLING = 12
        private const val AP_ENABLED = 13
    }
}
