package com.devicetesting.app

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.Log
import org.json.JSONObject
import java.io.BufferedOutputStream
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Sends device registration + periodic heartbeats (incl. health metrics) to the monitor API.
 * Runs on a background scheduler while the host activity is alive.
 */
class HeartbeatReporter(
    private val context: Context,
    private val onStatus: ((String) -> Unit)? = null,
) {
    private val scheduler = Executors.newSingleThreadScheduledExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val started = AtomicBoolean(false)
    private var future: ScheduledFuture<*>? = null
    private val registered = AtomicBoolean(false)

    private val deviceId: String by lazy {
        Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
            ?: "unknown-device"
    }

    private val deviceName: String by lazy {
        val model = Build.MODEL?.trim().orEmpty()
        val manufacturer = Build.MANUFACTURER?.trim().orEmpty()
        when {
            model.isNotEmpty() && manufacturer.isNotEmpty() &&
                !model.startsWith(manufacturer, ignoreCase = true) ->
                "$manufacturer $model"
            model.isNotEmpty() -> model
            else -> "Android Device"
        }
    }

    private val transport: String
        get() {
            val raw = context.getString(R.string.monitor_transport).trim().lowercase()
            return if (raw == "wifi" || raw == "lan" || raw == "local") "wifi" else "cloud"
        }

    private val baseUrl: String
        get() {
            val url = if (transport == "wifi") {
                context.getString(R.string.monitor_wifi_base_url)
            } else {
                context.getString(R.string.monitor_cloud_base_url)
            }
            return url.trimEnd('/')
        }

    fun start() {
        if (!started.compareAndSet(false, true)) return
        publishStatus("Monitor ($transport): connecting…")
        scheduler.execute {
            runCatching {
                ensureRegistered()
                sendHeartbeat()
                publishStatus("Monitor ($transport): OK ($deviceName)")
            }.onFailure { publishStatus("Monitor ($transport): FAIL — ${shortError(it)}") }
        }
        future = scheduler.scheduleAtFixedRate(
            {
                runCatching {
                    ensureRegistered()
                    sendHeartbeat()
                    publishStatus("Monitor ($transport): OK ($deviceName)")
                }.onFailure {
                    Log.w(TAG, "heartbeat failed: ${it.message}")
                    publishStatus("Monitor ($transport): FAIL — ${shortError(it)}")
                }
            },
            INTERVAL_SEC,
            INTERVAL_SEC,
            TimeUnit.SECONDS
        )
        Log.i(TAG, "HeartbeatReporter started mode=$transport → $baseUrl device=$deviceId")
    }

    fun stop() {
        future?.cancel(false)
        future = null
        started.set(false)
        scheduler.shutdownNow()
    }

    private fun publishStatus(message: String) {
        Log.i(TAG, message)
        val cb = onStatus ?: return
        mainHandler.post { cb(message) }
    }

    private fun shortError(t: Throwable): String {
        val raw = (t.message ?: t.javaClass.simpleName).replace('\n', ' ')
        return if (raw.length <= 120) raw else raw.take(117) + "…"
    }

    private fun ensureRegistered() {
        if (registered.get()) return
        val body = JSONObject()
            .put("device_id", deviceId)
            .put("device_name", deviceName)
            .put("model", Build.MODEL ?: "")
        postJson("/api/monitor/register", body)
        registered.set(true)
    }

    private fun sendHeartbeat() {
        val battery = readBattery()
        val health = DeviceHealthCollector.collect(context)
        val body = JSONObject()
            .put("device_id", deviceId)
            .put("device_name", deviceName)
            .put("active", true)
            .put("battery_percent", battery.percent)
            .put("charging", battery.charging)
            .put("app_state", "foreground")
            .put("network", health.optJSONObject("network"))
            .put("storage", health.optJSONObject("storage"))
            .put("memory", health.optJSONObject("memory"))
            .put("thermal", health.optJSONObject("thermal"))
            .put("test_execution", health.optJSONObject("test_execution"))
        postJson("/api/monitor/heartbeat", body)
    }

    private data class BatteryInfo(val percent: Double, val charging: Boolean)

    private fun readBattery(): BatteryInfo {
        val intent = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        val level = intent?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = intent?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1
        val percent = if (level >= 0 && scale > 0) (level * 100.0 / scale) else 0.0
        val status = intent?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1
        val charging = status == BatteryManager.BATTERY_STATUS_CHARGING ||
            status == BatteryManager.BATTERY_STATUS_FULL
        return BatteryInfo(percent = (percent * 10).toInt() / 10.0, charging = charging)
    }

    private fun postJson(path: String, body: JSONObject) {
        val url = URL("$baseUrl$path")
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 12_000
            readTimeout = 12_000
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=utf-8")
            setRequestProperty("Accept", "application/json")
        }
        MonitorSsl.apply(context, conn)
        try {
            BufferedOutputStream(conn.outputStream).use { out ->
                out.write(body.toString().toByteArray(Charsets.UTF_8))
                out.flush()
            }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.let { BufferedReader(InputStreamReader(it)).use { r -> r.readText() } }
            if (code !in 200..299) {
                throw IllegalStateException("HTTP $code for $path: $text")
            }
            Log.d(TAG, "OK $path → $text")
        } finally {
            conn.disconnect()
        }
    }

    companion object {
        private const val TAG = "HeartbeatReporter"
        private const val INTERVAL_SEC = 30L
    }
}
