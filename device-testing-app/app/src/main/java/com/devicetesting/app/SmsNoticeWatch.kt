package com.devicetesting.app

import android.app.Notification
import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.provider.Telephony
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification

/**
 * Sees an incoming text when Messages shows it as a chat notification.
 * Those texts are not written to the SMS list, so the inbox query cannot see them.
 * Only the sender and the arrival time are used. The message text is not recorded.
 */
class SmsNoticeWatch : NotificationListenerService() {
    override fun onListenerConnected() {
        instance = this
    }

    override fun onListenerDisconnected() {
        if (instance === this) instance = null
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        super.onDestroy()
    }

    companion object {
        private val MESSAGE_APPS = setOf(
            "com.google.android.apps.messaging",
            "com.android.mms",
        )

        @Volatile
        private var instance: SmsNoticeWatch? = null
        private var rebindAsked = false

        fun enabled(context: Context): Boolean {
            val listed = Settings.Secure.getString(
                context.contentResolver,
                "enabled_notification_listeners",
            ).orEmpty()
            val name = ComponentName(context, SmsNoticeWatch::class.java)
            return listed.split(":").any {
                it.equals(name.flattenToString(), ignoreCase = true) ||
                    it.equals(name.flattenToShortString(), ignoreCase = true)
            }
        }

        fun baseline(context: Context): Map<String, Long> {
            val notices = currentNotices(context) ?: return emptyMap()
            return notices.filter { it.packageName in messageApps(context) }
                .associate { it.key to latestTime(it) }
        }

        fun matches(context: Context, number: String, sinceMs: Long, seen: Map<String, Long>): Boolean {
            val notices = currentNotices(context) ?: return false
            val apps = messageApps(context)
            return notices.any { notice ->
                if (notice.packageName !in apps) return@any false
                if (partyLines(notice).none { SmsEvidence.sameParty(number, it) }) return@any false
                val time = latestTime(notice)
                val previous = seen[notice.key]
                val arrivedAfterStart = time >= sinceMs - 2_000
                arrivedAfterStart && (previous == null || time > previous)
            }
        }

        private fun messageApps(context: Context): Set<String> {
            val apps = HashSet(MESSAGE_APPS)
            Telephony.Sms.getDefaultSmsPackage(context)?.let { apps += it }
            return apps
        }

        private fun currentNotices(context: Context): Array<StatusBarNotification>? {
            if (instance == null && enabled(context) && !rebindAsked && Build.VERSION.SDK_INT >= 24) {
                rebindAsked = true
                requestRebind(ComponentName(context, SmsNoticeWatch::class.java))
            }
            val service = instance ?: return null
            return try {
                service.activeNotifications
            } catch (_: Exception) {
                null
            }
        }

        private fun latestTime(notice: StatusBarNotification): Long {
            val messages = notice.notification.extras.getParcelableArray(Notification.EXTRA_MESSAGES)
            var latest = 0L
            messages?.forEach { item ->
                val time = (item as? Bundle)?.getLong("time") ?: 0L
                if (time > latest) latest = time
            }
            if (latest > 0L) return latest
            return notice.postTime
        }

        private fun partyLines(notice: StatusBarNotification): List<String> {
            val extras = notice.notification.extras
            val lines = ArrayList<String>()
            extras.getCharSequence(Notification.EXTRA_TITLE)?.let { lines += it.toString() }
            notice.notification.tickerText?.let { lines += it.toString() }
            extras.getStringArray(Notification.EXTRA_PEOPLE)?.let { lines += it }
            return lines
        }
    }
}
