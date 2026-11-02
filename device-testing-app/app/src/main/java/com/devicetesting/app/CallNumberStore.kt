package com.devicetesting.app

import android.content.Context
import android.os.Build
import android.telephony.TelephonyManager

/**
 * The number the calls suite dials. Stored on this device only.
 * Emergency numbers and USSD codes are rejected.
 */
object CallNumberStore {
    private const val PREFS = "calls"
    private const val KEY = "default_number"

    fun get(context: Context): String =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, "").orEmpty()

    /** Saves a cleaned number. Returns an error message, or null when saved. */
    fun save(context: Context, raw: String): String? {
        val cleaned = normalize(raw)
        val error = reject(context, cleaned)
        if (error != null) return error
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY, cleaned).apply()
        return null
    }

    fun reject(context: Context, number: String): String? {
        val trimmed = number.trim()
        if (trimmed.isEmpty()) return "Enter a test number"
        if (trimmed.any { it == '#' || it == '*' }) return "USSD and special codes are not dialed"
        val digits = trimmed.filter { it.isDigit() }
        if (digits.length < 3 || digits.length > 15) return "Enter a phone number of 3 to 15 digits"
        if (trimmed.count { it == '+' } > 1 || (trimmed.contains('+') && !trimmed.startsWith('+'))) {
            return "Enter a phone number"
        }
        if (isEmergency(context, trimmed)) return "Emergency numbers are not dialed"
        return null
    }

    fun normalize(raw: String): String {
        val trimmed = raw.trim()
        val digits = trimmed.filter { it.isDigit() }
        return if (trimmed.startsWith("+")) "+$digits" else digits
    }

    private fun isEmergency(context: Context, number: String): Boolean {
        val digits = number.filter { it.isDigit() }
        if (digits in SHORT_EMERGENCY) return true
        if (Build.VERSION.SDK_INT < 29) return false
        return try {
            val telephony = context.getSystemService(Context.TELEPHONY_SERVICE) as TelephonyManager
            telephony.isEmergencyNumber(number) || telephony.isEmergencyNumber(digits)
        } catch (_: Exception) {
            false
        }
    }

    private val SHORT_EMERGENCY = setOf(
        "000", "110", "112", "119", "911", "999",
        "100", "101", "102", "108",
        "190", "191", "192", "193",
    )
}
