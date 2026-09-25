package com.example.cameratest

import android.hardware.camera2.CameraAccessException
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CaptureRequest
import android.media.MediaRecorder
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class VideoRecordTest : BaseCamera2Test() {

    @Test
    fun recordVideo() {
        val cameraId = requireCameraId() ?: return emitFail("camera_id required")
        val resolution = requireString("resolution") ?: return emitFail("resolution required")
        val fps = optInt("fps", 30)
        val durationSec = requireInt("duration_sec") ?: return emitFail("duration_sec required")
        val outputDirArg = requireString("output_dir")
        val withAudio = optString("audio", "false").equals("true", ignoreCase = true)

        if (durationSec < 1 || durationSec > 600) {
            return emitFail("duration_sec out of range (1..600): $durationSec")
        }

        val (w, h) = parseResolution(resolution)
            ?: return emitFail("invalid resolution: $resolution")

        val outDir = resolveOutputDir(outputDirArg)
        val outFile = File(outDir, "video_${System.currentTimeMillis()}.mp4")
        var recorder: MediaRecorder? = null

        try {
            val device = openCameraBlocking(cameraId)
            cameraDevice = device

            val chars = cameraManager.getCameraCharacteristics(cameraId)
            val map = chars.get(android.hardware.camera2.CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            val previewSize = choosePreviewSize(map)
            val preview = createPreviewSurface(previewSize.width, previewSize.height)

            recorder = MediaRecorder(appContext).apply {
                if (withAudio) {
                    setAudioSource(MediaRecorder.AudioSource.MIC)
                }
                setVideoSource(MediaRecorder.VideoSource.SURFACE)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setOutputFile(outFile.absolutePath)
                setVideoEncoder(MediaRecorder.VideoEncoder.H264)
                if (withAudio) {
                    setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                }
                setVideoSize(w, h)
                setVideoFrameRate(fps)
                setVideoEncodingBitRate(bitRateFor(w, h, fps))
                prepare()
            }

            val recSurface = recorder.surface
            val session = createSessionBlocking(device, listOf(preview, recSurface))
            captureSession = session

            val recordRequest = device.createCaptureRequest(CameraDevice.TEMPLATE_RECORD).apply {
                addTarget(preview)
                addTarget(recSurface)
                set(
                    CaptureRequest.CONTROL_AF_MODE,
                    CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_VIDEO,
                )
            }.build()
            session.setRepeatingRequest(recordRequest, null, backgroundHandler)

            val stopLatch = CountDownLatch(1)
            val t0 = System.nanoTime()
            recorder.start()
            backgroundHandler.postDelayed({ stopLatch.countDown() }, durationSec * 1000L)

            if (!stopLatch.await(durationSec + 10L, TimeUnit.SECONDS)) {
                // Still attempt stop below.
            }

            try {
                recorder.stop()
            } catch (e: RuntimeException) {
                return emitFail("MediaRecorder.stop failed: ${e.message}")
            } finally {
                try {
                    recorder.reset()
                } catch (_: Exception) {
                }
                try {
                    recorder.release()
                } catch (_: Exception) {
                }
                recorder = null
            }

            val durationMs = ((System.nanoTime() - t0) / 1_000_000L).toInt()
            if (!outFile.exists() || outFile.length() == 0L) {
                return emitFail("empty video file")
            }

            emitPass(
                "video_path" to outFile.absolutePath,
                "width" to w,
                "height" to h,
                "fps" to fps.toFloat(),
                "duration_ms" to durationMs,
            )
        } catch (e: SecurityException) {
            emitFail("permission not granted: ${e.message}")
        } catch (e: CameraAccessException) {
            emitFail("CameraAccessException: ${e.message}")
        } catch (e: Exception) {
            emitFail("Unexpected: ${e.message ?: e.javaClass.simpleName}")
        } finally {
            try {
                recorder?.reset()
                recorder?.release()
            } catch (_: Exception) {
            }
        }
    }

    private fun bitRateFor(w: Int, h: Int, fps: Int): Int {
        val pixels = w.toLong() * h.toLong()
        return when {
            pixels >= 3840L * 2160L -> 35_000_000
            pixels >= 1920L * 1080L -> 12_000_000
            else -> 4_000_000
        }.coerceAtLeast(fps * 100_000)
    }
}
