package com.devicetesting.app

import android.os.SystemClock
import android.telephony.TelephonyManager

/**
 * Runs the calls catalog on the phone.
 * Outgoing cases dial the saved number and pass only when the system call log
 * or a new system-log line shows that call. The number is not written into results.
 */
class CallsRunner(
    private val watch: CallWatch,
    private val evidence: CallEvidence,
    private val confirm: (String) -> Boolean,
    private val placeCall: () -> Boolean,
    private val endCall: () -> Boolean,
    private val savedNumber: () -> String,
    private val shouldStop: () -> Boolean,
    private val onStatus: (String) -> Unit,
) {
    fun run(test: TestCase): CaseResult {
        val outcome = try {
            dispatch(test)
        } catch (e: SecurityException) {
            Outcome("BLOCKED", "Phone permission is required")
        } catch (e: Exception) {
            Outcome("FAIL", e.message ?: e.javaClass.simpleName)
        }
        return CaseResult(test.id, test.title, test.suite, outcome.verdict, outcome.detail)
    }

    private fun dispatch(test: TestCase): Outcome {
        if (test.action == "blocked_emergency") {
            return blocked("This app does not place or receive emergency calls. The case is listed and is not executed.")
        }
        return when (test.id) {
            "CALL-FUNC-001" -> readiness()
            "CALL-FUNC-002" -> outgoing()
            "CALL-FUNC-003" -> incoming()
            "CALL-FUNC-004" -> answered()
            "CALL-PERF-001" -> setupTiming()
            "CALL-PERF-002" -> blocked("Needs a lab reference phone. This app cannot time the caller's start.")
            "CALL-PERF-003" -> durationCheck()
            "CALL-REL-001" -> repeatedOutgoing()
            "CALL-REL-002" -> holdCall()
            "CALL-REL-003" -> blocked("Needs an approved lab network interruption. Not run on this phone.")
            "CALL-SEC-001" -> permissionDenial()
            "CALL-SEC-002" -> dataMinimization()
            else -> fieldCase(test)
        }
    }

    /**
     * Field VoWiFi and VoLTE cases. The phone dials only the saved number.
     * Conditions the phone cannot create, such as poor signal or a handover,
     * are confirmed by the tester. Emergency cases never reach this method.
     */
    private fun fieldCase(test: TestCase): Outcome {
        val setup = prepareField(test)
        if (setup != null) return setup
        val outcome = when (test.action) {
            "place_saved_number", "place_saved_number_after_setting" -> outgoingBehavior(test)
            "wait_for_incoming" -> incomingBehavior(test)
            "observe_call_while_radio_changes" -> fieldMobility(test)
            "confirm_only" -> confirmOnly(test)
            else -> na("No on-phone action is mapped for this case")
        }
        return confirmBehavior(test, outcome)
    }

    private fun prepareField(test: TestCase): Outcome? {
        if (test.action == "observe_call_while_radio_changes" || test.action == "confirm_only") return null
        val ask = test.action == "place_saved_number_after_setting" ||
            needsFieldSetup(test) ||
            test.id in BEHAVIOR_CHECK ||
            test.id in MUST_NOT_ARRIVE ||
            test.id in MUST_NOT_CONNECT ||
            test.id in NOT_ANSWERED
        if (!ask) return null
        onStatus(test.title)
        val ok = confirm("Set this up, then tap Pass:\n${test.title}")
        if (shouldStop()) return unverified("Stopped during setup")
        if (!ok) return fail("The setup for this case was not confirmed")
        return null
    }

    private fun needsFieldSetup(test: TestCase): Boolean {
        val text = test.title.lowercase()
        return SETUP_HINTS.any { it in text }
    }

    private fun outgoingBehavior(test: TestCase): Outcome {
        return when (test.id) {
            "eTinT_MO_01" -> holdCall(LONG_HOLD_MS)
            in CANCEL_IDS -> cancelDuringSetup()
            in MUST_NOT_CONNECT -> expectNoConnection()
            in DROP_DURING -> dropDuringCall()
            "eTinT_MO_20" -> dtmfCall()
            else -> outgoing()
        }
    }

    private fun incomingBehavior(test: TestCase): Outcome {
        return when (test.id) {
            in MUST_NOT_ARRIVE -> expectNoIncoming()
            in NOT_ANSWERED -> incomingLeftUnanswered()
            else -> incoming()
        }
    }

    private fun confirmBehavior(test: TestCase, outcome: Outcome): Outcome {
        if (outcome.verdict != "PASS" || test.id !in BEHAVIOR_CHECK) return outcome
        onStatus(test.title)
        val ok = confirm("Did the call behave this way?\n${test.title}")
        if (shouldStop()) return unverified("Stopped during the behavior check")
        if (!ok) return fail("The tester did not confirm the expected call behavior.")
        return pass("${outcome.detail} The tester confirmed the expected behavior.")
    }

    private fun confirmOnly(test: TestCase): Outcome {
        onStatus(test.title)
        val ok = confirm("Do this while the phone is idle, then tap Pass:\n${test.title}")
        if (shouldStop()) return unverified("Stopped during the idle check")
        if (!ok) return fail("The idle radio change was not confirmed")
        return pass("The tester confirmed the idle radio change. No call is placed for this case.")
    }

    private fun fieldMobility(test: TestCase): Outcome {
        onStatus(test.title)
        val ready = confirm("A call will stay up. During the call, do this:\n${test.title}\nTap Pass to place the call.")
        if (shouldStop()) return unverified("Stopped before the radio change")
        if (!ready) return fail("The radio change was not started")
        val placed = dial(holdMs = 0, leaveUp = true)
        if (placed.verdict != "UP" && placed.verdict != "PASS") return Outcome(placed.verdict, placed.detail)
        val survived = confirm("Did the call stay up through this change?\n${test.title}")
        if (shouldStop()) {
            if (watch.refresh() != TelephonyManager.CALL_STATE_IDLE) finishCall()
            return unverified("Stopped during the radio change")
        }
        if (watch.refresh() != TelephonyManager.CALL_STATE_IDLE) finishCall()
        val missing = verifyInCallLog(placed.sinceMs)
        if (missing != null) return missing
        if (!survived) return fail("The tester did not confirm the call survived the radio change.")
        return pass("The call stayed up during the radio change. The tester confirmed it. ${placed.detail}")
    }

    private fun cancelDuringSetup(): Outcome {
        val ready = readiness()
        if (ready.verdict != "PASS") return ready
        val number = savedNumber()
        if (number.isBlank()) return blocked("Save a test number before running this case")
        if (!watch.hasCallPermission()) return blocked("Call permission is required to dial the saved number")
        if (!evidence.hasCallLogPermission()) return blocked("Call log permission is required to verify the call")
        val since = System.currentTimeMillis()
        onStatus("Calling the saved number, then cancelling")
        if (!placeCall()) return fail("The call could not be started")
        val offhook = watch.await(TelephonyManager.CALL_STATE_OFFHOOK, 20_000, shouldStop)
        if (shouldStop() && !offhook) return unverified("Stopped before the call was cancelled")
        if (!offhook) return fail("The call did not start, so it could not be cancelled")
        if (!finishCall()) return fail("The call could not be cancelled")
        val hit = waitForCallLog(number, since, 20_000)
        if (hit == null) return fail("The cancelled call is not in the system call log")
        if (hit.durationSec > 5) return fail("The call connected for ${hit.durationSec} seconds. This case cancels during setup.")
        return pass("The call was cancelled during setup. The system call log shows the outgoing attempt.")
    }

    private fun expectNoConnection(): Outcome {
        if (!watch.hasTelephony()) return na("This device has no telephony")
        if (!watch.hasPhonePermission()) return blocked("Phone permission is required")
        val subs = watch.subscriptionCount() ?: return blocked("SIM state could not be read")
        if (subs == 0) return blocked("No SIM is installed. This case needs a SIM, so it is blocked instead of failed.")
        val number = savedNumber()
        if (number.isBlank()) return blocked("Save a test number before running this case")
        if (!watch.hasCallPermission()) return blocked("Call permission is required to dial the saved number")
        if (!evidence.hasCallLogPermission()) return blocked("Call log permission is required to verify the call")
        val since = System.currentTimeMillis()
        onStatus("Calling the saved number. This case expects no connection.")
        if (!placeCall()) return pass("The call could not be started. No connection was established.")
        val offhook = watch.await(TelephonyManager.CALL_STATE_OFFHOOK, 20_000, shouldStop)
        if (shouldStop() && !offhook) return unverified("Stopped while checking that the call did not connect")
        if (offhook) finishCall()
        val hit = waitForCallLog(number, since, 10_000)
        if (hit != null && hit.durationSec > 0) {
            return fail("The call connected for ${hit.durationSec} seconds. This case expected no connection.")
        }
        return pass("No connected call was established.")
    }

    private fun dropDuringCall(): Outcome {
        val placed = dial(holdMs = 0, leaveUp = true)
        if (placed.verdict != "UP" && placed.verdict != "PASS") return Outcome(placed.verdict, placed.detail)
        onStatus("Remove service so the call drops")
        val dropped = confirm("Remove mobile or Wi-Fi service so the call drops, then tap Pass.")
        if (shouldStop()) {
            if (watch.refresh() != TelephonyManager.CALL_STATE_IDLE) finishCall()
            return unverified("Stopped while the call was being dropped")
        }
        if (watch.refresh() != TelephonyManager.CALL_STATE_IDLE) finishCall()
        if (placed.verdict == "UP") {
            val missing = verifyInCallLog(placed.sinceMs)
            if (missing != null) return missing
        }
        if (!dropped) return fail("The tester did not confirm that the call dropped when service was removed.")
        return pass("The call was up, then the tester confirmed it dropped when service was removed.")
    }

    private fun dtmfCall(): Outcome {
        val placed = outgoing()
        if (placed.verdict != "PASS") return placed
        val heard = confirm("Were the keypad tones heard on the other phone?")
        if (shouldStop()) return unverified("Stopped during the tone check")
        if (!heard) return fail("Keypad tones were not confirmed")
        return pass("${placed.detail} The tester confirmed keypad tones.")
    }

    private fun expectNoIncoming(): Outcome {
        val ready = readiness()
        if (ready.verdict != "PASS") return ready
        onStatus("This case expects no incoming call")
        val ringing = watch.await(TelephonyManager.CALL_STATE_RINGING, 45_000, shouldStop)
        if (shouldStop()) return unverified("Stopped while waiting to see that no call arrived")
        if (ringing) return fail("A call arrived. This case expected no incoming call.")
        return pass("No incoming call arrived.")
    }

    private fun incomingLeftUnanswered(): Outcome {
        val ready = readiness()
        if (ready.verdict != "PASS") return ready
        onStatus("From the other phone, call this device. Do not answer.")
        val ringing = watch.await(TelephonyManager.CALL_STATE_RINGING, 90_000, shouldStop)
        if (shouldStop() && !ringing) return unverified("Stopped before ringing")
        if (!ringing) return fail("Ringing was not observed")
        onStatus("Leave the call unanswered until it stops")
        val deadline = SystemClock.elapsedRealtime() + 120_000
        while (SystemClock.elapsedRealtime() < deadline) {
            if (shouldStop()) return unverified("Stopped during the unanswered call")
            val state = watch.refresh()
            if (state == TelephonyManager.CALL_STATE_OFFHOOK) {
                return fail("The call was answered. This case leaves it unanswered.")
            }
            if (state == TelephonyManager.CALL_STATE_IDLE) {
                return pass("The phone rang and the call was not answered.")
            }
            try {
                Thread.sleep(300)
            } catch (_: InterruptedException) {
                return unverified("Stopped during the unanswered call")
            }
        }
        return fail("The phone did not return to idle")
    }

    private fun verifyInCallLog(sinceMs: Long): Outcome? {
        val number = savedNumber()
        if (number.isBlank()) return blocked("Save a test number before running this case")
        val hit = waitForCallLog(number, sinceMs, 20_000)
        if (hit == null) return fail("The system call log has no outgoing call to the saved number.")
        return null
    }

    private fun readiness(): Outcome {
        if (!watch.hasTelephony()) return na("This device has no telephony")
        if (!watch.hasPhonePermission()) return blocked("Phone permission is required")
        val subs = watch.subscriptionCount() ?: return blocked("SIM state could not be read")
        val voice = watch.voiceInService() ?: return blocked("Voice service state could not be read")
        if (subs == 0) return blocked("No SIM is installed. This case needs a SIM, so it is blocked instead of failed.")
        if (!voice) return blocked("Voice service is not in service. This is not a call failure.")
        return pass("Active subscriptions: $subs. Voice service is in service.")
    }

    private fun outgoing(): Outcome {
        val placed = dial(holdMs = 0)
        if (placed.verdict != "PASS") return Outcome(placed.verdict, placed.detail)
        return pass("${placed.detail} Off-hook does not prove the other phone answered.")
    }

    private fun incoming(): Outcome {
        val ready = readiness()
        if (ready.verdict != "PASS") return ready
        onStatus("From the other phone, call this device")
        val ringing = watch.await(TelephonyManager.CALL_STATE_RINGING, 90_000, shouldStop)
        if (shouldStop() && !ringing) return unverified("Stopped before ringing")
        if (!ringing) return fail("Ringing was not observed")
        onStatus("Answer or reject the call. This case continues when the phone is idle.")
        var answered = false
        val deadline = SystemClock.elapsedRealtime() + 120_000
        while (SystemClock.elapsedRealtime() < deadline) {
            if (shouldStop()) return unverified("Stopped during the incoming call")
            val state = watch.refresh()
            if (state == TelephonyManager.CALL_STATE_OFFHOOK) answered = true
            if (state == TelephonyManager.CALL_STATE_IDLE) {
                val how = if (answered) "answered" else "rejected"
                return pass("Ringing observed, then the call was $how, then the phone returned to idle.")
            }
            try {
                Thread.sleep(300)
            } catch (_: InterruptedException) {
                return unverified("Stopped during the incoming call")
            }
        }
        return fail("The phone did not return to idle")
    }

    private fun answered(): Outcome {
        val ready = readiness()
        if (ready.verdict != "PASS") return ready
        onStatus("From the other phone, call this device")
        val ringing = watch.await(TelephonyManager.CALL_STATE_RINGING, 90_000, shouldStop)
        if (!ringing) return if (shouldStop()) unverified("Stopped before ringing") else fail("Ringing was not observed")
        onStatus("Answer the call on this phone")
        val offhook = watch.await(TelephonyManager.CALL_STATE_OFFHOOK, 90_000, shouldStop)
        if (shouldStop() && !offhook) return unverified("Stopped before the call was answered")
        if (!offhook) return fail("The call was not answered")
        onStatus("Answer detected. End the call, then choose Pass or Fail.")
        val idle = watch.await(TelephonyManager.CALL_STATE_IDLE, 180_000, shouldStop)
        if (shouldStop() && !idle) return unverified("Stopped before the call ended")
        if (!idle) return fail("The phone did not return to idle")
        val audio = confirm("Could both sides hear each other?")
        if (shouldStop()) return unverified("Stopped during the audio check")
        if (!audio) return fail("Tester did not confirm two-way audio")
        return pass("Ringing, answer, and idle were observed. The tester confirmed two-way audio.")
    }

    private fun setupTiming(): Outcome {
        val placed = dial(holdMs = 0)
        if (placed.verdict != "PASS") return Outcome(placed.verdict, placed.detail)
        return unverified(
            "${placed.detail} No pass limit is configured, so the timing stays not verified. This is not answer time."
        )
    }

    private fun durationCheck(): Outcome {
        val placed = dial(holdMs = 15_000)
        if (placed.verdict != "PASS") return Outcome(placed.verdict, placed.detail)
        val logged = placed.logDurationSec
        if (logged == null) {
            return unverified("${placed.detail} The system call log has no duration, so connected time was not compared.")
        }
        val detail = "${placed.detail} System call log duration is $logged seconds. That is connected time, not the whole off-hook interval."
        return pass(detail)
    }

    private fun repeatedOutgoing(): Outcome {
        var completed = 0
        repeat(CYCLE_COUNT) { index ->
            if (shouldStop()) return unverified("Stopped after $completed of $CYCLE_COUNT calls")
            onStatus("Call ${index + 1} of $CYCLE_COUNT")
            val cycle = outgoing()
            if (cycle.verdict == "BLOCKED" || cycle.verdict == "NOT_APPLICABLE" || cycle.verdict == "NOT_VERIFIED") {
                return cycle
            }
            if (cycle.verdict != "PASS") return fail("Call ${index + 1} was not verified. ${cycle.detail}")
            completed++
            if (index < CYCLE_COUNT - 1) pause(15_000, "Pausing 15 seconds before the next call")
        }
        return pass("Completed $completed of $CYCLE_COUNT calls. Each one is in the system call log.")
    }

    private fun holdCall(holdMs: Long = HOLD_MS): Outcome {
        val placed = dial(holdMs)
        if (placed.verdict != "PASS") return Outcome(placed.verdict, placed.detail)
        return pass("${placed.detail} Call state does not prove speech quality.")
    }

    /**
     * Dials the saved number, waits through [holdMs], ends the call, then checks
     * the system call log and new system-log lines.
     */
    private fun dial(holdMs: Long, leaveUp: Boolean = false): Placed {
        val ready = readiness()
        if (ready.verdict != "PASS") return Placed(ready.verdict, ready.detail, null)
        if (!watch.hasCallPermission()) {
            return Placed("BLOCKED", "Call permission is required to dial the saved number", null)
        }
        if (!evidence.hasCallLogPermission()) {
            return Placed("BLOCKED", "Call log permission is required to verify the call", null)
        }
        val number = savedNumber()
        if (number.isBlank()) return Placed("BLOCKED", "Save a test number before running this case", null)
        val beforeLog = evidence.logcatSnapshot()
        val since = System.currentTimeMillis()
        val started = SystemClock.elapsedRealtime()
        onStatus("Calling the saved number")
        if (!placeCall()) return Placed("FAIL", "The call could not be started", null)
        val offhook = watch.await(TelephonyManager.CALL_STATE_OFFHOOK, 60_000, shouldStop)
        if (shouldStop() && !offhook) return Placed("NOT_VERIFIED", "Stopped before the call went off-hook", null)
        if (!offhook) return Placed("FAIL", "The call did not go off-hook", null)
        val setupMs = SystemClock.elapsedRealtime() - started
        val wait = stayUntilOtherPhoneRings(beforeLog)
        if (wait.stopped != null) {
            if (watch.refresh() != TelephonyManager.CALL_STATE_IDLE) finishCall()
            return wait.stopped
        }
        if (leaveUp && wait.stillOffHook) {
            return Placed("UP", "The saved number is off-hook.", null, since)
        }
        if (wait.stillOffHook && holdMs > 0) {
            val held = holdOffHook(holdMs)
            if (held != null) {
                if (watch.refresh() != TelephonyManager.CALL_STATE_IDLE) finishCall()
                return held
            }
        }
        if (wait.stillOffHook && !finishCall()) {
            return Placed("FAIL", "The phone did not return to idle", null)
        }
        val hit = waitForCallLog(number, since, 20_000)
        val logcat = evidence.newLogConfirms(beforeLog, evidence.logcatSnapshot(), number)
        if (hit == null && !logcat) {
            val reason = if (offhook) {
                "The phone went off-hook, but the system call log and system log have no outgoing call to the saved number."
            } else {
                "The call was not placed. The system call log and system log have no outgoing call to the saved number."
            }
            return Placed("FAIL", reason, null)
        }
        val source = when {
            hit != null && logcat -> "the system call log and the system log"
            hit != null -> "the system call log"
            else -> "the system log"
        }
        return Placed(
            "PASS",
            "Dialed the saved number. Verified from $source. Off-hook in $setupMs ms.",
            hit?.durationSec,
        )
    }

    /**
     * Keeps the outgoing call up until the other phone has time to ring.
     * A short idle gap while dialing is ignored. Hanging up in that gap is what
     * disconnected the call locally on the Nexus 6P before the other phone rang.
     * If the other phone answers and ends the call, this returns without hanging up.
     */
    private fun stayUntilOtherPhoneRings(beforeLog: String): RingWait {
        val started = SystemClock.elapsedRealtime()
        var alertedAt = 0L
        var offHookMs = 0L
        var idleMs = 0L
        var nextLogCheck = started
        while (true) {
            if (shouldStop()) {
                return RingWait(Placed("NOT_VERIFIED", "Stopped before the other phone could ring", null), false)
            }
            val now = SystemClock.elapsedRealtime()
            val state = watch.refresh()
            if (state == TelephonyManager.CALL_STATE_IDLE) {
                idleMs += 1_000
                val endedByTheOtherSide = offHookMs >= 3_000 && idleMs >= 5_000
                if (endedByTheOtherSide) {
                    onStatus("Call finished. Checking the system call log.")
                    return RingWait(null, false)
                }
            } else {
                offHookMs += 1_000
                idleMs = 0
            }
            if (alertedAt == 0L && now >= nextLogCheck) {
                nextLogCheck = now + 2_000
                if (evidence.sawNewAlerting(beforeLog)) alertedAt = now
            }
            val rangLongEnough = alertedAt > 0L && now - alertedAt >= RING_AFTER_ALERT_MS && offHookMs >= 3_000
            val gaveTheNetworkTime = offHookMs >= MIN_RING_MS
            if (rangLongEnough || gaveTheNetworkTime) {
                return RingWait(null, watch.refresh() != TelephonyManager.CALL_STATE_IDLE)
            }
            val left = if (alertedAt > 0L) {
                ((RING_AFTER_ALERT_MS - (now - alertedAt)) / 1000).coerceAtLeast(0)
            } else {
                ((MIN_RING_MS - offHookMs) / 1000).coerceAtLeast(0)
            }
            onStatus(
                if (alertedAt > 0L) "Other phone is ringing, $left seconds"
                else "Waiting for the other phone to ring, $left seconds"
            )
            try {
                Thread.sleep(1000)
            } catch (_: InterruptedException) {
                return RingWait(Placed("NOT_VERIFIED", "Stopped before the other phone could ring", null), false)
            }
        }
    }

    private fun holdOffHook(holdMs: Long): Placed? {
        val holdUntil = SystemClock.elapsedRealtime() + holdMs
        var idleSamples = 0
        while (SystemClock.elapsedRealtime() < holdUntil) {
            if (shouldStop()) return Placed("NOT_VERIFIED", "Stopped during the call", null)
            if (watch.refresh() == TelephonyManager.CALL_STATE_IDLE) {
                idleSamples++
                if (idleSamples >= 2) return Placed("FAIL", "Call state changed during the call", null)
            } else {
                idleSamples = 0
            }
            val left = ((holdUntil - SystemClock.elapsedRealtime()) / 1000).coerceAtLeast(0)
            onStatus("On the call, $left seconds left")
            try {
                Thread.sleep(1000)
            } catch (_: InterruptedException) {
                return Placed("NOT_VERIFIED", "Stopped during the call", null)
            }
        }
        return null
    }

    private fun finishCall(): Boolean {
        if (watch.refresh() == TelephonyManager.CALL_STATE_IDLE) return true
        onStatus("Ending the call")
        val ended = endCall()
        if (!ended) {
            val manual = confirm("The app could not end the call. End it, then tap Pass.")
            if (!manual) return false
        }
        return watch.await(TelephonyManager.CALL_STATE_IDLE, 60_000, shouldStop)
    }

    private fun waitForCallLog(number: String, sinceMs: Long, timeoutMs: Long): CallEvidence.Hit? {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            if (shouldStop()) return evidence.outgoingSince(number, sinceMs)
            evidence.outgoingSince(number, sinceMs)?.let { return it }
            try {
                Thread.sleep(500)
            } catch (_: InterruptedException) {
                return evidence.outgoingSince(number, sinceMs)
            }
        }
        return evidence.outgoingSince(number, sinceMs)
    }

    private fun permissionDenial(): Outcome {
        val handled = watch.exerciseDeniedPath()
        if (!handled) return fail("The denied-permission path crashed or still read call state.")
        val missing = watch.missingPermissions()
        val permissionNote = if (missing.isEmpty()) {
            "The system permission was left granted."
        } else {
            "Missing ${missing.joinToString(", ")} permission."
        }
        return pass("Denied phone access was handled without crashing or placing a call. $permissionNote No SIM is required.")
    }

    private fun dataMinimization(): Outcome {
        val detail = "The system call log is read only to verify placement. This result does not include the saved number."
        if (Regex("\\+?\\d{7,}").containsMatchIn(detail)) return fail("Result text contains a phone number")
        return pass(detail)
    }

    private fun pause(ms: Long, status: String) {
        val until = SystemClock.elapsedRealtime() + ms
        while (SystemClock.elapsedRealtime() < until) {
            if (shouldStop()) return
            onStatus(status)
            try {
                Thread.sleep(1000)
            } catch (_: InterruptedException) {
                return
            }
        }
    }

    private fun pass(detail: String) = Outcome("PASS", detail)
    private fun fail(detail: String) = Outcome("FAIL", detail)
    private fun blocked(detail: String) = Outcome("BLOCKED", detail)
    private fun na(detail: String) = Outcome("NOT_APPLICABLE", detail)
    private fun unverified(detail: String) = Outcome("NOT_VERIFIED", detail)

    private data class Outcome(val verdict: String, val detail: String)

    private data class Placed(
        val verdict: String,
        val detail: String,
        val logDurationSec: Int?,
        val sinceMs: Long = 0L,
    )

    private data class RingWait(val stopped: Placed?, val stillOffHook: Boolean)

    companion object {
        const val CYCLE_COUNT = 3
        const val HOLD_MS = 300_000L
        const val MIN_RING_MS = 35_000L
        const val RING_AFTER_ALERT_MS = 15_000L
        const val LONG_HOLD_MS = 1_800_000L
        val CANCEL_IDS = setOf("eTinT_MO_18", "eTinT_MO_24", "Test Case Voice 08")
        val MUST_NOT_CONNECT = setOf("eTinT_MO_13", "eTinT_MO_23", "SS_NEW_11", "SS_NEW_13", "SS_NEW_14")
        val DROP_DURING = setOf("eTinT_MO_15", "eTinT_MO_16")
        val MUST_NOT_ARRIVE = setOf("eTinT_MT_18", "SS_NEW_10", "SS_NEW_12")
        val NOT_ANSWERED = setOf("eTinT_MT_12", "eTinT_MT_13")
        val BEHAVIOR_CHECK = setOf(
            "eTinT_MO_14", "eTinT_MO_17", "eTinT_MO_19",
            "SS_NEW_01", "SS_NEW_02", "SS_NEW_03", "SS_NEW_04", "SS_NEW_05", "SS_NEW_06",
            "SS_NEW_07", "SS_NEW_08", "SS_NEW_09", "SS_NEW_15", "SS_NEW_16", "SS_NEW_17",
            "SS_NEW_18", "SS_NEW_19", "SS_NEW_20", "SS_NEW_21", "SS_NEW_25", "SS_NEW_30",
            "MC 04", "MC 06",
        )
        val SETUP_HINTS = listOf(
            "poor", "airplane", "oos", "no service", "roaming", "hotspot", "captive",
            "mobile network data", "csfb", "wcdma", "flight", "both cellular", "non-3uk",
            "voicemail", "long idle",
        )
    }
}
