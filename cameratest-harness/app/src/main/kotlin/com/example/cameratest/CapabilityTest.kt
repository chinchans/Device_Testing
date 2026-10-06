package com.example.cameratest

import android.graphics.ImageFormat
import android.graphics.SurfaceTexture
import android.hardware.SensorPrivacyManager
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraExtensionCharacteristics
import android.hardware.camera2.CameraMetadata
import android.hardware.camera2.CaptureRequest
import android.hardware.camera2.params.DynamicRangeProfiles
import android.media.MediaCodec
import android.os.Build
import android.util.Range
import kotlin.math.abs
import kotlin.math.sqrt
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CapabilityTest : BaseCamera2Test() {

    @Test
    fun listCapabilities() {
        val filterId = requireString("camera_id")

        try {
            val ids = if (filterId != null) {
                if (cameraManager.cameraIdList.none { it == filterId }) {
                    return emitSkip("camera_id $filterId not found")
                }
                arrayOf(filterId)
            } else {
                cameraManager.cameraIdList
            }

            if (ids.isEmpty()) {
                return emitSkip("No cameras on this device")
            }

            val cameras = JSONArray()
            for (id in ids) {
                cameras.put(describeCamera(id))
            }
            emitPass(
                "cameras" to cameras,
                "sdk_int" to Build.VERSION.SDK_INT,
                "fingerprint" to Build.FINGERPRINT,
                "manufacturer" to Build.MANUFACTURER,
                "model" to Build.MODEL,
                "camera_privacy_toggle_supported" to cameraPrivacyToggleSupported(),
                "concurrent_camera_ids" to concurrentCameraIds(),
            )
        } catch (e: SecurityException) {
            emitFail("CAMERA permission not granted: ${e.message}")
        } catch (e: Exception) {
            emitFail("Unexpected: ${e.message ?: e.javaClass.simpleName}")
        }
    }

    private fun describeCamera(id: String): JSONObject {
        val obj = JSONObject()
        obj.put("id", id)
        try {
            val chars = cameraManager.getCameraCharacteristics(id)
            val facing = chars.get(CameraCharacteristics.LENS_FACING)
            obj.put(
                "facing",
                when (facing) {
                    CameraCharacteristics.LENS_FACING_BACK -> "BACK"
                    CameraCharacteristics.LENS_FACING_FRONT -> "FRONT"
                    CameraCharacteristics.LENS_FACING_EXTERNAL -> "EXTERNAL"
                    else -> "UNKNOWN"
                },
            )

            val focals = chars.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)
            obj.put("focalLength", focals?.firstOrNull()?.toDouble() ?: JSONObject.NULL)

            val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
            val jpegSizes = JSONArray()
            map?.getOutputSizes(ImageFormat.JPEG)?.forEach { s ->
                jpegSizes.put("${s.width}x${s.height}")
            }
            obj.put("resolutions", jpegSizes)

            val videoSizes = JSONArray()
            val mrSizes = map?.getOutputSizes(android.media.MediaRecorder::class.java)
            val sizeSource = mrSizes
                ?: map?.getOutputSizes(SurfaceTexture::class.java)
                ?: emptyArray()
            sizeSource.forEach { s -> videoSizes.put("${s.width}x${s.height}") }
            obj.put("videoSizes", videoSizes)

            val fpsRanges = JSONArray()
            chars.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)
                ?.forEach { r: Range<Int> ->
                    fpsRanges.put("${r.lower}-${r.upper}")
                }
            obj.put("fpsRanges", fpsRanges)

            val afModes = JSONArray()
            chars.get(CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES)?.forEach { mode ->
                afModes.put(afModeName(mode))
            }
            obj.put("afModes", afModes)

            val hasFlash = chars.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
            obj.put("hasFlash", hasFlash)

            if (Build.VERSION.SDK_INT >= 30) {
                val zoom = chars.get(CameraCharacteristics.CONTROL_ZOOM_RATIO_RANGE)
                if (zoom != null) {
                    obj.put("zoomRatioRange", "${zoom.lower}-${zoom.upper}")
                }
            }
            describeExtended(id, chars, obj)
        } catch (e: Exception) {
            obj.put("error", e.message ?: e.javaClass.simpleName)
        }
        return obj
    }

    /** Harness v2 fields used by the host to fill case variables and gate NOT_APPLICABLE. */
    private fun describeExtended(id: String, chars: CameraCharacteristics, obj: JSONObject) {
        obj.put("hardwareLevel", when (chars.get(CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL)) {
            CameraMetadata.INFO_SUPPORTED_HARDWARE_LEVEL_LEGACY -> "LEGACY"
            CameraMetadata.INFO_SUPPORTED_HARDWARE_LEVEL_LIMITED -> "LIMITED"
            CameraMetadata.INFO_SUPPORTED_HARDWARE_LEVEL_FULL -> "FULL"
            CameraMetadata.INFO_SUPPORTED_HARDWARE_LEVEL_3 -> "LEVEL_3"
            CameraMetadata.INFO_SUPPORTED_HARDWARE_LEVEL_EXTERNAL -> "EXTERNAL"
            else -> "UNKNOWN"
        })
        val caps = chars.get(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES) ?: IntArray(0)
        obj.put("capabilities", JSONArray(caps.map { capabilityName(it) }))
        obj.put("burstCapture", caps.contains(CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_BURST_CAPTURE))
        obj.put("logicalMultiCamera", caps.contains(CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_LOGICAL_MULTI_CAMERA))
        obj.put(
            "zslReprocessing",
            caps.contains(CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_PRIVATE_REPROCESSING) ||
                caps.contains(CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_YUV_REPROCESSING),
        )
        obj.put("zslRequestKey", chars.availableCaptureRequestKeys.contains(CaptureRequest.CONTROL_ENABLE_ZSL))
        obj.put("afMaxRegions", chars.get(CameraCharacteristics.CONTROL_MAX_REGIONS_AF) ?: 0)
        obj.put(
            "timestampSource",
            if (chars.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE) ==
                CameraMetadata.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME
            ) "REALTIME" else "UNKNOWN",
        )
        equivalentFocal(chars)?.let { obj.put("equivalentFocalMm", it) }

        val physical = JSONArray()
        for (pid in chars.physicalCameraIds) {
            val p = JSONObject().put("id", pid)
            try {
                val pc = cameraManager.getCameraCharacteristics(pid)
                pc.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)?.firstOrNull()
                    ?.let { p.put("focalLength", it.toDouble()) }
                equivalentFocal(pc)?.let { p.put("equivalentFocalMm", it) }
            } catch (e: Exception) {
                p.put("error", e.message ?: e.javaClass.simpleName)
            }
            physical.put(p)
        }
        obj.put("physicalCameras", physical)

        val scenes = chars.get(CameraCharacteristics.CONTROL_AVAILABLE_SCENE_MODES) ?: IntArray(0)
        obj.put("sceneModes", JSONArray(scenes.toList().mapNotNull {
            when (it) {
                CameraMetadata.CONTROL_SCENE_MODE_HDR -> "HDR"
                CameraMetadata.CONTROL_SCENE_MODE_NIGHT -> "NIGHT"
                CameraMetadata.CONTROL_SCENE_MODE_PORTRAIT -> "PORTRAIT"
                else -> null
            }
        }))
        if (Build.VERSION.SDK_INT >= 31) {
            val ext = try {
                cameraManager.getCameraExtensionCharacteristics(id).supportedExtensions
            } catch (_: Exception) {
                emptyList()
            }
            obj.put("extensions", JSONArray(ext.map {
                when (it) {
                    CameraExtensionCharacteristics.EXTENSION_AUTOMATIC -> "AUTOMATIC"
                    CameraExtensionCharacteristics.EXTENSION_BOKEH -> "BOKEH"
                    CameraExtensionCharacteristics.EXTENSION_HDR -> "HDR"
                    CameraExtensionCharacteristics.EXTENSION_NIGHT -> "NIGHT"
                    else -> "EXTENSION_$it"
                }
            }))
        }
        obj.put(
            "hlg10",
            Build.VERSION.SDK_INT >= 33 &&
                chars.get(CameraCharacteristics.REQUEST_AVAILABLE_DYNAMIC_RANGE_PROFILES)
                    ?.supportedProfiles?.contains(DynamicRangeProfiles.HLG10) == true,
        )

        val map = chars.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
        obj.put("encoderVideoSizes", JSONArray(
            map?.getOutputSizes(MediaCodec::class.java)?.map { "${it.width}x${it.height}" } ?: emptyList<String>(),
        ))
        val ratios = map?.getOutputSizes(ImageFormat.JPEG)
            ?.map { ratioLabel(it.width, it.height) }?.distinct() ?: emptyList()
        obj.put("aspectRatios", JSONArray(ratios))
    }

    private fun equivalentFocal(c: CameraCharacteristics): Double? {
        val f = c.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)?.firstOrNull() ?: return null
        val s = c.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE) ?: return null
        val diag = sqrt((s.width * s.width + s.height * s.height).toDouble())
        return if (diag > 0) Math.round(f * 43.27 / diag * 10) / 10.0 else null
    }

    private fun ratioLabel(w: Int, h: Int): String {
        val r = w.toDouble() / h
        return listOf("4:3" to 4.0 / 3, "16:9" to 16.0 / 9, "1:1" to 1.0, "3:2" to 1.5, "18:9" to 2.0, "20:9" to 20.0 / 9)
            .firstOrNull { abs(r - it.second) <= 0.02 * it.second }?.first
            ?: "%.2f:1".format(r)
    }

    private fun cameraPrivacyToggleSupported(): Boolean =
        Build.VERSION.SDK_INT >= 31 &&
            appContext.getSystemService(SensorPrivacyManager::class.java)
                ?.supportsSensorToggle(SensorPrivacyManager.Sensors.CAMERA) == true

    private fun concurrentCameraIds(): JSONArray =
        try {
            JSONArray(cameraManager.concurrentCameraIds.map { JSONArray(it.toList()) })
        } catch (_: Exception) {
            JSONArray()
        }

    private fun capabilityName(c: Int): String = when (c) {
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_BACKWARD_COMPATIBLE -> "BACKWARD_COMPATIBLE"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_SENSOR -> "MANUAL_SENSOR"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_MANUAL_POST_PROCESSING -> "MANUAL_POST_PROCESSING"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_RAW -> "RAW"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_PRIVATE_REPROCESSING -> "PRIVATE_REPROCESSING"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_READ_SENSOR_SETTINGS -> "READ_SENSOR_SETTINGS"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_BURST_CAPTURE -> "BURST_CAPTURE"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_YUV_REPROCESSING -> "YUV_REPROCESSING"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_DEPTH_OUTPUT -> "DEPTH_OUTPUT"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_CONSTRAINED_HIGH_SPEED_VIDEO -> "CONSTRAINED_HIGH_SPEED_VIDEO"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_MOTION_TRACKING -> "MOTION_TRACKING"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_LOGICAL_MULTI_CAMERA -> "LOGICAL_MULTI_CAMERA"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_MONOCHROME -> "MONOCHROME"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_SECURE_IMAGE_DATA -> "SECURE_IMAGE_DATA"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_SYSTEM_CAMERA -> "SYSTEM_CAMERA"
        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_OFFLINE_PROCESSING -> "OFFLINE_PROCESSING"
        else -> "CAPABILITY_$c"
    }

    private fun afModeName(mode: Int): String = when (mode) {
        CameraMetadata.CONTROL_AF_MODE_OFF -> "OFF"
        CameraMetadata.CONTROL_AF_MODE_AUTO -> "AUTO"
        CameraMetadata.CONTROL_AF_MODE_MACRO -> "MACRO"
        CameraMetadata.CONTROL_AF_MODE_CONTINUOUS_VIDEO -> "CONTINUOUS_VIDEO"
        CameraMetadata.CONTROL_AF_MODE_CONTINUOUS_PICTURE -> "CONTINUOUS_PICTURE"
        CameraMetadata.CONTROL_AF_MODE_EDOF -> "EDOF"
        else -> "MODE_$mode"
    }
}
