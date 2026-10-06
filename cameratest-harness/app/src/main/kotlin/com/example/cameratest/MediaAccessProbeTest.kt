package com.example.cameratest

import android.content.ContentValues
import android.graphics.Bitmap
import android.graphics.Color
import android.net.Uri
import android.provider.MediaStore
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileInputStream

/**
 * Captured-media access control (scoped storage).
 *
 * mode:
 *  - full     seed file_count camera JPEGs via MediaStore, run the secondary helper in
 *             mode=read, then delete the seeded files (default)
 *  - read     (inside the helper) count seeded files visible through MediaStore and try to
 *             open them by content URI and by file path
 * Args: file_count (3), secondary_package (com.example.camerasecondary), camera_id.
 * Output follows the security contract; metric_value 1 = helper could neither list nor read.
 */
@RunWith(AndroidJUnit4::class)
open class MediaAccessProbeTest : HarnessTest() {

    private val relativeDir = "Pictures/CameraTestSecurity"

    @Test
    fun mediaAccess() {
        when (optString("mode", "full").lowercase()) {
            "read" -> read()
            else -> full()
        }
    }

    private fun full() {
        val count = optInt("file_count", 3).coerceIn(1, 50)
        val helper = optString("secondary_package", "com.example.camerasecondary")
        val health = SystemHealthMonitor(::shell)
        val seeded = ArrayList<Pair<String, Uri>>()
        var source = "camera"
        try {
            val jpeg = try {
                cameraJpeg()
            } catch (_: Exception) {
                source = "synthetic"
                syntheticJpeg()
            }
            val stamp = System.currentTimeMillis()
            for (i in 0 until count) {
                val name = "sec_media_${stamp}_$i.jpg"
                seeded += name to insertImage(name, jpeg)
            }
            val j = runHelperInstrumentation(
                helper,
                MediaAccessProbeTest::class.java.name,
                mapOf(
                    "mode" to "read",
                    "names" to seeded.joinToString(",") { it.first },
                    "uris" to seeded.joinToString(",") { it.second.toString() },
                ),
            )
            val crashes = health.fields(harnessPackages()).toMap().let {
                ((it["app_crash_count"] as? Int) ?: 0) + ((it["anr_count"] as? Int) ?: 0)
            }
            if (j == null) {
                return emitSecurity("BLOCKED_PRECONDITION", 0, 0, crashes, "reason" to "helper $helper is not installed (build the secondary flavor)")
            }
            val visible = j.optInt("visible", -1)
            val readableUri = j.optInt("readable_uri", -1)
            val readablePath = j.optInt("readable_path", -1)
            val unauthorized = maxOf(0, readableUri) + maxOf(0, readablePath)
            val enforced = seeded.size == count && visible == 0 && readableUri == 0 && readablePath == 0
            emitSecurity(
                if (enforced) "PASS" else "FAIL",
                if (enforced) 1 else 0,
                unauthorized,
                crashes,
                "scenario" to "media_access",
                "files_seeded" to seeded.size,
                "media_source" to source,
                "helper_package" to helper,
                "helper_visible" to visible,
                "helper_readable_uri" to readableUri,
                "helper_readable_path" to readablePath,
                "helper_media_permission_granted" to j.opt("media_permission_granted"),
                "helper_raw" to j.optString("raw").ifEmpty { null },
            )
        } catch (e: Exception) {
            emitSecurity("FAIL", 0, 0, 0, "scenario" to "media_access", "error" to describe(e))
        } finally {
            for ((_, uri) in seeded) {
                try {
                    appContext.contentResolver.delete(uri, null, null)
                } catch (_: Exception) {
                }
            }
        }
    }

    private fun read() {
        val names = listArg("names")
        val uris = listArg("uris")
        val resolver = appContext.contentResolver
        var visible = 0
        if (names.isNotEmpty()) {
            val selection = "${MediaStore.Images.Media.DISPLAY_NAME} IN (${names.joinToString(",") { "?" }})"
            try {
                resolver.query(
                    MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
                    arrayOf(MediaStore.Images.Media._ID),
                    selection,
                    names.toTypedArray(),
                    null,
                )?.use { visible = it.count }
            } catch (_: Exception) {
            }
        }
        var readableUri = 0
        for (u in uris) {
            try {
                resolver.openInputStream(Uri.parse(u))?.use { if (it.read() >= 0) readableUri++ }
            } catch (_: Exception) {
            }
        }
        var readablePath = 0
        val base = File("/storage/emulated/0/$relativeDir")
        for (n in names) {
            try {
                FileInputStream(File(base, n)).use { if (it.read() >= 0) readablePath++ }
            } catch (_: Exception) {
            }
        }
        val mediaPermission = listOf(
            "android.permission.READ_MEDIA_IMAGES",
            "android.permission.READ_EXTERNAL_STORAGE",
        ).any { appContext.checkSelfPermission(it) == android.content.pm.PackageManager.PERMISSION_GRANTED }
        emitSecurity(
            "PASS",
            if (visible == 0 && readableUri == 0 && readablePath == 0) 1 else 0,
            readableUri + readablePath,
            0,
            "scenario" to "media_read",
            "package" to appContext.packageName,
            "media_permission_granted" to mediaPermission,
            "visible" to visible,
            "readable_uri" to readableUri,
            "readable_path" to readablePath,
        )
    }

    private fun insertImage(name: String, jpeg: ByteArray): Uri {
        val resolver = appContext.contentResolver
        val values = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, name)
            put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg")
            put(MediaStore.Images.Media.RELATIVE_PATH, relativeDir)
            put(MediaStore.Images.Media.IS_PENDING, 1)
        }
        val uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
            ?: error("MediaStore insert failed")
        resolver.openOutputStream(uri)?.use { it.write(jpeg) } ?: error("cannot write $uri")
        resolver.update(uri, ContentValues().apply { put(MediaStore.Images.Media.IS_PENDING, 0) }, null, null)
        return uri
    }

    private fun cameraJpeg(): ByteArray {
        val cameraId = cameraArg() ?: error("no camera")
        try {
            val reader = newJpegReader(jpegSizeFor(cameraId, null) ?: error("no JPEG size"))
            openAndStream(cameraId, listOf(reader.surface))
            val shot = captureStill(cameraDevice!!, captureSession!!, reader)
            if (!shot.ok) error(shot.error ?: "capture failed")
            return shot.bytes!!
        } finally {
            closeStream()
        }
    }

    private fun syntheticJpeg(): ByteArray {
        val bmp = Bitmap.createBitmap(640, 480, Bitmap.Config.ARGB_8888)
        bmp.eraseColor(Color.rgb(90, 140, 200))
        return ByteArrayOutputStream().use { out ->
            bmp.compress(Bitmap.CompressFormat.JPEG, 90, out)
            bmp.recycle()
            out.toByteArray()
        }
    }
}
