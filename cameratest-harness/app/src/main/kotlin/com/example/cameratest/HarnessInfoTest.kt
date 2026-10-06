package com.example.cameratest

import android.os.Build
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONArray
import org.junit.Test
import org.junit.runner.RunWith

/** Harness identity: version, role (flavor) and the operation classes it provides. */
@RunWith(AndroidJUnit4::class)
open class HarnessInfoTest : HarnessTest() {

    @Test
    fun info() {
        val pkg = appContext.packageName
        val info = appContext.packageManager.getPackageInfo(pkg, 0)
        val role = when (pkg) {
            "com.example.cameraunauthorized" -> "unauthorized"
            "com.example.camerasecondary" -> "secondary"
            else -> "harness"
        }
        val operations = JSONArray(
            listOf(
                "CapabilityTest", "PhotoCaptureTest", "CameraSwitchTest", "ResolutionMatrixTest",
                "AspectRatioCaptureTest", "FocusTest", "FlashTest", "DigitalZoomTest", "OpticalZoomTest",
                "VideoRecordTest", "VideoProfileTest", "CaptureModeTest", "LatencyPerfTest", "BurstPerfTest",
                "VideoPerfTest", "ResourcePerfTest", "EnduranceTest", "VideoEnduranceTest",
                "LifecycleEnduranceTest", "SecurityProbeTest", "MediaAccessProbeTest",
                "ImageInspectTest", "VideoInspectTest", "RepeatedPhotoStressTest",
            ),
        )
        emitPass(
            "harness_version" to info.versionName,
            "harness_version_code" to info.longVersionCode,
            "package" to pkg,
            "role" to role,
            "camera_permission_granted" to hasCameraPermission(),
            "sdk_int" to Build.VERSION.SDK_INT,
            "fingerprint" to Build.FINGERPRINT,
            "manufacturer" to Build.MANUFACTURER,
            "model" to Build.MODEL,
            "operations" to operations,
        )
    }
}
