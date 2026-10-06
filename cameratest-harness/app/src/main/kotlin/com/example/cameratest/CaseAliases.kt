package com.example.cameratest

/*
 * Class names referenced by the Camera Performance / Reliability / Security case files
 * (e.g. `com.example.cameratest/.ColdLaunchPerfTest`). Each alias only presets the
 * operation of a parameterized harness class; explicit `-e` arguments still win.
 * Run as: am instrument -w -e class com.example.cameratest.<Alias> ... \
 *         com.example.cameratest/androidx.test.runner.AndroidJUnitRunner
 */

// ---------------------------------------------------------------- performance

class ColdLaunchPerfTest : LatencyPerfTest() {
    override val aliasDefaults = mapOf("mode" to "cold_launch")
}

class WarmLaunchPerfTest : LatencyPerfTest() {
    override val aliasDefaults = mapOf("mode" to "warm_launch")
}

class PreviewTtffPerfTest : LatencyPerfTest() {
    override val aliasDefaults = mapOf("mode" to "ttff")
}

class ShutterLatencyPerfTest : LatencyPerfTest() {
    override val aliasDefaults = mapOf("mode" to "shutter")
}

class AutofocusPerfTest : LatencyPerfTest() {
    override val aliasDefaults = mapOf("mode" to "af")
}

class CameraSwitchPerfTest : LatencyPerfTest() {
    override val aliasDefaults = mapOf("mode" to "switch")
}

class LensSwitchPerfTest : LatencyPerfTest() {
    override val aliasDefaults = mapOf("mode" to "lens_switch")
}

class PhotoProcessingPerfTest : LatencyPerfTest() {
    override val aliasDefaults = mapOf("mode" to "processing")
}

class HighResProcessingPerfTest : LatencyPerfTest() {
    override val aliasDefaults = mapOf("mode" to "processing", "resolution" to "max")
}

class PhotoSavePerfTest : LatencyPerfTest() {
    override val aliasDefaults = mapOf("mode" to "save")
}

class VideoStartPerfTest : VideoPerfTest() {
    override val aliasDefaults = mapOf("mode" to "start")
}

class VideoFinalizePerfTest : VideoPerfTest() {
    override val aliasDefaults = mapOf("mode" to "finalize")
}

class VideoFpsStabilityTest : VideoPerfTest() {
    override val aliasDefaults = mapOf("mode" to "fps")
}

class CameraMemoryPerfTest : ResourcePerfTest() {
    override val aliasDefaults = mapOf("mode" to "memory")
}

class CameraCpuPerfTest : ResourcePerfTest() {
    override val aliasDefaults = mapOf("mode" to "cpu")
}

// ---------------------------------------------------------------- reliability

class CameraOpenCloseEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "open_close")
}

class RepeatedRearCaptureEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "capture")
}

class RepeatedFrontCaptureEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "capture")
}

class CameraSwitchEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "switch")
}

class UltrawideSwitchEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "lens_switch")
}

class TelephotoSwitchEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "lens_switch")
}

class ZoomEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "zoom")
}

class AutofocusEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "af")
}

class FlashEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "flash")
}

class PreviewEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "preview")
}

class MemoryLeakEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "memory_leak")
}

class ResourceReleaseEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "resource_release")
}

class CameraServiceEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "cameraservice")
}

class MediaIntegrityEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "media_integrity")
}

class CrashAnrEnduranceTest : EnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "mixed")
}

class VideoStartStopEnduranceTest : VideoEnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "start_stop")
}

class BackgroundForegroundRecoveryTest : LifecycleEnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "background_foreground")
}

class LockUnlockRecoveryTest : LifecycleEnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "lock_unlock")
}

class OrientationEnduranceTest : LifecycleEnduranceTest() {
    override val aliasDefaults = mapOf("operation" to "orientation")
}

// ---------------------------------------------------------------- security

class PermissionGrantSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "grant")
}

class PermissionDenialSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "deny")
}

class PermissionRevocationSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "revoke")
}

class OneTimePermissionSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "one_time")
}

class WhileInUsePermissionSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "while_in_use")
}

class BackgroundCameraRestrictionTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "background")
}

class PrivacyIndicatorSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "privacy_indicator")
}

class PrivacyToggleBlockSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "privacy_toggle_block")
}

class PrivacyToggleRestoreSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "privacy_toggle_restore")
}

class UnauthorizedAppSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "unauthorized_app")
}

class PermissionResetSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "reset")
}

class AppDataResetSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "data_reset")
}

class PermissionIsolationSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "permission_isolation")
}

class LockedDeviceCameraSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "locked_device")
}

class SecureLockscreenCameraSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "secure_lockscreen")
}

class CameraAuditSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "audit")
}

class CameraResourceIsolationSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "resource_isolation")
}

class PermissionPersistenceRebootSecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "persistence_reboot")
}

class PostOtaPrivacySecurityTest : SecurityProbeTest() {
    override val aliasDefaults = mapOf("scenario" to "post_ota")
}

class CapturedMediaPermissionSecurityTest : MediaAccessProbeTest() {
    override val aliasDefaults = mapOf("mode" to "full")
}
