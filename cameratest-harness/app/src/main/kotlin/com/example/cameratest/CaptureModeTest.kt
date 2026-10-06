package com.example.cameratest

import android.graphics.ImageFormat
import android.graphics.SurfaceTexture
import android.hardware.HardwareBuffer
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraExtensionCharacteristics
import android.hardware.camera2.CameraExtensionSession
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.CaptureResult
import android.hardware.camera2.params.ExtensionSessionConfiguration
import android.hardware.camera2.params.OutputConfiguration
import android.media.ImageReader
import android.media.MediaExtractor
import android.media.MediaFormat
import android.os.Build
import android.os.SystemClock
import android.util.Size
import androidx.annotation.RequiresApi
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.abs

/**
 * Special capture modes.
 *
 * Args: camera_id, mode = hdr | night | portrait | hdr_video
 * (mode=hdr with capture_type=video is treated as hdr_video), duration_sec (3, video only),
 * resolution, output_dir.
 * Photo modes use Camera2 extensions (API 31+) when offered, otherwise the matching
 * scene mode; if neither exists the mode is NOT_APPLICABLE (OEM camera app only).
 */
@RunWith(AndroidJUnit4::class)
open class CaptureModeTest : VideoHarnessTest() {

    private class ModeShot(
        val implementation: String,
        val bytes: ByteArray?,
        val processingMs: Double?,
        val detail: Map<String, Any?>,
        val error: String?,
    )

    @Test
    fun captureMode() {
        var mode = optString("mode", "hdr").lowercase()
        if (mode == "bokeh") mode = "portrait"
        if (mode == "hdr" && optString("capture_type", "photo").equals("video", true)) mode = "hdr_video"
        if (mode !in setOf("hdr", "night", "portrait", "hdr_video")) {
            return emitFail("mode must be hdr|night|portrait|hdr_video")
        }
        val cameraId = cameraArg() ?: return emitNotApplicable("no camera")
        try {
            if (mode == "hdr_video") return hdrVideo(cameraId)

            val extension = extensionFor(mode)
            val extSupported = Build.VERSION.SDK_INT >= 31 && extension != null &&
                cameraManager.getCameraExtensionCharacteristics(cameraId).supportedExtensions.contains(extension)
            val sceneMode = sceneModeFor(mode)
            val sceneSupported = chars(cameraId).get(CameraCharacteristics.CONTROL_AVAILABLE_SCENE_MODES)
                ?.contains(sceneMode) == true
            if (!extSupported && !sceneSupported) {
                return emitNotApplicable(
                    "camera $cameraId exposes no $mode extension or scene mode to third-party apps",
                    "camera_id" to cameraId,
                    "mode" to mode,
                )
            }

            var shot: ModeShot? = null
            var extensionError: String? = null
            if (extSupported && Build.VERSION.SDK_INT >= 31) {
                shot = try {
                    extensionCapture(cameraId, extension!!)
                } catch (e: Exception) {
                    extensionError = describe(e)
                    null
                } finally {
                    closeStream()
                }
            }
            if ((shot == null || shot.error != null) && sceneSupported) {
                extensionError = extensionError ?: shot?.error
                shot = sceneModeCapture(cameraId, sceneMode)
            }
            val s = shot ?: return emitFailWith(extensionError ?: "capture failed", "camera_id" to cameraId, "mode" to mode)

            val path = s.bytes?.let {
                saveDurably(it, resolveOutputDir(requireString("output_dir")), "${mode}_${System.currentTimeMillis()}.jpg")
                    .absolutePath
            }
            val extra = arrayListOf<Pair<String, Any?>>(
                "camera_id" to cameraId,
                "mode" to mode,
                "implementation" to s.implementation,
                "processing_ms" to s.processingMs,
                "bytes" to (s.bytes?.size ?: 0),
                "path" to path,
                "extension_error" to extensionError,
            )
            s.detail.forEach { (k, v) -> extra += k to v }
            emitResult(s.error == null && s.bytes != null, s.error, *extra.toTypedArray())
        } catch (e: Exception) {
            emitFailWith(describe(e), "camera_id" to cameraId, "mode" to mode)
        }
    }

    private fun extensionFor(mode: String): Int? {
        if (Build.VERSION.SDK_INT < 31) return null
        return when (mode) {
            "hdr" -> CameraExtensionCharacteristics.EXTENSION_HDR
            "night" -> CameraExtensionCharacteristics.EXTENSION_NIGHT
            "portrait" -> CameraExtensionCharacteristics.EXTENSION_BOKEH
            else -> null
        }
    }

    private fun sceneModeFor(mode: String): Int = when (mode) {
        "hdr" -> CameraMetadata.CONTROL_SCENE_MODE_HDR
        "night" -> CameraMetadata.CONTROL_SCENE_MODE_NIGHT
        else -> CameraMetadata.CONTROL_SCENE_MODE_PORTRAIT
    }

    @RequiresApi(31)
    private fun extensionCapture(cameraId: String, extension: Int): ModeShot {
        val extChars = cameraManager.getCameraExtensionCharacteristics(cameraId)
        val jpegSizes = extChars.getExtensionSupportedSizes(extension, ImageFormat.JPEG)
        val previewSizes = extChars.getExtensionSupportedSizes(extension, SurfaceTexture::class.java)
        if (jpegSizes.isEmpty() || previewSizes.isEmpty()) error("extension has no JPEG or preview sizes")
        val wanted = requireString("resolution")?.let { parseResolution(it) }
        val jpegSize = jpegSizes.firstOrNull { wanted != null && it.width == wanted.first && it.height == wanted.second }
            ?: jpegSizes.maxByOrNull { it.width.toLong() * it.height }!!
        val previewSize = previewSizes.minByOrNull { abs(it.width * it.height - 1280 * 720) }!!

        val previewFrames = AtomicInteger()
        val previewReader = ImageReader.newInstance(
            previewSize.width,
            previewSize.height,
            ImageFormat.PRIVATE,
            4,
            HardwareBuffer.USAGE_GPU_SAMPLED_IMAGE,
        )
        previewReader.setOnImageAvailableListener({ r ->
            try {
                r.acquireLatestImage()?.close()
                previewFrames.incrementAndGet()
            } catch (_: Exception) {
            }
        }, backgroundHandler)
        val jpegReader = newJpegReader(jpegSize)
        val executor = Executor { backgroundHandler.post(it) }
        var session: CameraExtensionSession? = null
        try {
            val device = openCameraTracked(cameraId)
            val latch = CountDownLatch(1)
            val ref = AtomicReference<CameraExtensionSession?>()
            device.createExtensionSession(
                ExtensionSessionConfiguration(
                    extension,
                    listOf(OutputConfiguration(previewReader.surface), OutputConfiguration(jpegReader.surface)),
                    executor,
                    object : CameraExtensionSession.StateCallback() {
                        override fun onConfigured(s: CameraExtensionSession) {
                            ref.set(s)
                            latch.countDown()
                        }

                        override fun onConfigureFailed(s: CameraExtensionSession) {
                            latch.countDown()
                        }
                    },
                ),
            )
            if (!latch.await(15, TimeUnit.SECONDS)) error("extension session timeout")
            session = ref.get() ?: error("extension session configuration failed")

            val previewReq = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW)
                .apply { addTarget(previewReader.surface) }.build()
            session.setRepeatingRequest(previewReq, executor, object : CameraExtensionSession.ExtensionCaptureCallback() {})
            if (!waitUntil(5000) { previewFrames.get() > 0 }) error("no extension preview frame")

            val done = CountDownLatch(1)
            val imageNs = AtomicLong(0)
            val bytesRef = AtomicReference<ByteArray?>()
            val failed = AtomicReference<String?>()
            jpegReader.setOnImageAvailableListener({ r ->
                val img = try {
                    r.acquireNextImage()
                } catch (_: Exception) {
                    null
                } ?: return@setOnImageAvailableListener
                try {
                    imageNs.set(SystemClock.elapsedRealtimeNanos())
                    val buf = img.planes[0].buffer
                    bytesRef.set(ByteArray(buf.remaining()).also { buf.get(it) })
                } finally {
                    img.close()
                    done.countDown()
                }
            }, backgroundHandler)
            val stillReq = device.createCaptureRequest(CameraDevice.TEMPLATE_STILL_CAPTURE).apply {
                addTarget(jpegReader.surface)
                set(CaptureRequest.JPEG_ORIENTATION, jpegOrientation(cameraId))
            }.build()
            val t0 = SystemClock.elapsedRealtimeNanos()
            session.capture(
                stillReq,
                executor,
                object : CameraExtensionSession.ExtensionCaptureCallback() {
                    override fun onCaptureFailed(s: CameraExtensionSession, request: CaptureRequest) {
                        failed.set("extension capture failed")
                        done.countDown()
                    }
                },
            )
            if (!done.await(30, TimeUnit.SECONDS)) failed.compareAndSet(null, "extension capture timeout")
            return ModeShot(
                "camera2_extension",
                bytesRef.get(),
                if (imageNs.get() > 0) (imageNs.get() - t0) / 1e6 else null,
                mapOf(
                    "extension" to extension,
                    "width" to jpegSize.width,
                    "height" to jpegSize.height,
                    "preview_frames" to previewFrames.get(),
                ),
                failed.get(),
            )
        } finally {
            try {
                session?.close()
            } catch (_: Exception) {
            }
            try {
                previewReader.close()
            } catch (_: Exception) {
            }
        }
    }

    private fun sceneModeCapture(cameraId: String, sceneMode: Int): ModeShot {
        val configure: (CaptureRequest.Builder) -> Unit = { b ->
            b.set(CaptureRequest.CONTROL_MODE, CaptureRequest.CONTROL_MODE_USE_SCENE_MODE)
            b.set(CaptureRequest.CONTROL_SCENE_MODE, sceneMode)
        }
        try {
            val size: Size = jpegSizeFor(cameraId, requireString("resolution") ?: "max") ?: error("no JPEG size")
            val reader = newJpegReader(size)
            val monitor = ResultMonitor()
            val device = openCameraTracked(cameraId)
            val streamSink = createSink(cameraId)
            val session: CameraCaptureSession = startStream(device, streamSink, listOf(reader.surface), monitor, configure)
            streamSink.awaitFirstFrame(5000) ?: error("no preview frame")
            Thread.sleep(500)
            val shot = captureStill(device, session, reader, timeoutSec = 30) { b ->
                configure(b)
                b.set(CaptureRequest.JPEG_ORIENTATION, jpegOrientation(cameraId))
            }
            return ModeShot(
                "scene_mode",
                shot.bytes,
                shot.shutterMs.takeIf { shot.ok },
                mapOf(
                    "scene_mode" to sceneMode,
                    "scene_mode_in_result" to shot.result?.get(CaptureResult.CONTROL_SCENE_MODE),
                    "width" to size.width,
                    "height" to size.height,
                ),
                shot.error,
            )
        } finally {
            closeStream()
        }
    }

    private fun hdrVideo(cameraId: String) {
        if (!supportsHlg10(cameraId)) {
            return emitNotApplicable("camera $cameraId does not offer HLG10 10-bit output", "camera_id" to cameraId, "mode" to "hdr_video")
        }
        val durationSec = optInt("duration_sec", 3).coerceIn(1, 600)
        val fps = optInt("fps", 30)
        val size = videoSizeFor(cameraId, requireString("resolution"))
            ?: return emitNotApplicable("no encoder-compatible video size", "camera_id" to cameraId)
        val file = File(resolveOutputDir(requireString("output_dir")), "hdr_video_${System.currentTimeMillis()}.mp4")
        val pipeline = try {
            VideoPipeline(size.width, size.height, fps, file, hdr = true)
        } catch (e: Exception) {
            return emitNotApplicable("no HEVC Main10 encoder: ${e.message}", "camera_id" to cameraId)
        }
        try {
            val device = openCameraTracked(cameraId)
            val session = createVideoSession(device, cameraId, pipeline, withPreview = false)
            session.setRepeatingRequest(videoRequest(device, cameraId, pipeline, fps), null, backgroundHandler)
            pipeline.awaitFirstSample(5000) ?: error("no encoded frame within 5s")
            Thread.sleep(durationSec * 1000L)
            stopEncoderTarget(device, session, cameraId, fps)
            val stopped = pipeline.stop()
            val written = pipeline.finalizeFile()
            val (transfer, standard) = colorInfo(file)
            val hlg = transfer == MediaFormat.COLOR_TRANSFER_HLG
            emitResult(
                stopped && written && hlg,
                pipeline.error ?: if (!hlg) "recorded file is not tagged HLG" else null,
                "camera_id" to cameraId,
                "mode" to "hdr_video",
                "width" to size.width,
                "height" to size.height,
                "encoded_frames" to pipeline.encodedFrames,
                "duration_ms" to readableDurationMs(file),
                "color_transfer" to transfer,
                "color_standard" to standard,
                "hlg" to hlg,
                "path" to file.absolutePath,
            )
        } catch (e: Exception) {
            emitFailWith(describe(e), "camera_id" to cameraId, "mode" to "hdr_video")
        } finally {
            closeStream()
            pipeline.release()
        }
    }

    private fun colorInfo(file: File): Pair<Int?, Int?> {
        val extractor = MediaExtractor()
        return try {
            extractor.setDataSource(file.absolutePath)
            for (i in 0 until extractor.trackCount) {
                val f = extractor.getTrackFormat(i)
                if (f.getString(MediaFormat.KEY_MIME)?.startsWith("video/") == true) {
                    val t = if (f.containsKey(MediaFormat.KEY_COLOR_TRANSFER)) f.getInteger(MediaFormat.KEY_COLOR_TRANSFER) else null
                    val s = if (f.containsKey(MediaFormat.KEY_COLOR_STANDARD)) f.getInteger(MediaFormat.KEY_COLOR_STANDARD) else null
                    return t to s
                }
            }
            null to null
        } catch (_: Exception) {
            null to null
        } finally {
            extractor.release()
        }
    }
}
