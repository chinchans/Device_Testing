package com.devicetesting.app

import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import org.json.JSONArray
import org.json.JSONObject

/**
 * Shared test-execution snapshot read by [HeartbeatReporter].
 * Tracks the suite case list so Device Monitoring can show id / name / status.
 */
object TestExecutionStatus {
    data class CaseProgress(
        val id: String,
        val title: String,
        @Volatile var status: String, // pending | running | PASS | FAIL | ...
    )

    private val running = AtomicBoolean(false)
    private val currentTest = AtomicReference<String?>(null)
    private val currentSuite = AtomicReference<String?>(null)
    private val currentFeature = AtomicReference<String?>(null)
    private val failureCount = AtomicInteger(0)
    private val startedAtMs = AtomicLong(0L)
    private val cases = CopyOnWriteArrayList<CaseProgress>()

    fun setIdle(failures: Int = 0) {
        clearSnapshot(failures)
    }

    fun beginSuite(feature: String, suite: String, suiteCases: List<TestCase>) {
        running.set(true)
        startedAtMs.set(System.currentTimeMillis())
        currentFeature.set(feature)
        currentSuite.set(suite)
        currentTest.set(null)
        failureCount.set(0)
        synchronized(cases) {
            cases.clear()
            suiteCases.forEach { test ->
                cases += CaseProgress(test.id, test.title, "pending")
            }
        }
    }

    fun setRunning(suite: String?, testTitle: String?, failures: Int = failureCount.get()) {
        if (!running.getAndSet(true)) {
            startedAtMs.set(System.currentTimeMillis())
        }
        currentSuite.set(suite)
        currentTest.set(testTitle)
        failureCount.set(failures.coerceAtLeast(0))
        if (!testTitle.isNullOrBlank()) {
            synchronized(cases) {
                cases.forEach { c ->
                    when {
                        c.id == testTitle || c.title == testTitle -> c.status = "running"
                        c.status == "running" -> c.status = "pending"
                    }
                }
            }
        }
    }

    fun markCaseRunning(caseId: String) {
        currentTest.set(caseId)
        synchronized(cases) {
            cases.forEach { c ->
                when {
                    c.id == caseId -> c.status = "running"
                    c.status == "running" -> c.status = "pending"
                }
            }
        }
    }

    fun markCaseFinished(caseId: String, verdict: String) {
        val normalized = verdict.ifBlank { "NOT_VERIFIED" }
        synchronized(cases) {
            cases.find { it.id == caseId }?.status = normalized
        }
        if (normalized == "FAIL") {
            failureCount.set(cases.count { it.status == "FAIL" })
        } else {
            failureCount.set(cases.count { it.status == "FAIL" })
        }
    }

    fun finishSuite(failures: Int = cases.count { it.status == "FAIL" }) {
        // Drop suite details so Device Monitoring shows Idle only when not running.
        clearSnapshot(failures)
    }

    private fun clearSnapshot(failures: Int = 0) {
        running.set(false)
        currentTest.set(null)
        currentSuite.set(null)
        currentFeature.set(null)
        failureCount.set(failures.coerceAtLeast(0))
        startedAtMs.set(0L)
        synchronized(cases) {
            cases.clear()
        }
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

    fun isRunning(): Boolean = running.get()

    fun toJson(): JSONObject {
        val isRunning = running.get()
        val started = startedAtMs.get()
        val durationSec = if (isRunning && started > 0L) {
            ((System.currentTimeMillis() - started) / 1000.0)
        } else {
            0.0
        }
        val caseJson = JSONArray()
        synchronized(cases) {
            cases.forEach { c ->
                caseJson.put(
                    JSONObject()
                        .put("id", c.id)
                        .put("title", c.title)
                        .put("status", c.status)
                )
            }
        }
        return JSONObject()
            .put("state", if (isRunning) "running" else "idle")
            .put("feature", currentFeature.get())
            .put("current_test", currentTest.get())
            .put("current_suite", currentSuite.get())
            .put("failures", failureCount.get())
            .put("duration_sec", (durationSec * 10).toInt() / 10.0)
            .put("cases", caseJson)
            .put("case_count", caseJson.length())
    }
}
