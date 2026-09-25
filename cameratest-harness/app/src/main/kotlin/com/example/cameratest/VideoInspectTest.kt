package com.example.cameratest

import android.media.MediaMetadataRetriever
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@RunWith(AndroidJUnit4::class)
class VideoInspectTest : BaseCamera2Test() {

    @Test
    fun inspectVideo() {
        val path = requireString("video_path") ?: return emitFail("video_path required")
        val file = File(path)
        if (!file.exists() || !file.isFile) {
            return emitFail("video file not found: $path")
        }

        val retriever = MediaMetadataRetriever()
        try {
            retriever.setDataSource(file.absolutePath)
            val width = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)
                ?.toIntOrNull() ?: 0
            val height = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)
                ?.toIntOrNull() ?: 0
            val durationMs = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toLongOrNull()?.toInt() ?: 0
            val fpsRaw = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_CAPTURE_FRAMERATE)
            val fps = fpsRaw?.toFloatOrNull()
                ?: estimateFps(retriever)
            if (width <= 0 || height <= 0) {
                return emitFail("unable to read video dimensions")
            }
            emitPass(
                "width" to width,
                "height" to height,
                "fps" to fps,
                "duration_ms" to durationMs,
            )
        } catch (e: Exception) {
            emitFail("inspect failed: ${e.message}")
        } finally {
            try {
                retriever.release()
            } catch (_: Exception) {
            }
        }
    }

    private fun estimateFps(retriever: MediaMetadataRetriever): Float {
        // Best-effort when CAPTURE_FRAMERATE is absent.
        return try {
            val frameCount = retriever.extractMetadata(
                MediaMetadataRetriever.METADATA_KEY_VIDEO_FRAME_COUNT,
            )?.toFloatOrNull()
            val durationMs = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                ?.toFloatOrNull()
            if (frameCount != null && durationMs != null && durationMs > 0f) {
                frameCount / (durationMs / 1000f)
            } else {
                0f
            }
        } catch (_: Exception) {
            0f
        }
    }
}
