package com.example.cameratest

import android.graphics.BitmapFactory
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class ImageInspectTest : BaseCamera2Test() {

    @Test
    fun inspectImage() {
        val path = requireString("image_path") ?: return emitFail("image_path required")
        val file = File(path)
        if (!file.exists() || !file.isFile) {
            return emitFail("image file not found: $path")
        }

        try {
            val opts = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(file.absolutePath, opts)
            if (opts.outWidth <= 0 || opts.outHeight <= 0) {
                return emitFail("unable to decode image bounds")
            }
            val format = when {
                opts.outMimeType != null -> opts.outMimeType!!.substringAfterLast('/').uppercase()
                path.endsWith(".jpg", true) || path.endsWith(".jpeg", true) -> "JPEG"
                path.endsWith(".png", true) -> "PNG"
                path.endsWith(".heic", true) || path.endsWith(".heif", true) -> "HEIC"
                else -> "UNKNOWN"
            }
            emitPass(
                "width" to opts.outWidth,
                "height" to opts.outHeight,
                "format" to format,
            )
        } catch (e: Exception) {
            emitFail("inspect failed: ${e.message}")
        }
    }
}
