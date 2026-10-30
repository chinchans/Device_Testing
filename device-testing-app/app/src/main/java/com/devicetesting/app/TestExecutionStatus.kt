package com.devicetesting.app

import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import org.json.JSONObject

/**
 * Shared test-execution snapshot read by [HeartbeatReporter].
 * Updated from MainActivity / runners when a suite starts, progresses, or finishes.
 */
object TestExecutionStatus {
    private val running = AtomicBoolean(false)
    private val currentTest = AtomicReference<String?>(null)
    private val currentSuite = AtomicReference<String?>(null)
    private val failureCount = AtomicInteger(0)
    private val startedAtMs = AtomicLong(0L)

    fun setIdle(failures: Int = failureCount.get()) {
        running.set(false)
        currentTest.set(null)
        currentSuite.set(null)
        failureCount.set(failures.coerceAtLeast(0))
        startedAtMs.set(0L)
    }

    fun setRunning(suite: String?, testTitle: String?, failures: Int = failureCount.get()) {
        if (!running.getAndSet(true)) {
            startedAtMs.set(System.currentTimeMillis())
        }
        currentSuite.set(suite)
        currentTest.set(testTitle)
        failureCount.set(failures.coerceAtLeast(0))
    }

    fun setCurrentTest(testTitle: String?) {
        currentTest.set(testTitle)
    }

    fun addFailure() {
        failureCount.incrementAndGet()
    }

    fun setFailures(count: Int) {
        failureCount.set(count.coerceAtLeast(0))
    }

    fun toJson(): JSONObject {
        val isRunning = running.get()
        val started = startedAtMs.get()
        val durationSec = if (isRunning && started > 0L) {
            ((System.currentTimeMillis() - started) / 1000.0)
        } else {
            0.0
        }
        return JSONObject()
            .put("state", if (isRunning) "running" else "idle")
            .put("current_test", currentTest.get())
            .put("current_suite", currentSuite.get())
            .put("failures", failureCount.get())
            .put("duration_sec", (durationSec * 10).toInt() / 10.0)
    }
}
