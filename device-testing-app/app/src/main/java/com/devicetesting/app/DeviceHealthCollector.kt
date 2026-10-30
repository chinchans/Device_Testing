package com.devicetesting.app

import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.Build
import android.os.Environment
import android.os.PowerManager
import android.os.StatFs
import org.json.JSONObject

/** Collects phone health snapshots for the monitoring heartbeat. */
object DeviceHealthCollector {
    private const val LOW_STORAGE_BYTES = 500L * 1024L * 1024L // 500 MB

    fun collect(context: Context): JSONObject {
        return JSONObject()
            .put("network", networkHealth(context))
            .put("storage", storageHealth())
            .put("memory", memoryHealth(context))
            .put("thermal", thermalHealth(context))
            .put("test_execution", TestExecutionStatus.toJson())
    }

    private fun networkHealth(context: Context): JSONObject {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val active = cm.activeNetwork
        val caps = active?.let { cm.getNetworkCapabilities(it) }
        val connected = caps != null
        val transport = when {
            caps == null -> "none"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_BLUETOOTH) -> "bluetooth"
            else -> "other"
        }
        val validated = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true
        val internet = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
        return JSONObject()
            .put("connected", connected)
            .put("transport", transport)
            .put("internet", internet)
            .put("validated_internet", validated)
    }

    private fun storageHealth(): JSONObject {
        val path = Environment.getDataDirectory()
        val stat = StatFs(path.path)
        val total = stat.blockCountLong * stat.blockSizeLong
        val free = stat.availableBlocksLong * stat.blockSizeLong
        val used = (total - free).coerceAtLeast(0L)
        val freePct = if (total > 0) (free * 100.0 / total) else 0.0
        return JSONObject()
            .put("total_bytes", total)
            .put("free_bytes", free)
            .put("used_bytes", used)
            .put("free_percent", (freePct * 10).toInt() / 10.0)
            .put("low_storage", free < LOW_STORAGE_BYTES)
    }

    private fun memoryHealth(context: Context): JSONObject {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val info = ActivityManager.MemoryInfo()
        am.getMemoryInfo(info)
        val runtime = Runtime.getRuntime()
        val appUsed = runtime.totalMemory() - runtime.freeMemory()
        val availPct = if (info.totalMem > 0) (info.availMem * 100.0 / info.totalMem) else 0.0
        return JSONObject()
            .put("total_bytes", info.totalMem)
            .put("available_bytes", info.availMem)
            .put("available_percent", (availPct * 10).toInt() / 10.0)
            .put("low_memory", info.lowMemory)
            .put("threshold_bytes", info.threshold)
            .put("app_used_bytes", appUsed)
            .put("app_max_bytes", runtime.maxMemory())
    }

    private fun thermalHealth(context: Context): JSONObject {
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val tenths = intent?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE) ?: Int.MIN_VALUE
        val batteryTempC = if (tenths != Int.MIN_VALUE) tenths / 10.0 else null
        val thermalStatus = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val pm = context.getSystemService(Context.POWER_SERVICE) as PowerManager
            thermalStatusLabel(pm.currentThermalStatus)
        } else {
            "unsupported"
        }
        val overheating = when {
            batteryTempC != null && batteryTempC >= 45.0 -> true
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
                thermalStatus in setOf("severe", "critical", "emergency", "shutdown") -> true
            else -> false
        }
        return JSONObject()
            .put("battery_temp_c", batteryTempC)
            .put("thermal_status", thermalStatus)
            .put("overheating", overheating)
    }

    private fun thermalStatusLabel(status: Int): String = when (status) {
        PowerManager.THERMAL_STATUS_NONE -> "none"
        PowerManager.THERMAL_STATUS_LIGHT -> "light"
        PowerManager.THERMAL_STATUS_MODERATE -> "moderate"
        PowerManager.THERMAL_STATUS_SEVERE -> "severe"
        PowerManager.THERMAL_STATUS_CRITICAL -> "critical"
        PowerManager.THERMAL_STATUS_EMERGENCY -> "emergency"
        PowerManager.THERMAL_STATUS_SHUTDOWN -> "shutdown"
        else -> "unknown"
    }
}
