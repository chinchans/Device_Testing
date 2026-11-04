package com.devicetesting.app

import android.Manifest
import android.app.Activity
import android.app.DownloadManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.media.MediaScannerConnection
import android.net.ConnectivityManager
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.os.SystemClock
import android.provider.Settings
import android.telephony.SmsManager
import android.telephony.TelephonyManager
import java.io.File
import androidx.core.content.ContextCompat
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * Runs the Airtel SMS catalog. Outgoing messages go to the saved number through the SIM
 * message center. The number is not written into the result.
 */
class SmsRunner(
    private val context: Context,
    private val evidence: SmsEvidence,
    private val watch: CallWatch,
    private val placeCall: () -> Boolean,
    private val endCall: () -> Boolean,
    private val savedNumber: () -> String,
    private val shouldStop: () -> Boolean,
    private val onStatus: (String) -> Unit,
    private val wifi: WifiConnector,
) {
    fun run(test: TestCase): CaseResult {
        val outcome = try {
            dispatch(test)
        } catch (_: SecurityException) {
            Outcome("BLOCKED", "SMS permission is required")
        } catch (e: Exception) {
            Outcome("FAIL", e.message ?: e.javaClass.simpleName)
        }
        return CaseResult(test.id, test.title, test.suite, outcome.verdict, outcome.detail)
    }

    private fun dispatch(test: TestCase): Outcome {
        if (test.id in THRESHOLD) {
            return blocked("This case needs mobile signal below the MMS threshold. The app cannot set that, so it is blocked instead of failed.")
        }
        if (test.action == "check_sms_setting") {
            return unverified("The operator SMS setting is not exposed to this app, so it stays not verified.")
        }
        if (test.action == "send_sms_to_saved_numbers") {
            return blocked("This case needs several saved test numbers. Only one number can be saved.")
        }
        val ready = prepare(test) ?: return runAction(test)
        return ready
    }

    private fun prepare(test: TestCase): Outcome? {
        if (!watch.hasTelephony()) return na("This device has no telephony")
        if (!watch.hasPhonePermission()) return blocked("Phone permission is required")
        val subs = watch.subscriptionCount() ?: return blocked("SIM state could not be read")
        if (subs == 0) return blocked("No SIM is installed. This case needs a SIM, so it is blocked instead of failed.")
        if (!canSend()) return blocked("SMS permission is required")
        if (!evidence.canRead()) return blocked("SMS read permission is required to verify the message")
        radioGate(test)?.let { return it }
        conditionGate(test)?.let { return it }
        if (test.action != "check_sms_setting" && savedNumber().isBlank()) {
            return blocked("Save a test number before running this case")
        }
        val rejected = CallNumberStore.reject(context, savedNumber())
        if (rejected != null && test.action != "check_sms_setting") return blocked(rejected)
        return null
    }

    private fun runAction(test: TestCase): Outcome {
        val duringCall = "during_call" in test.action
        val duringData = "during_data" in test.action
        val download = if (duringData) openDownload() else null
        if (duringData && download == null) {
            if (shouldStop()) return unverified("Stopped during the download")
            return blocked("The download did not start, so the message was not sent.")
        }
        if (duringCall) {
            val call = startCall()
            if (call != null) {
                download?.finish()
                return call
            }
        }
        val before = download?.savedBytes() ?: 0L
        val outcome = try {
            when {
                test.action.startsWith("wait_for_mms") -> waitForMms(test)
                test.action.startsWith("wait_for_long") -> waitForSms(duringData)
                test.action.startsWith("wait_for") -> waitForSms(duringData)
                test.action.startsWith("send_mms") -> sendMms(test)
                test.action.startsWith("send_long") -> sendSms(long = true, duringDownload = duringData)
                else -> sendSms(long = false, duringDownload = duringData)
            }
        } finally {
            if (duringCall) endCall()
            download?.finish()
        }
        return finish(test, withConditions(test, outcome, duringCall, download, before))
    }

    private fun withConditions(
        test: TestCase,
        outcome: Outcome,
        duringCall: Boolean,
        download: PhoneDownload?,
        beforeBytes: Long,
    ): Outcome {
        if (outcome.verdict != "PASS") return outcome
        if (download != null) {
            val file = download.savedFile()
            if (file == null || file.length() <= 0L) {
                return fail("No file was saved in Downloads, so this is not a pass.")
            }
            if (download.savedBytes() <= beforeBytes) {
                return fail("The download was not still saving while the message was checked.")
            }
        }
        val notes = ArrayList<String>()
        if (test.radio == "VoWiFi" && wifiConnected()) notes += "Wi-Fi was connected."
        if (duringCall) notes += "The call was off-hook."
        val file = download?.savedFile()
        if (file != null) notes += "Saved ${file.name} in Downloads."
        if (notes.isEmpty()) return outcome
        return pass("${outcome.detail} ${notes.joinToString(" ")}")
    }

    private fun finish(test: TestCase, outcome: Outcome): Outcome {
        if (outcome.verdict == "PASS" && test.id in PATH_ONLY) {
            return unverified("${outcome.detail} The SGs or circuit path was not read, so that check stays not verified.")
        }
        return outcome
    }

    private fun sendSms(long: Boolean, duringDownload: Boolean = false): Outcome {
        val number = savedNumber()
        val token = token()
        val body = if (long) {
            "Device test $token. " + "Long message check. ".repeat(40)
        } else {
            "Device test $token"
        }
        val since = System.currentTimeMillis()
        onStatus(
            when {
                duringDownload && long -> "Sending a long test message during the download"
                duringDownload -> "Sending the test message during the download"
                long -> "Sending a long test message"
                else -> "Sending the test message"
            }
        )
        val sent = if (long) sendLong(number, body) else sendText(number, body)
        if (shouldStop()) return unverified("Stopped while sending")
        if (!sent) return fail("The message was not accepted by the phone")
        val seen = waitUntil(20_000) { evidence.sentWithToken(token, since) }
        if (shouldStop()) return unverified("Stopped before the SMS database was checked")
        if (!seen) return fail("The system SMS list has no sent test message")
        val kind = if (long) "long test message" else "test message"
        return pass("The $kind is in the sent messages. The SIM message center was used.")
    }

    private fun waitForSms(duringDownload: Boolean = false): Outcome {
        val number = savedNumber()
        val since = System.currentTimeMillis()
        val alreadyThere = SmsNoticeWatch.baseline(context)
        val prompt = if (duringDownload) {
            "A download is running. Text this phone now"
        } else {
            "Text this phone now"
        }
        onStatus(prompt)
        val timeout = if (SmsNoticeWatch.enabled(context)) 90_000L else 180_000L
        var lastPrompt = SystemClock.elapsedRealtime()
        val seen = waitUntil(timeout) {
            val now = SystemClock.elapsedRealtime()
            if (now - lastPrompt >= 5_000) {
                lastPrompt = now
                onStatus(prompt)
            }
            if (evidence.inboxFrom(number, since) || SmsNoticeWatch.matches(context, number, since, alreadyThere)) {
                true
            } else {
                if (!noticeAsked && !SmsNoticeWatch.enabled(context)) {
                    noticeAsked = true
                    onStatus("Allow notification access for this app, then come back and send the text")
                    requestNoticeAccess()
                }
                false
            }
        }
        if (shouldStop() && !seen) return unverified("Stopped before a text arrived")
        if (seen) return pass("A text from the saved number was received.")
        if (!SmsNoticeWatch.enabled(context)) {
            return blocked("The text is shown by Messages and is not in the SMS list. Allow notification access for this app, then run this case again.")
        }
        return fail("No text from the saved number arrived")
    }

    private fun requestNoticeAccess() {
        val launch = {
            try {
                context.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
            } catch (_: Exception) {
            }
        }
        val activity = context as? Activity
        if (activity != null) activity.runOnUiThread { launch() } else launch()
    }

    private fun sendMms(test: TestCase): Outcome {
        val number = savedNumber()
        val since = System.currentTimeMillis()
        onStatus("Sending a picture message")
        val sent = MmsSender.send(context, number, "Device test ${token()}")
        if (shouldStop()) return unverified("Stopped while sending the picture message")
        if (test.id in MUST_NOT_SEND_MMS) {
            return if (sent) {
                fail("The picture message was sent. This case expected it not to send.")
            } else {
                pass("The picture message was not sent.")
            }
        }
        if (!sent) return fail("The picture message was not accepted by the phone")
        val seen = waitUntil(20_000) { evidence.mmsBox(incoming = false, since) }
        if (!seen) return unverified("The phone accepted the picture message, but it is not in the MMS list yet.")
        return pass("The picture message is in the sent messages.")
    }

    private fun waitForMms(test: TestCase): Outcome {
        if (test.id in MUST_NOT_SEND_MMS) {
            val since = System.currentTimeMillis()
            onStatus("Waiting to see that no picture message arrives")
            val seen = waitUntil(30_000) { evidence.mmsBox(incoming = true, since) }
            if (shouldStop()) return unverified("Stopped while waiting for a picture message")
            return if (seen) {
                fail("A picture message arrived. This case expected none.")
            } else {
                pass("No picture message arrived.")
            }
        }
        val since = System.currentTimeMillis()
        onStatus("From the other phone, send a picture message to this device")
        val seen = waitUntil(90_000) { evidence.mmsBox(incoming = true, since) }
        if (shouldStop() && !seen) return unverified("Stopped before a picture message arrived")
        if (!seen) return fail("No picture message arrived")
        return pass("A picture message is in the inbox.")
    }

    private fun startCall(): Outcome? {
        if (!watch.hasCallPermission()) return blocked("Call permission is required for this case")
        onStatus("Calling the saved number")
        if (!placeCall()) return fail("The call could not be started")
        val offhook = watch.await(TelephonyManager.CALL_STATE_OFFHOOK, 60_000, shouldStop)
        if (shouldStop() && !offhook) return unverified("Stopped before the call went off-hook")
        if (!offhook) return fail("The call did not go off-hook")
        return null
    }

    private fun openDownload(): PhoneDownload? {
        onStatus("Starting a download")
        val session = PhoneDownload(context, shouldStop, onStatus)
        if (session.open()) return session
        session.finish()
        return null
    }

    private fun radioGate(test: TestCase): Outcome? {
        val now = settledRadio()
        return when (test.radio) {
            "2G" -> if (now == "2G") null else blocked(radioSkipDetail(now))
            "3G" -> if (now == "3G") null else blocked(radioSkipDetail(now))
            "LTE" -> if (now == "LTE" || now == "VoWiFi") null else blocked("The phone is not on LTE. This is not a message failure.")
            "VoLTE" -> if (now == "LTE" || now == "VoWiFi") null else blocked("The phone is not on LTE for a VoLTE message. This is not a message failure.")
            "VoWiFi" -> ensureWifi()
            else -> null
        }
    }

    private fun radioSkipDetail(now: String): String {
        val where = when (now) {
            "LTE", "VoWiFi" -> "LTE"
            "2G" -> "2G"
            "3G" -> "3G"
            else -> "an unknown network"
        }
        return "This phone is on $where. 2G and 3G cases were not run."
    }

    private fun conditionGate(test: TestCase): Outcome? {
        if (test.id in AIRPLANE) return ensureAirplane()
        if (test.id in DATA_OFF) return ensureDataOff()
        if (test.id in MUST_NOT_SEND_MMS && mobileDataEnabled()) {
            return blocked("Mobile data is still switched on, so this picture message was not attempted.")
        }
        return null
    }

    private fun settledRadio(): String {
        var now = radioNow()
        if (now != "other") return now
        onStatus("Checking the mobile network")
        val deadline = SystemClock.elapsedRealtime() + 8_000
        while (SystemClock.elapsedRealtime() < deadline) {
            if (shouldStop()) return now
            sleep(500)
            now = radioNow()
            if (now != "other") return now
        }
        return now
    }

    @Suppress("DEPRECATION")
    private fun radioNow(): String {
        val type = try {
            context.getSystemService(TelephonyManager::class.java).voiceNetworkType
        } catch (_: SecurityException) {
            TelephonyManager.NETWORK_TYPE_UNKNOWN
        }
        return when (type) {
            TelephonyManager.NETWORK_TYPE_GSM,
            TelephonyManager.NETWORK_TYPE_GPRS,
            TelephonyManager.NETWORK_TYPE_EDGE -> "2G"
            TelephonyManager.NETWORK_TYPE_UMTS,
            TelephonyManager.NETWORK_TYPE_HSDPA,
            TelephonyManager.NETWORK_TYPE_HSUPA,
            TelephonyManager.NETWORK_TYPE_HSPA,
            TelephonyManager.NETWORK_TYPE_HSPAP -> "3G"
            TelephonyManager.NETWORK_TYPE_LTE -> "LTE"
            TelephonyManager.NETWORK_TYPE_IWLAN -> "VoWiFi"
            else -> "other"
        }
    }

    private fun ensureWifi(): Outcome? {
        if (wifiConnected()) return null
        if (wifiAttempted) return blocked(wifiBlock)
        wifiAttempted = true
        val result = wifi.joinSavedNetwork(shouldStop, onStatus)
        if (result == WifiConnector.STOPPED) {
            wifiAttempted = false
            return unverified("Stopped while joining Wi-Fi")
        }
        if (result != null) {
            wifiBlock = result
            return blocked(result)
        }
        return null
    }

    @Suppress("DEPRECATION")
    private fun wifiConnected(): Boolean {
        val cm = context.getSystemService(ConnectivityManager::class.java)
        return cm.getNetworkInfo(ConnectivityManager.TYPE_WIFI)?.isConnected == true
    }

    private fun mobileDataEnabled(): Boolean {
        if (Build.VERSION.SDK_INT >= 26) {
            try {
                return context.getSystemService(TelephonyManager::class.java).isDataEnabled
            } catch (_: SecurityException) {
            }
        }
        return Settings.Global.getInt(context.contentResolver, "mobile_data", 1) == 1
    }

    private fun airplaneOn(): Boolean =
        Settings.Global.getInt(context.contentResolver, Settings.Global.AIRPLANE_MODE_ON, 0) == 1

    private fun ensureAirplane(): Outcome? {
        if (airplaneOn()) {
            wifiAttempted = false
            return ensureWifi()
        }
        onStatus("Turn airplane mode on. Wi-Fi can stay connected.")
        if (!airplanePrompted) {
            airplanePrompted = true
            openSettings(Settings.ACTION_AIRPLANE_MODE_SETTINGS)
        }
        val ready = waitUntil(180_000) { airplaneOn() }
        if (shouldStop() && !ready) return unverified("Stopped before airplane mode was on")
        if (!ready) return blocked("Airplane mode is still off, so this case was not run.")
        wifiAttempted = false
        return ensureWifi()
    }

    private fun ensureDataOff(): Outcome? {
        if (!mobileDataEnabled()) return null
        onStatus("Turn mobile data off. Wi-Fi can stay connected.")
        if (!dataPrompted) {
            dataPrompted = true
            val action = if (Build.VERSION.SDK_INT >= 28) {
                Settings.ACTION_DATA_USAGE_SETTINGS
            } else {
                Settings.ACTION_WIRELESS_SETTINGS
            }
            openSettings(action)
        }
        val ready = waitUntil(180_000) { !mobileDataEnabled() }
        if (shouldStop() && !ready) return unverified("Stopped before mobile data was turned off")
        if (!ready) return blocked("Mobile data is still on, so this case was not run.")
        return null
    }

    private fun openSettings(action: String) {
        val launch = {
            try {
                context.startActivity(Intent(action).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            } catch (_: Exception) {
                try {
                    context.startActivity(
                        Intent(Settings.ACTION_WIRELESS_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    )
                } catch (_: Exception) {
                }
            }
        }
        val activity = context as? Activity
        if (activity != null) activity.runOnUiThread { launch() } else launch()
    }

    private fun sendText(number: String, body: String): Boolean = sendParts(number, listOf(body))

    private fun sendLong(number: String, body: String): Boolean {
        @Suppress("DEPRECATION")
        val parts = SmsManager.getDefault().divideMessage(body)
        return sendParts(number, parts)
    }

    @Suppress("DEPRECATION")
    private fun sendParts(number: String, parts: List<String>): Boolean {
        val app = context.applicationContext
        val action = "${app.packageName}.SMS_SENT"
        val flags = if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_IMMUTABLE else 0
        val codes = AtomicInteger(0)
        val latch = CountDownLatch(parts.size)
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(ctx: Context, intent: Intent) {
                if (resultCode != Activity.RESULT_OK) codes.incrementAndGet()
                latch.countDown()
            }
        }
        app.registerReceiver(receiver, IntentFilter(action))
        return try {
            val intents = ArrayList<PendingIntent>(parts.size)
            parts.indices.forEach { index ->
                intents += PendingIntent.getBroadcast(app, index, Intent(action), flags)
            }
            val manager = SmsManager.getDefault()
            if (parts.size == 1) {
                manager.sendTextMessage(number, null, parts[0], intents[0], null)
            } else {
                manager.sendMultipartTextMessage(number, null, ArrayList(parts), intents, null)
            }
            val deadline = SystemClock.elapsedRealtime() + 30_000
            var finished = false
            while (SystemClock.elapsedRealtime() < deadline) {
                if (shouldStop()) break
                if (latch.await(300, TimeUnit.MILLISECONDS)) {
                    finished = true
                    break
                }
            }
            finished && codes.get() == 0
        } catch (_: Exception) {
            false
        } finally {
            try {
                app.unregisterReceiver(receiver)
            } catch (_: Exception) {
            }
        }
    }

    private fun waitUntil(timeoutMs: Long, ready: () -> Boolean): Boolean {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            if (shouldStop()) return ready()
            if (ready()) return true
            sleep(500)
        }
        return ready()
    }

    private fun sleep(ms: Long) {
        try {
            Thread.sleep(ms)
        } catch (_: InterruptedException) {
        }
    }

    private fun canSend(): Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.SEND_SMS) == PackageManager.PERMISSION_GRANTED

    private fun token(): String = List(6) { ('A'..'Z').random() }.joinToString("")

    private var noticeAsked = false
    private var airplanePrompted = false
    private var dataPrompted = false
    private var wifiAttempted = false
    private var wifiBlock = "Wi-Fi is not connected."

    /**
     * Saves a file in the phone Downloads folder and keeps writing it while the message is checked.
     */
    private class PhoneDownload(
        private val context: Context,
        private val shouldStop: () -> Boolean,
        private val onStatus: (String) -> Unit,
    ) {
        private val manager = context.getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
        private val name = "device-test-${System.currentTimeMillis()}.bin"
        private val closed = AtomicBoolean(false)
        private var downloadId = -1L
        private var direct: Thread? = null
        @Volatile private var directBytes = 0L

        fun open(): Boolean {
            val queued = SmsRunner.SOURCES.any { enqueue(it) }
            if (!queued) startDirect()
            val started = SystemClock.elapsedRealtime()
            val deadline = started + 25_000
            while (SystemClock.elapsedRealtime() < deadline) {
                if (shouldStop()) return false
                val fileBytes = savedFile()?.length() ?: 0L
                if (fileBytes > 0L) {
                    onStatus("Downloading $name to Downloads")
                    return true
                }
                val systemBytes = queryBytes()
                val waitingOnSystemFile = queued && systemBytes > 0L &&
                    SystemClock.elapsedRealtime() - started > 8_000 && direct == null
                if (waitingOnSystemFile || (downloadId >= 0 && queryStatus() == DownloadManager.STATUS_FAILED && direct == null)) {
                    if (downloadId >= 0) {
                        try {
                            manager.remove(downloadId)
                        } catch (_: Exception) {
                        }
                        downloadId = -1L
                    }
                    startDirect()
                }
                sleep()
            }
            return (savedFile()?.length() ?: 0L) > 0L
        }

        fun savedBytes(): Long = maxOf(directBytes, queryBytes(), savedFile()?.length() ?: 0L)

        fun savedFile(): File? {
            val expected = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), name)
            if (expected.exists() && expected.length() > 0L) return expected
            if (downloadId < 0) return null
            return try {
                manager.query(DownloadManager.Query().setFilterById(downloadId))?.use { cursor ->
                    if (!cursor.moveToFirst()) return null
                    val nameIndex = cursor.getColumnIndex(DownloadManager.COLUMN_LOCAL_FILENAME)
                    val path = if (nameIndex >= 0) cursor.getString(nameIndex) else null
                    val file = if (path.isNullOrBlank()) null else File(path)
                    if (file != null && file.exists() && file.length() > 0L) file else null
                }
            } catch (_: Exception) {
                null
            }
        }

        fun finish() {
            closed.set(true)
            val deadline = SystemClock.elapsedRealtime() + 20_000
            while (SystemClock.elapsedRealtime() < deadline) {
                if ((savedFile()?.length() ?: 0L) > 0L) break
                if (queryStatus() == DownloadManager.STATUS_FAILED || queryStatus() == DownloadManager.STATUS_SUCCESSFUL) break
                sleep()
            }
            savedFile()?.absolutePath?.let { path ->
                MediaScannerConnection.scanFile(context, arrayOf(path), null, null)
            }
            try {
                direct?.join(2_000)
            } catch (_: InterruptedException) {
            }
        }

        private fun enqueue(source: String): Boolean {
            return try {
                val request = DownloadManager.Request(Uri.parse(source))
                    .setTitle("Device test download")
                    .setDescription(name)
                    .setMimeType("application/octet-stream")
                    .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                    .setAllowedOverMetered(true)
                    .setAllowedOverRoaming(true)
                    .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
                @Suppress("DEPRECATION")
                request.setVisibleInDownloadsUi(true)
                downloadId = manager.enqueue(request)
                true
            } catch (_: Exception) {
                downloadId = -1L
                false
            }
        }

        private fun startDirect(): Boolean {
            if (direct != null) return true
            val file = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), name)
            direct = Thread {
                for (source in SmsRunner.SOURCES) {
                    if (closed.get() || shouldStop() || directBytes > 0L) break
                    try {
                        file.parentFile?.mkdirs()
                        val connection = (URL(source).openConnection() as HttpURLConnection).apply {
                            instanceFollowRedirects = true
                            connectTimeout = 10_000
                            readTimeout = 20_000
                            setRequestProperty("User-Agent", "DeviceTesting")
                        }
                        connection.inputStream.use { input ->
                            file.outputStream().use { output ->
                                val buffer = ByteArray(8192)
                                while (!closed.get() && !shouldStop()) {
                                    val count = input.read(buffer)
                                    if (count < 0) break
                                    output.write(buffer, 0, count)
                                    directBytes += count
                                }
                                output.flush()
                            }
                        }
                        connection.disconnect()
                    } catch (_: Exception) {
                    }
                }
                if (file.exists() && file.length() > 0L) {
                    MediaScannerConnection.scanFile(context, arrayOf(file.absolutePath), null, null)
                }
            }.also {
                it.isDaemon = true
                it.start()
            }
            return true
        }

        private fun queryBytes(): Long {
            if (downloadId < 0) return 0L
            return try {
                manager.query(DownloadManager.Query().setFilterById(downloadId))?.use { cursor ->
                    if (!cursor.moveToFirst()) return 0L
                    val index = cursor.getColumnIndex(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR)
                    if (index < 0) 0L else cursor.getLong(index)
                } ?: 0L
            } catch (_: Exception) {
                0L
            }
        }

        private fun queryStatus(): Int {
            if (downloadId < 0) return DownloadManager.STATUS_FAILED
            return try {
                manager.query(DownloadManager.Query().setFilterById(downloadId))?.use { cursor ->
                    if (!cursor.moveToFirst()) return DownloadManager.STATUS_FAILED
                    val index = cursor.getColumnIndex(DownloadManager.COLUMN_STATUS)
                    if (index < 0) DownloadManager.STATUS_FAILED else cursor.getInt(index)
                } ?: DownloadManager.STATUS_FAILED
            } catch (_: Exception) {
                DownloadManager.STATUS_FAILED
            }
        }

        private fun sleep() {
            try {
                Thread.sleep(300)
            } catch (_: InterruptedException) {
            }
        }
    }

    private fun pass(detail: String) = Outcome("PASS", detail)
    private fun fail(detail: String) = Outcome("FAIL", detail)
    private fun blocked(detail: String) = Outcome("BLOCKED", detail)
    private fun na(detail: String) = Outcome("NOT_APPLICABLE", detail)
    private fun unverified(detail: String) = Outcome("NOT_VERIFIED", detail)

    private data class Outcome(val verdict: String, val detail: String)

    companion object {
        val PATH_ONLY = setOf("SMS_Reg_03", "SMS_Reg_04", "SMS_Reg_05", "SMS_Reg_06")
        val AIRPLANE = setOf("eTinT_MSG_26", "eTinT_MSG_27")
        val DATA_OFF = setOf("eTinT_MSG_28", "eTinT_MSG_29")
        val MUST_NOT_SEND_MMS = setOf("eTinT_MSG_20", "eTinT_MSG_21")
        val THRESHOLD = setOf("eTinT_MSG_22", "eTinT_MSG_23")
        val SOURCES = listOf(
            "https://speed.cloudflare.com/__down?bytes=20000000",
            "https://proof.ovh.net/files/10Mb.dat",
        )
    }
}
