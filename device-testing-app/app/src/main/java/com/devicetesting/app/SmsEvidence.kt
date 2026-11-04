package com.devicetesting.app

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.provider.Telephony
import androidx.core.content.ContextCompat

/**
 * Reads the phone SMS and MMS stores. Result text built by the runner does not include the number.
 */
class SmsEvidence(context: Context) {
    private val app = context.applicationContext

    fun canRead(): Boolean =
        ContextCompat.checkSelfPermission(app, Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED

    fun sentWithToken(token: String, sinceMs: Long): Boolean =
        scan(Telephony.Sms.CONTENT_URI, sinceMs) { body, _, type ->
            type == Telephony.Sms.MESSAGE_TYPE_SENT && body.contains(token)
        }

    fun inboxFrom(number: String, sinceMs: Long): Boolean {
        return try {
            app.contentResolver.query(
                Telephony.Sms.Inbox.CONTENT_URI,
                arrayOf("address", "date"),
                null,
                null,
                "date DESC",
            )?.use { cursor ->
                val addressCol = cursor.getColumnIndex("address")
                val dateCol = cursor.getColumnIndex("date")
                var seen = 0
                while (cursor.moveToNext() && seen < 40) {
                    seen++
                    val raw = if (dateCol >= 0) cursor.getLong(dateCol) else 0L
                    val dateMs = if (raw in 1 until 10_000_000_000L) raw * 1000 else raw
                    if (dateMs < sinceMs - 2_000) break
                    val address = if (addressCol >= 0) cursor.getString(addressCol).orEmpty() else ""
                    if (sameParty(number, address)) return true
                }
                false
            } ?: false
        } catch (_: SecurityException) {
            false
        }
    }

    fun mmsBox(incoming: Boolean, sinceMs: Long): Boolean {
        val box = if (incoming) 1 else 2
        return try {
            app.contentResolver.query(
                Telephony.Mms.CONTENT_URI,
                arrayOf("date", "msg_box"),
                null,
                null,
                "date DESC",
            )?.use { cursor ->
                val dateCol = cursor.getColumnIndex("date")
                val boxCol = cursor.getColumnIndex("msg_box")
                while (cursor.moveToNext()) {
                    val raw = if (dateCol >= 0) cursor.getLong(dateCol) else 0L
                    val dateMs = if (raw < 10_000_000_000L) raw * 1000 else raw
                    val msgBox = if (boxCol >= 0) cursor.getInt(boxCol) else -1
                    if (dateMs >= sinceMs - 5_000 && msgBox == box) return true
                }
                false
            } ?: false
        } catch (_: SecurityException) {
            false
        }
    }

    private fun scan(
        uri: android.net.Uri,
        sinceMs: Long,
        match: (body: String, address: String, type: Int) -> Boolean,
    ): Boolean {
        return try {
            app.contentResolver.query(
                uri,
                arrayOf("body", "address", "date", "type"),
                "date>=?",
                arrayOf((sinceMs - 5_000).toString()),
                "date DESC",
            )?.use { cursor ->
                val bodyCol = cursor.getColumnIndex("body")
                val addressCol = cursor.getColumnIndex("address")
                val typeCol = cursor.getColumnIndex("type")
                while (cursor.moveToNext()) {
                    val body = if (bodyCol >= 0) cursor.getString(bodyCol).orEmpty() else ""
                    val address = if (addressCol >= 0) cursor.getString(addressCol).orEmpty() else ""
                    val type = if (typeCol >= 0) cursor.getInt(typeCol) else -1
                    if (match(body, address, type)) return true
                }
                false
            } ?: false
        } catch (_: SecurityException) {
            false
        }
    }

    companion object {
        fun sameParty(saved: String, shown: String): Boolean {
            val left = national(saved.filter { it.isDigit() })
            val right = national(shown.filter { it.isDigit() })
            if (left.length < 7 || right.length < 7) return false
            return left == right || left.takeLast(8) == right.takeLast(8)
        }

        private fun national(digits: String): String {
            var value = digits
            if (value.startsWith("00")) value = value.drop(2)
            if (value.startsWith("44") && value.length > 10) value = value.drop(2)
            if (value.startsWith("91") && value.length > 10) value = value.drop(2)
            if (value.startsWith("0")) value = value.drop(1)
            return value
        }
    }
}
