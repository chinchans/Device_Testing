package com.devicetesting.app

import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.provider.CallLog
import androidx.core.content.ContextCompat
import java.util.concurrent.TimeUnit

/**
 * Checks the system call log, then new system-log lines, for an outgoing call
 * to the saved number. The dialed number is not copied into the result text.
 */
class CallEvidence(context: Context) {
    private val app = context.applicationContext

    data class Hit(val source: String, val durationSec: Int)

    fun hasCallLogPermission(): Boolean =
        ContextCompat.checkSelfPermission(app, android.Manifest.permission.READ_CALL_LOG) ==
            PackageManager.PERMISSION_GRANTED

    @SuppressLint("MissingPermission")
    fun outgoingSince(number: String, sinceMs: Long): Hit? {
        if (!hasCallLogPermission()) return null
        val cursor = try {
            app.contentResolver.query(
                CallLog.Calls.CONTENT_URI,
                arrayOf(CallLog.Calls.NUMBER, CallLog.Calls.DATE, CallLog.Calls.DURATION, CallLog.Calls.TYPE),
                "${CallLog.Calls.DATE} >= ? AND ${CallLog.Calls.TYPE} = ?",
                arrayOf((sinceMs - CLOCK_SKEW_MS).toString(), CallLog.Calls.OUTGOING_TYPE.toString()),
                "${CallLog.Calls.DATE} DESC",
            )
        } catch (_: SecurityException) {
            null
        } ?: return null
        cursor.use {
            val numberCol = it.getColumnIndex(CallLog.Calls.NUMBER)
            val durationCol = it.getColumnIndex(CallLog.Calls.DURATION)
            if (numberCol < 0) return null
            while (it.moveToNext()) {
                val logged = it.getString(numberCol).orEmpty()
                if (!sameNumber(number, logged)) continue
                val duration = if (durationCol < 0) 0 else it.getInt(durationCol)
                return Hit("system call log", duration.coerceAtLeast(0))
            }
        }
        return null
    }

    fun logcatSnapshot(): String {
        return try {
            val process = ProcessBuilder("logcat", "-d", "-t", "250", "-b", "main", "-b", "system", "-b", "radio")
                .redirectErrorStream(true)
                .start()
            val text = process.inputStream.bufferedReader().use { reader ->
                val buffer = CharArray(MAX_LOG_CHARS)
                val read = reader.read(buffer)
                if (read <= 0) "" else String(buffer, 0, read)
            }
            process.waitFor(2, TimeUnit.SECONDS)
            text
        } catch (_: Exception) {
            ""
        }
    }

    /** True when a new system-log line says the far end is being alerted. */
    fun sawNewAlerting(before: String): Boolean {
        val seen = before.lines().toHashSet()
        val fresh = logcatSnapshot().lines().filter { line -> line.isNotBlank() && line !in seen }
        if (fresh.isEmpty()) return false
        val lower = fresh.joinToString("\n").lowercase()
        return ALERT_MARKERS.any { lower.contains(it) }
    }

    /** True when lines that appeared after the dial mention this number and a call event. */
    fun newLogConfirms(before: String, after: String, number: String): Boolean {
        val digits = number.filter { it.isDigit() }
        if (digits.length < 3) return false
        val seen = before.lines().toHashSet()
        val fresh = after.lines().filter { line -> line.isNotBlank() && line !in seen }
        if (fresh.isEmpty()) return false
        val blob = fresh.joinToString("\n")
        val tail = digits.takeLast(minOf(8, digits.length))
        if (!blob.contains(digits) && !blob.contains(tail)) return false
        val lower = blob.lowercase()
        return CALL_MARKERS.any { lower.contains(it) }
    }

    companion object {
        private const val CLOCK_SKEW_MS = 5_000L
        private const val MAX_LOG_CHARS = 48_000
        private val CALL_MARKERS = listOf(
            "offhook", "callstate", "call_state", "telecom", "ims", "outgoing",
        )
        private val ALERT_MARKERS = listOf(
            "alerting", "call_state_alerting", "precise_call_state: alerting",
        )

        fun sameNumber(saved: String, logged: String): Boolean {
            val a = saved.filter { it.isDigit() }
            val b = logged.filter { it.isDigit() }
            if (a.isEmpty() || b.isEmpty()) return false
            if (a == b) return true
            val n = minOf(8, a.length, b.length)
            return n >= 7 && a.takeLast(n) == b.takeLast(n)
        }
    }
}
