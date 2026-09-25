package com.example.cameratest

import android.content.Context
import android.graphics.ImageFormat
import android.graphics.SurfaceTexture
import android.hardware.camera2.CameraAccessException
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.params.OutputConfiguration
import android.hardware.camera2.params.SessionConfiguration
import android.media.ImageReader
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.util.Size
import android.view.Surface
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Before
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference

/**
 * Shared Camera2 lifecycle + single-line JSON stdout contract for the harness.
 * Host (pytest) is the SLA judge; this APK only reports operation outcome.
 */
abstract class BaseCamera2Test {

    protected lateinit var args: Bundle
    protected lateinit var appContext: Context
    protected lateinit var cameraManager: CameraManager
    protected lateinit var backgroundHandler: Handler
    protected lateinit var backgroundThread: HandlerThread

    protected var cameraDevice: CameraDevice? = null
    protected var captureSession: CameraCaptureSession? = null
    protected var imageReader: ImageReader? = null
    protected var previewTexture: SurfaceTexture? = null
    protected var previewSurface: Surface? = null

    @Before
    fun setUp() {
        args = InstrumentationRegistry.getArguments()
        appContext = InstrumentationRegistry.getInstrumentation().targetContext
        cameraManager = appContext.getSystemService(Context.CAMERA_SERVICE) as CameraManager
        backgroundThread = HandlerThread("camera-harness-bg").apply { start() }
        backgroundHandler = Handler(backgroundThread.looper)
    }

    @After
    fun tearDown() {
        safeClose()
        try {
            backgroundThread.quitSafely()
            backgroundThread.join(2_000)
        } catch (_: Exception) {
        }
    }

    protected fun safeClose() {
        try {
            captureSession?.stopRepeating()
        } catch (_: Exception) {
        }
        try {
            captureSession?.close()
        } catch (_: Exception) {
        }
        try {
            cameraDevice?.close()
        } catch (_: Exception) {
        }
        try {
            imageReader?.close()
        } catch (_: Exception) {
        }
        try {
            previewSurface?.release()
        } catch (_: Exception) {
        }
        try {
            previewTexture?.release()
        } catch (_: Exception) {
        }
        captureSession = null
        cameraDevice = null
        imageReader = null
        previewSurface = null
        previewTexture = null
    }

    /** Single-line JSON to stdout — the only harness → host contract channel. */
    protected fun emit(fields: Map<String, Any?>) {
        val obj = JSONObject()
        for ((k, v) in fields) {
            if (v == null) continue
            when (v) {
                is JSONObject, is JSONArray -> obj.put(k, v)
                is Number, is Boolean, is String -> obj.put(k, v)
                else -> obj.put(k, v.toString())
            }
        }
        println(obj.toString())
    }

    protected fun emitPass(vararg pairs: Pair<String, Any?>) {
        emit(mapOf("result" to "PASS") + pairs.toMap())
    }

    protected fun emitFail(error: String) {
        emit(mapOf("result" to "FAIL", "error" to error))
    }

    protected fun emitSkip(reason: String) {
        emit(mapOf("result" to "SKIPPED", "error" to reason))
    }

    protected fun requireString(key: String): String? =
        args.getString(key)?.takeIf { it.isNotBlank() }

    protected fun requireInt(key: String): Int? {
        val raw = args.getString(key) ?: return null
        return raw.toIntOrNull()
    }

    protected fun optInt(key: String, default: Int): Int {
        val raw = args.getString(key) ?: return default
        return raw.toIntOrNull() ?: default
    }

    protected fun optFloat(key: String, default: Float): Float {
        val raw = args.getString(key) ?: return default
        return raw.toFloatOrNull() ?: default
    }

    protected fun optString(key: String, default: String): String =
        requireString(key) ?: default

    /** Camera2 IDs are strings; accept "0" / "1" / logical ids from -e camera_id. */
    protected fun requireCameraId(key: String = "camera_id"): String? = requireString(key)

    protected fun parseResolution(res: String): Pair<Int, Int>? {
        val m = Regex("(\\d+)\\s*[xX]\\s*(\\d+)").find(res.trim()) ?: return null
        return m.groupValues[1].toInt() to m.groupValues[2].toInt()
    }

    protected fun discoverCameraId(facing: Int): String? {
        return try {
            cameraManager.cameraIdList.firstOrNull { id ->
                cameraManager.getCameraCharacteristics(id)
                    .get(CameraCharacteristics.LENS_FACING) == facing
            }
        } catch (_: Exception) {
            null
        }
    }

    protected fun resolveOutputDir(requested: String?): File {
        val candidates = mutableListOf<File>()
        if (!requested.isNullOrBlank()) {
            candidates += File(requested)
        }
        candidates += File("/sdcard/DCIM/CameraTest")
        appContext.getExternalFilesDir("CameraTest")?.let { candidates += it }
        candidates += File(appContext.filesDir, "CameraTest")

        for (dir in candidates) {
            try {
                if (!dir.exists()) dir.mkdirs()
                if (dir.exists() && dir.canWrite()) {
                    val probe = File(dir, ".write_probe")
                    probe.writeText("ok")
                    probe.delete()
                    return dir
                }
            } catch (_: Exception) {
            }
        }
        val fallback = File(appContext.filesDir, "CameraTest")
        fallback.mkdirs()
        return fallback
    }

    protected fun openCameraBlocking(cameraId: String, timeoutSec: Long = 10): CameraDevice {
        val latch = CountDownLatch(1)
        val opened = AtomicReference<CameraDevice?>()
        val error = AtomicReference<String?>()
        cameraManager.openCamera(
            cameraId,
            object : CameraDevice.StateCallback() {
                override fun onOpened(camera: CameraDevice) {
                    opened.set(camera)
                    latch.countDown()
                }

                override fun onDisconnected(camera: CameraDevice) {
                    error.set("camera disconnected")
                    camera.close()
                    latch.countDown()
                }

                override fun onError(camera: CameraDevice, errorCode: Int) {
                    error.set("camera error code=$errorCode")
                    camera.close()
                    latch.countDown()
                }
            },
            backgroundHandler,
        )
        if (!latch.await(timeoutSec, TimeUnit.SECONDS)) {
            throw IllegalStateException("openCamera timeout after ${timeoutSec}s")
        }
        return opened.get()
            ?: throw IllegalStateException(error.get() ?: "openCamera failed")
    }

    protected fun createPreviewSurface(width: Int, height: Int): Surface {
        val texture = SurfaceTexture(/* randomTexture= */ false).apply {
            setDefaultBufferSize(width.coerceAtLeast(320), height.coerceAtLeast(240))
        }
        previewTexture = texture
        return Surface(texture).also { previewSurface = it }
    }

    protected fun createSessionBlocking(
        device: CameraDevice,
        surfaces: List<Surface>,
        timeoutSec: Long = 10,
    ): CameraCaptureSession {
        val latch = CountDownLatch(1)
        val sessionRef = AtomicReference<CameraCaptureSession?>()
        val error = AtomicReference<String?>()
        val executor = Executor { runnable -> backgroundHandler.post(runnable) }
        val configs = surfaces.map { OutputConfiguration(it) }
        val sessionConfig = SessionConfiguration(
            SessionConfiguration.SESSION_REGULAR,
            configs,
            executor,
            object : CameraCaptureSession.StateCallback() {
                override fun onConfigured(session: CameraCaptureSession) {
                    sessionRef.set(session)
                    latch.countDown()
                }

                override fun onConfigureFailed(session: CameraCaptureSession) {
                    error.set("session configuration failed")
                    latch.countDown()
                }
            },
        )
        device.createCaptureSession(sessionConfig)
        if (!latch.await(timeoutSec, TimeUnit.SECONDS)) {
            throw IllegalStateException("createCaptureSession timeout")
        }
        return sessionRef.get()
            ?: throw IllegalStateException(error.get() ?: "createCaptureSession failed")
    }

    protected fun startRepeatingPreview(
        device: CameraDevice,
        session: CameraCaptureSession,
        preview: Surface,
        extraTargets: List<Surface> = emptyList(),
    ) {
        val request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW).apply {
            addTarget(preview)
            extraTargets.forEach { addTarget(it) }
            set(
                CaptureRequest.CONTROL_AF_MODE,
                CaptureRequest.CONTROL_AF_MODE_CONTINUOUS_PICTURE,
            )
        }.build()
        session.setRepeatingRequest(request, null, backgroundHandler)
    }

    protected fun choosePreviewSize(map: android.hardware.camera2.params.StreamConfigurationMap?): Size {
        val sizes = map?.getOutputSizes(SurfaceTexture::class.java)
            ?: arrayOf(Size(1280, 720))
        return sizes.minByOrNull { it.width * it.height } ?: Size(640, 480)
    }

    protected fun assertJpegSizeSupported(cameraId: String, width: Int, height: Int): Boolean {
        return try {
            val chars = cameraManager.getCameraCharacteristics(cameraId)
            val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
                ?: return false
            map.getOutputSizes(ImageFormat.JPEG)?.any { it.width == width && it.height == height }
                ?: false
        } catch (_: Exception) {
            false
        }
    }

    protected fun jpegOrientation(cameraId: String): Int {
        return try {
            val chars = cameraManager.getCameraCharacteristics(cameraId)
            val sensor = chars.get(CameraCharacteristics.SENSOR_ORIENTATION) ?: 0
            val facing = chars.get(CameraCharacteristics.LENS_FACING)
            if (facing == CameraCharacteristics.LENS_FACING_FRONT) {
                (360 - sensor % 360) % 360
            } else {
                sensor % 360
            }
        } catch (_: Exception) {
            0
        }
    }

    protected fun isCameraAccessError(t: Throwable): Boolean =
        t is CameraAccessException || t.cause is CameraAccessException
}
