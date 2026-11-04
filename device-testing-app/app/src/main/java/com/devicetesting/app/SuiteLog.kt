package com.devicetesting.app

import android.content.Context
import android.os.Environment
import android.util.Log
import java.io.BufferedReader
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * Streams the phone log for one suite into a text file.
 * On a rooted phone, logcat is started through superuser so every buffer is included.
 * Otherwise logcat runs as this app, which sees the full log only when READ_LOGS is granted.
 */
class SuiteLog(context: Context) {
    private val app = context.applicationContext
    private val startedAt = System.currentTimeMillis()

    fun startedAtMs(): Long = startedAt
    private var process: Process? = null
    private var reader: Thread? = null
    private var file: File? = null
    private var logPid: Int? = null
    private var rooted = false

    fun start(label: String, feature: String = "", onStatus: (String) -> Unit = {}) {
        if (file != null) return
        try {
            val stamp = stamp(startedAt - 1_000)
            val dir = File(app.filesDir, "suite_logs").apply { mkdirs() }
            val safe = label.replace(Regex("[^A-Za-z0-9]+"), "_").trim('_').ifEmpty { "suite" }
            val feat = feature.replace(Regex("[^A-Za-z0-9]+"), "_").trim('_').lowercase()
            val out = File(dir, if (feat.isEmpty()) "${safe}_$startedAt.txt" else "${feat}_${safe}_$startedAt.txt")
            file = out
            val running = openCapture(stamp, onStatus)
            out.writeText(buildString {
                if (feat.isNotEmpty()) append("Feature: ").append(feat).append('\n')
                append("Suite: ").append(label).append('\n')
                append("Started: ").append(stamp(startedAt)).append('\n')
                append("Buffers: main, system, crash, radio, events\n")
                append(if (rooted) "Capture: full log as root\n\n" else "Capture: logcat as the app\n\n")
            })
            Log.i(TAG, "SUITE_LOG_START $label root=$rooted")
            process = running.process
            reader = Thread {
                try {
                    running.lines.use { input ->
                        out.outputStream().bufferedWriter().use { sink ->
                            while (true) {
                                val line = input.readLine() ?: break
                                sink.append(line)
                                sink.append('\n')
                            }
                        }
                    }
                } catch (_: Exception) {
                }
            }.also {
                it.name = "suite-log"
                it.start()
            }
        } catch (_: Exception) {
        }
    }

    fun save(label: String): File? {
        if (file == null) start(label)
        Log.i(TAG, "SUITE_LOG_END $label")
        stopCapture()
        val saved = file ?: return null
        try {
            saved.appendText("\nSaved: ${stamp(System.currentTimeMillis())}\n")
        } catch (_: Exception) {
        }
        copyToDownloads(saved)
        return saved
    }

    private fun openCapture(stamp: String, onStatus: (String) -> Unit): Capture {
        val su = findSu()
        if (su != null) {
            onStatus("Allow root to record the full phone log")
            try {
                val command = "echo \$\$; exec logcat -v threadtime -T ${shellQuote(stamp)} -b main -b system -b crash -b radio -b events"
                val rootProcess = ProcessBuilder(su, "-c", command).redirectErrorStream(true).start()
                val lines = rootProcess.inputStream.bufferedReader()
                val first = readLine(lines, ROOT_WAIT_MS)
                val pid = first?.toIntOrNull()
                if (pid != null && pid > 0) {
                    logPid = pid
                    rooted = true
                    return Capture(rootProcess, lines)
                }
                rootProcess.destroy()
                try {
                    lines.close()
                } catch (_: Exception) {
                }
            } catch (_: Exception) {
            }
        }
        val appProcess = ProcessBuilder(
            "logcat",
            "-v", "threadtime",
            "-T", stamp,
            "-b", "main",
            "-b", "system",
            "-b", "crash",
            "-b", "radio",
            "-b", "events",
        ).redirectErrorStream(true).start()
        return Capture(appProcess, appProcess.inputStream.bufferedReader())
    }

    private fun stopCapture() {
        val pid = logPid
        val su = if (rooted && pid != null) findSu() else null
        try {
            process?.destroy()
            reader?.join(5_000)
        } catch (_: Exception) {
        }
        if (su != null && pid != null) {
            try {
                ProcessBuilder(su, "-c", "kill $pid").start().waitFor(2, TimeUnit.SECONDS)
            } catch (_: Exception) {
            }
        }
        process = null
    }

    private fun findSu(): String? {
        val candidates = listOf(
            "/system/bin/su",
            "/system/xbin/su",
            "/sbin/su",
            "/debug_ramdisk/su",
        )
        candidates.firstOrNull { File(it).exists() }?.let { return it }
        return try {
            val which = ProcessBuilder("sh", "-c", "command -v su").redirectErrorStream(true).start()
            val path = which.inputStream.bufferedReader().use { it.readLine() }?.trim().orEmpty()
            which.waitFor(2, TimeUnit.SECONDS)
            path.takeIf { it.isNotEmpty() && File(it).exists() }
        } catch (_: Exception) {
            null
        }
    }

    private fun readLine(lines: BufferedReader, timeoutMs: Long): String? {
        val value = AtomicReference<String?>(null)
        val done = CountDownLatch(1)
        Thread {
            try {
                value.set(lines.readLine())
            } catch (_: Exception) {
            } finally {
                done.countDown()
            }
        }.start()
        return if (done.await(timeoutMs, TimeUnit.MILLISECONDS)) value.get() else null
    }

    private fun copyToDownloads(file: File) {
        try {
            val downloads = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS)
            if (!downloads.exists()) downloads.mkdirs()
            file.copyTo(File(downloads, file.name), overwrite = true)
        } catch (_: Exception) {
        }
    }

    private fun shellQuote(value: String): String = "'" + value.replace("'", "'\\''") + "'"

    private fun stamp(timeMs: Long): String = SimpleDateFormat("MM-dd HH:mm:ss.SSS", Locale.US).format(Date(timeMs))

    private class Capture(val process: Process, val lines: BufferedReader)

    companion object {
        private const val TAG = "SuiteLog"
        private const val ROOT_WAIT_MS = 60_000L
    }
}
