package com.devicetesting.app

/**
 * The 12 voice-call cases from fut_calls_test_cases_OPENA.json.
 * Lab-only cases stay in the list and the runner marks them Blocked.
 */
object CallsCatalog {
    fun load(): List<TestCase> = listOf(
        TestCase("CALL-FUNC-001", "SIM and voice-service readiness", "functionality", "AUTOMATED"),
        TestCase("CALL-FUNC-002", "Outgoing call initiation", "functionality", "AUTOMATED"),
        TestCase("CALL-FUNC-003", "Incoming call detection", "functionality", "SEMI_AUTOMATED"),
        TestCase("CALL-FUNC-004", "Answered call and termination", "functionality", "SEMI_AUTOMATED"),
        TestCase("CALL-PERF-001", "Outgoing call setup timing (approximate)", "performance", "AUTOMATED"),
        TestCase("CALL-PERF-002", "Incoming notification delay (instrumented)", "performance", "LAB_AUTOMATED"),
        TestCase("CALL-PERF-003", "Call duration observation accuracy", "performance", "AUTOMATED"),
        TestCase("CALL-REL-001", "Repeated outgoing call sessions", "reliability", "AUTOMATED"),
        TestCase("CALL-REL-002", "Long-duration call stability", "reliability", "AUTOMATED"),
        TestCase("CALL-REL-003", "Call recovery after controlled network interruption", "reliability", "LAB_AUTOMATED"),
        TestCase("CALL-SEC-001", "Call permission handling", "security", "AUTOMATED"),
        TestCase("CALL-SEC-002", "Call-data minimization and access control", "security", "AUTOMATED"),
    )
}
