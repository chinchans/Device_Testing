package com.example.cameratest

import android.graphics.ImageFormat
import android.graphics.SurfaceTexture
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraMetadata
import android.os.Build
import android.util.Range
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
            emitPass("cameras" to cameras)
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
        } catch (e: Exception) {
            obj.put("error", e.message ?: e.javaClass.simpleName)
        }
        return obj
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
