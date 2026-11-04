package com.devicetesting.app

import android.app.Activity
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.telephony.SmsManager
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * Sends one text MMS through the SIM message center. A null service-center address is not set;
 * the platform uses the carrier center. Returns true when the phone accepts the message.
 */
object MmsSender {
    fun send(context: Context, number: String, text: String): Boolean {
        val app = context.applicationContext
        val pdu = textPdu(number, text)
        MmsPduProvider.bytes = pdu
        val uri = MmsPduProvider.uri()
        val action = "${app.packageName}.MMS_SENT"
        val flags = if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_IMMUTABLE else 0
        val sent = PendingIntent.getBroadcast(app, 1, Intent(action), flags)
        val code = AtomicInteger(Int.MIN_VALUE)
        val latch = CountDownLatch(1)
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context, intent: Intent) {
                code.set(resultCode)
                latch.countDown()
            }
        }
        app.registerReceiver(receiver, IntentFilter(action))
        return try {
            @Suppress("DEPRECATION")
            SmsManager.getDefault().sendMultimediaMessage(app, uri, null, null, sent)
            latch.await(30, TimeUnit.SECONDS) && code.get() == Activity.RESULT_OK
        } catch (_: Exception) {
            false
        } finally {
            try {
                app.unregisterReceiver(receiver)
            } catch (_: Exception) {
            }
        }
    }

    private fun textPdu(number: String, text: String): ByteArray {
        val body = text.toByteArray(Charsets.UTF_8)
        val partHeaders = byteArrayOf(0x83.toByte())
        val part = ByteArrayOutputStream()
        part.write(uintvar(partHeaders.size))
        part.write(uintvar(body.size))
        part.write(partHeaders)
        part.write(body)
        val out = ByteArrayOutputStream()
        out.write(0x8C); out.write(0x80)
        val tid = "T${(System.currentTimeMillis() % 100000).toInt()}"
        out.write(0x98); out.write(tid.toByteArray()); out.write(0)
        out.write(0x8D); out.write(0x90)
        out.write(0x89); out.write(0x01); out.write(0x81)
        val address = "$number/TYPE=PLMN".toByteArray()
        out.write(0x97); out.write(address.size + 1); out.write(address); out.write(0)
        out.write(0x84); out.write(0xA3)
        out.write(uintvar(1))
        out.write(part.toByteArray())
        return out.toByteArray()
    }

    private fun uintvar(value: Int): ByteArray {
        if (value <= 0) return byteArrayOf(0)
        val groups = ArrayList<Int>()
        var rest = value
        while (rest > 0) {
            groups.add(rest and 0x7F)
            rest = rest shr 7
        }
        return ByteArray(groups.size) { index ->
            val piece = groups[groups.size - 1 - index]
            (if (index < groups.size - 1) piece or 0x80 else piece).toByte()
        }
    }
}
