package com.devicetesting.app

import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.os.SystemClock
import android.telecom.TelecomManager
import android.telephony.PhoneStateListener
import android.telephony.ServiceState
import android.telephony.SubscriptionManager
import android.telephony.TelephonyManager
import androidx.core.content.ContextCompat

/**
 * Reads SIM, voice service, and call state. Phone numbers from the listener are ignored.
 */
class CallWatch(context: Context) {
    private val app = context.applicationContext
    private val telephony = app.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager

    @Volatile
    var state: Int = TelephonyManager.CALL_STATE_IDLE
        private set

    private var idlePolls = 0

    private var listening = false

    @Suppress("DEPRECATION")
    private val listener = object : PhoneStateListener() {
        override fun onCallStateChanged(state: Int, phoneNumber: String?) {
            this@CallWatch.state = state
            if (state != TelephonyManager.CALL_STATE_IDLE) idlePolls = 0
        }
    }

    fun hasTelephony(): Boolean =
        app.packageManager.hasSystemFeature(PackageManager.FEATURE_TELEPHONY)

    fun hasPhonePermission(): Boolean = granted(android.Manifest.permission.READ_PHONE_STATE)

    fun hasCallPermission(): Boolean = granted(android.Manifest.permission.CALL_PHONE)

    fun missingPermissions(): List<String> {
        val names = mutableListOf(
            android.Manifest.permission.READ_PHONE_STATE to "phone",
            android.Manifest.permission.CALL_PHONE to "call",
            android.Manifest.permission.READ_CALL_LOG to "call log",
        )
        if (android.os.Build.VERSION.SDK_INT >= 26) {
            names += android.Manifest.permission.ANSWER_PHONE_CALLS to "answer"
        }
        return names.filter { !granted(it.first) }.map { it.second }
    }

    private fun granted(permission: String): Boolean =
        ContextCompat.checkSelfPermission(app, permission) == PackageManager.PERMISSION_GRANTED

    /**
     * The in-app path for a denied phone permission. It does not read call state,
     * dial, or change the system permission.
     */
    fun exerciseDeniedPath(): Boolean {
        return try {
            readCallState(permitted = false) == null
        } catch (_: Exception) {
            false
        }
    }

    private fun readCallState(permitted: Boolean): Int? {
        if (!permitted || !hasPhonePermission()) return null
        return refresh()
    }

    fun subscriptionCount(): Int? {
        if (!hasPhonePermission()) return null
        return try {
            val manager = app.getSystemService(SubscriptionManager::class.java) ?: return 0
            @Suppress("DEPRECATION")
            manager.activeSubscriptionInfoList?.size ?: 0
        } catch (_: SecurityException) {
            null
        }
    }

    /** True when voice is in service. Null when the state cannot be read. */
    fun voiceInService(): Boolean? {
        if (!hasPhonePermission()) return null
        return try {
            if (android.os.Build.VERSION.SDK_INT >= 26) {
                val service = telephony.serviceState ?: return false
                service.state == ServiceState.STATE_IN_SERVICE
            } else {
                @Suppress("DEPRECATION")
                telephony.simState == TelephonyManager.SIM_STATE_READY &&
                    !telephony.networkOperator.isNullOrBlank()
            }
        } catch (_: SecurityException) {
            null
        }
    }

    @SuppressLint("MissingPermission")
    fun start(): Boolean {
        if (!hasPhonePermission()) return false
        if (listening) return true
        return try {
            @Suppress("DEPRECATION")
            state = telephony.callState
            @Suppress("DEPRECATION")
            telephony.listen(listener, PhoneStateListener.LISTEN_CALL_STATE)
            listening = true
            true
        } catch (_: SecurityException) {
            false
        }
    }

    fun stop() {
        if (!listening) return
        try {
            @Suppress("DEPRECATION")
            telephony.listen(listener, PhoneStateListener.LISTEN_NONE)
        } catch (_: Exception) {
        }
        listening = false
    }

    /** Ends the call this app placed. False when the platform does not allow it. */
    @SuppressLint("MissingPermission")
    fun endCall(): Boolean {
        if (refresh() == TelephonyManager.CALL_STATE_IDLE) return true
        if (android.os.Build.VERSION.SDK_INT >= 28) {
            val ended = try {
                val telecom = app.getSystemService(TelecomManager::class.java)
                telecom?.endCall() == true
            } catch (_: Exception) {
                false
            }
            if (ended) return true
        }
        return endCallLegacy()
    }

    @SuppressLint("PrivateApi", "DiscouragedPrivateApi")
    private fun endCallLegacy(): Boolean {
        return try {
            val method = TelephonyManager::class.java.getDeclaredMethod("getITelephony")
            method.isAccessible = true
            val binder = method.invoke(telephony) ?: return false
            val end = binder.javaClass.getDeclaredMethod("endCall")
            end.invoke(binder) as? Boolean ?: false
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Reads call state from the telephony service as well as the listener.
     * One idle reading is ignored so a dialing call is not cut off. Several
     * idle readings in a row are trusted, so an ended call does not leave the
     * suite waiting until Stop.
     */
    @SuppressLint("MissingPermission")
    fun refresh(): Int {
        if (!hasPhonePermission()) return state
        return try {
            @Suppress("DEPRECATION")
            val polled = telephony.callState
            if (polled == TelephonyManager.CALL_STATE_IDLE) {
                idlePolls++
                if (idlePolls >= 3) state = TelephonyManager.CALL_STATE_IDLE
            } else {
                idlePolls = 0
                state = polled
            }
            state
        } catch (_: SecurityException) {
            state
        }
    }

    fun await(target: Int, timeoutMs: Long, shouldStop: () -> Boolean): Boolean {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            val current = refresh()
            if (shouldStop()) return current == target
            if (current == target) return true
            try {
                Thread.sleep(200)
            } catch (_: InterruptedException) {
                return refresh() == target
            }
        }
        return refresh() == target
    }
}
