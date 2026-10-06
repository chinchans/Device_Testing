package com.example.cameratest

import android.app.Activity
import android.content.Context
import android.graphics.Color
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCaptureSession
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraDevice
import android.hardware.camera2.CameraManager
import android.hardware.camera2.params.OutputConfiguration
import android.hardware.camera2.params.SessionConfiguration
import android.media.ImageReader
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.Process
import android.os.SystemClock
import android.view.WindowManager
import android.widget.TextView
import org.json.JSONObject
import java.io.File
import java.util.concurrent.Executor
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.abs

/**
 * Runs in its own process (":launchprobe") so the harness can measure real cold and warm
 * camera launches: launch request → first preview frame, all on elapsedRealtimeNanos.
 * Writes one JSON result to [RESULT_FILE] in the app's files dir, then finishes.
 */
class LaunchProbeActivity : Activity() {

    private lateinit var thread: HandlerThread
    private lateinit var handler: Handler
    private var device: CameraDevice? = null
    private var session: CameraCaptureSession? = null
    private var reader: ImageReader? = null
    private val done = AtomicBoolean(false)
    private val result = JSONObject()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        result.put("on_create_ns", SystemClock.elapsedRealtimeNanos())
        result.put("process_start_ns", Process.getStartElapsedRealtime() * 1_000_000L)
        result.put("pid", Process.myPid())
        result.put("request_ns", intent.getLongExtra(EXTRA_REQUEST_NS, 0L))
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(TextView(this).apply {
            text = "Camera launch probe"
            setTextColor(Color.WHITE)
            setBackgroundColor(Color.BLACK)
        })
        thread = HandlerThread("launch-probe").apply { start() }
        handler = Handler(thread.looper)
        try {
            openCamera()
        } catch (e: Exception) {
            finishWith("${e.javaClass.simpleName}: ${e.message}")
        }
    }

    private fun openCamera() {
        val manager = getSystemService(Context.CAMERA_SERVICE) as CameraManager
        val cameraId = intent.getStringExtra(EXTRA_CAMERA_ID)
            ?: manager.cameraIdList.firstOrNull {
                manager.getCameraCharacteristics(it).get(CameraCharacteristics.LENS_FACING) ==
                    CameraCharacteristics.LENS_FACING_BACK
            }
            ?: return finishWith("no rear camera")
        result.put("camera_id", cameraId)
        val sizes = manager.getCameraCharacteristics(cameraId)
            .get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            ?.getOutputSizes(ImageFormat.YUV_420_888)
        val size = sizes?.minByOrNull { abs(it.width * it.height - 640 * 480) }
            ?: return finishWith("no YUV size")
        val r = ImageReader.newInstance(size.width, size.height, ImageFormat.YUV_420_888, 2)
        reader = r
        r.setOnImageAvailableListener({ ir ->
            val now = SystemClock.elapsedRealtimeNanos()
            try {
                ir.acquireLatestImage()?.close()
            } catch (_: Exception) {
            }
            if (!result.has("first_frame_ns")) {
                result.put("first_frame_ns", now)
                finishWith(null)
            }
        }, handler)

        result.put("open_request_ns", SystemClock.elapsedRealtimeNanos())
        manager.openCamera(cameraId, object : CameraDevice.StateCallback() {
            override fun onOpened(camera: CameraDevice) {
                device = camera
                result.put("camera_opened_ns", SystemClock.elapsedRealtimeNanos())
                val executor = Executor { handler.post(it) }
                camera.createCaptureSession(
                    SessionConfiguration(
                        SessionConfiguration.SESSION_REGULAR,
                        listOf(OutputConfiguration(r.surface)),
                        executor,
                        object : CameraCaptureSession.StateCallback() {
                            override fun onConfigured(s: CameraCaptureSession) {
                                session = s
                                try {
                                    val req = camera.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW)
                                        .apply { addTarget(r.surface) }.build()
                                    s.setRepeatingRequest(req, null, handler)
                                } catch (e: Exception) {
                                    finishWith("repeating request: ${e.message}")
                                }
                            }

                            override fun onConfigureFailed(s: CameraCaptureSession) {
                                finishWith("session configuration failed")
                            }
                        },
                    ),
                )
            }

            override fun onDisconnected(camera: CameraDevice) {
                camera.close()
                finishWith("camera disconnected")
            }

            override fun onError(camera: CameraDevice, error: Int) {
                camera.close()
                finishWith("camera error code=$error")
            }
        }, handler)
    }

    /** Releases the camera first so the next launch never waits on this one. */
    private fun finishWith(error: String?) {
        if (!done.compareAndSet(false, true)) return
        if (error != null) result.put("error", error)
        try {
            session?.close()
        } catch (_: Exception) {
        }
        try {
            device?.close()
        } catch (_: Exception) {
        }
        try {
            reader?.close()
        } catch (_: Exception) {
        }
        result.put("released_ns", SystemClock.elapsedRealtimeNanos())
        val tmp = File(filesDir, "$RESULT_FILE.tmp")
        tmp.writeText(result.toString())
        tmp.renameTo(File(filesDir, RESULT_FILE))
        runOnUiThread { finish() }
    }

    override fun onDestroy() {
        thread.quitSafely()
        super.onDestroy()
    }

    companion object {
        const val RESULT_FILE = "launch_probe.json"
        const val EXTRA_CAMERA_ID = "camera_id"
        const val EXTRA_REQUEST_NS = "request_ns"
    }
}
