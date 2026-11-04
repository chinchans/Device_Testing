package com.devicetesting.app

import android.content.Context
import org.json.JSONObject

/**
 * Voice-call cases for the Calls screen.
 * The first 12 are the on-device suite. The rest are the field VoWiFi and VoLTE
 * catalogs. Emergency cases stay in the list and the runner does not dial them.
 */
object CallsCatalog {
    private val original = listOf(
        TestCase("CALL-FUNC-001", "SIM and voice-service readiness", "functionality", "AUTOMATED"),
        TestCase("CALL-FUNC-002", "Outgoing call initiation", "functionality", "AUTOMATED", "place_saved_number"),
        TestCase("CALL-FUNC-003", "Incoming call detection", "functionality", "SEMI_AUTOMATED", "wait_for_incoming"),
        TestCase("CALL-FUNC-004", "Answered call and termination", "functionality", "SEMI_AUTOMATED"),
        TestCase("CALL-PERF-001", "Outgoing call setup timing (approximate)", "performance", "AUTOMATED", "place_saved_number"),
        TestCase("CALL-PERF-002", "Incoming notification delay (instrumented)", "performance", "LAB_AUTOMATED"),
        TestCase("CALL-PERF-003", "Call duration observation accuracy", "performance", "AUTOMATED", "place_saved_number"),
        TestCase("CALL-REL-001", "Repeated outgoing call sessions", "reliability", "AUTOMATED", "place_saved_number"),
        TestCase("CALL-REL-002", "Long-duration call stability", "reliability", "AUTOMATED", "place_saved_number"),
        TestCase("CALL-REL-003", "Call recovery after controlled network interruption", "reliability", "LAB_AUTOMATED"),
        TestCase("CALL-SEC-001", "Call permission handling", "security", "AUTOMATED"),
        TestCase("CALL-SEC-002", "Call-data minimization and access control", "security", "AUTOMATED"),
    )

    fun load(context: Context): List<TestCase> {
        val field = FIELD_FILES.flatMap { loadField(context, it) }
        return original + field
    }

    fun isVoWifi(test: TestCase): Boolean = test.title.startsWith("VoWiFi:")

    fun needsSavedNumber(test: TestCase): Boolean {
        if (test.action == "blocked_emergency" || test.action == "confirm_only") return false
        if (test.action == "wait_for_incoming") return false
        return test.action == "place_saved_number" ||
            test.action == "place_saved_number_after_setting" ||
            test.action == "observe_call_while_radio_changes"
    }

    private fun loadField(context: Context, asset: String): List<TestCase> {
        val text = context.assets.open(asset).bufferedReader().use { it.readText() }
        val list = JSONObject(text).getJSONArray("test_cases")
        val cases = mutableListOf<TestCase>()
        for (i in 0 until list.length()) {
            val meta = list.getJSONObject(i).getJSONObject("test_metadata")
            val id = meta.getString("testCaseId")
            val rawTitle = meta.getString("title")
            val bearer = meta.optString("bearer")
            val title = if (bearer.isBlank()) rawTitle else "$bearer: $rawTitle"
            val rawSuite = meta.optString("suite", "functionality")
            val suite = if (rawSuite == "functionality" || rawSuite == "reliability") rawSuite else "functionality"
            val execution = meta.optString("execution_mode", "SEMI_AUTOMATED")
            val rawAction = meta.optString("app_action")
            val action = when {
                rawAction == "blocked_emergency" || execution == "BLOCKED" -> "blocked_emergency"
                isIdleMove(id, rawTitle) -> "confirm_only"
                else -> rawAction
            }
            cases += TestCase(id, title, suite, execution, action)
        }
        return cases
    }

    private fun isIdleMove(id: String, title: String): Boolean {
        if (id in IDLE_IDS) return true
        val text = title.lowercase()
        return text.startsWith("idle")
    }

    private val FIELD_FILES = listOf(
        "calls/fut_vowifi_field_call_cases.json",
        "calls/fut_volte_field_call_cases.json",
    )

    private val IDLE_IDS = setOf(
        "eTinT_CA_07",
        "eTinT_MOB_LIVE_11",
        "eTinT_MOB_LIVE_12",
    )
}
