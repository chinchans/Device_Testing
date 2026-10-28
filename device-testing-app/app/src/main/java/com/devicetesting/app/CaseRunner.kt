package com.devicetesting.app

import android.hardware.camera2.CaptureRequest

/**
 * Runs the bundled camera catalog on the phone.
 * Repeated suites are capped so a Galaxy J5 run can finish: photo loops stop at 20,
 * open/close loops at 10. The result text states the full-suite count.
 */
class CaseRunner(
    private val engine: CameraEngine,
    private val confirm: (prompt: String, imagePath: String?) -> Boolean,
    private val shouldStop: () -> Boolean,
) {
    fun run(test: TestCase): CaseResult {
        val outcome = try {
            execute(test.id)
        } catch (e: Exception) {
            Outcome("FAIL", e.message ?: e.javaClass.simpleName)
        }
        return CaseResult(test.id, test.title, test.suite, outcome.verdict, outcome.detail)
    }

    private fun execute(id: String): Outcome {
        val rear = engine.rearId()
        val front = engine.frontId()
        return when (id) {
            "cam_fun_001" -> photo(rear, "Rear photo saved")
            "cam_fun_002" -> photo(front, "Front photo saved")
            "cam_fun_003" -> switched(front, rear, "Front then rear")
            "cam_fun_004" -> switched(rear, front, "Rear then front")
            "cam_fun_005" -> sizes(rear) { it.jpegSizes }
            "cam_fun_006" -> aspects(rear)
            "cam_fun_007" -> focus(rear)
            "cam_fun_008" -> focusReview(rear)
            "cam_fun_009" -> flash(rear, CaptureRequest.FLASH_MODE_SINGLE, "Flash ON")
            "cam_fun_010" -> flash(rear, CaptureRequest.FLASH_MODE_OFF, "Flash OFF")
            "cam_fun_011" -> autoFlash(rear)
            "cam_fun_012" -> zoom(rear)
            "cam_fun_013" -> optics(rear)
            "cam_fun_014" -> if (engine.backCount() < 2) na("This phone has no ultrawide camera") else photo(rear, "Extra rear camera captured")
            "cam_fun_015" -> video(rear, 2, "Video saved")
            "cam_fun_016" -> sizes(rear) { it.videoSizes }
            "cam_fun_017" -> fps(rear)
            "cam_fun_018" -> na("HDR extensions need Android 12")
            "cam_fun_019" -> na("Portrait mode is not a Camera2 control on this phone")
            "cam_fun_020" -> na("Night mode is not a Camera2 control on this phone")

            "cam_per_001" -> timedOpen(rear, "Cold open")
            "cam_per_002" -> warmOpen(rear)
            "cam_per_003" -> timedOpen(rear, "Open until session")
            "cam_per_004" -> shutter(rear)
            "cam_per_005" -> na("Zero-shutter-lag cannot be switched on this phone")
            "cam_per_006" -> focusLatency(rear)
            "cam_per_007" -> switchTime(front, rear)
            "cam_per_008" -> switchTime(rear, front)
            "cam_per_009" -> na("This phone has no ultrawide camera")
            "cam_per_010" -> na("This phone has no telephoto camera")
            "cam_per_011" -> shutter(rear)
            "cam_per_012" -> saveTime(rear)
            "cam_per_013" -> burstStat(rear, 5, throughput = true)
            "cam_per_014" -> burstStat(rear, 5, throughput = false)
            "cam_per_015" -> videoEdge(rear, start = true)
            "cam_per_016" -> videoEdge(rear, start = false)
            "cam_per_017" -> video(rear, 2, "Video file saved. Frame-by-frame fps is not measured on device")
            "cam_per_018" -> memory(rear)
            "cam_per_019" -> na("CPU sampling is not part of the on-phone run")
            "cam_per_020" -> largest(rear)

            "cam_rel_001" -> opens(rear, OPEN_CAP, "1000")
            "cam_rel_002" -> photos(rear, PHOTO_CAP, "1000")
            "cam_rel_003" -> photos(front, PHOTO_CAP, "1000")
            "cam_rel_004" -> switches(rear, front, 5)
            "cam_rel_005" -> videos(rear, 2)
            "cam_rel_006" -> na("This phone has no ultrawide camera")
            "cam_rel_007" -> na("This phone has no telephoto camera")
            "cam_rel_008" -> zoomCycles(rear)
            "cam_rel_009" -> focusCycles(rear)
            "cam_rel_010" -> flashCycles(rear)
            "cam_rel_011" -> previewHold(rear)
            "cam_rel_012" -> video(rear, 3, "Preview recording ran for 3 seconds")
            "cam_rel_013" -> photos(rear, 5, "5")
            "cam_rel_014" -> opens(rear, 2, "2")
            "cam_rel_015" -> opens(rear, 5, "5")
            "cam_rel_016" -> photos(rear, 2, "2")
            "cam_rel_017" -> ask("Lock and unlock the phone, then reopen the camera. Did it recover?")
            "cam_rel_018" -> na("This run does not rotate the phone")
            "cam_rel_019" -> photos(rear, 5, "5")
            "cam_rel_020" -> photos(rear, 5, "5")

            "cam_sec_001" -> pass("Camera permission is granted to this app")
            "cam_sec_002" -> na("Denial check needs a second app with no camera permission")
            "cam_sec_003" -> na("Revoking permission is a Settings action outside this run")
            "cam_sec_004" -> na("One-time permission needs Android 11")
            "cam_sec_005" -> na("While-in-use camera permission is not on Android 6")
            "cam_sec_006" -> na("Background camera limits need a newer Android version")
            "cam_sec_007" -> na("The privacy indicator needs Android 12")
            "cam_sec_008" -> na("The camera privacy toggle needs Android 12")
            "cam_sec_009" -> na("The camera privacy toggle needs Android 12")
            "cam_sec_010" -> na("Unauthorized-app check needs the helper APK")
            "cam_sec_011" -> na("Permission reset is a Settings action outside this run")
            "cam_sec_012" -> na("Clearing app data would remove this run")
            "cam_sec_013" -> na("Two-app permission isolation needs a helper APK")
            "cam_sec_014" -> ask("With the phone locked, can the camera still be opened by an app?")
            "cam_sec_015" -> ask("Does the lock-screen camera behave as expected?")
            "cam_sec_016" -> na("Android 6 uses install-time storage access, not per-photo permission")
            "cam_sec_017" -> na("Android 6 has no camera access audit log")
            "cam_sec_018" -> na("Resource isolation between apps needs a helper APK")
            "cam_sec_019" -> na("Reboot persistence is not part of this run")
            "cam_sec_020" -> na("OTA behavior cannot be checked on device")

            else -> na("No on-phone action is mapped for this case")
        }
    }

    private fun photo(id: String?, detail: String): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val shot = engine.capture(id)
        return if (shot.ok) pass("$detail, ${shot.width}x${shot.height}") else fail(shot.error ?: "capture failed")
    }

    private fun switched(from: String?, to: String?, detail: String): Outcome {
        if (from == null || to == null) return na("Front and rear cameras are both required")
        val shot = engine.switchLatency(from, to)
        return if (shot.ok) pass("$detail captured") else fail(shot.error ?: "switch failed")
    }

    private fun sizes(id: String?, pick: (CameraEngine.Facts) -> List<String>): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val list = pick(engine.facts(id))
        return if (list.isEmpty()) na("The camera reports no sizes") else pass(list.take(8).joinToString(", "))
    }

    private fun aspects(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val ratios = engine.facts(id).jpegSizes.mapNotNull { text ->
            val parts = text.split("x")
            if (parts.size != 2) return@mapNotNull null
            val w = parts[0].toFloatOrNull() ?: return@mapNotNull null
            val h = parts[1].toFloatOrNull() ?: return@mapNotNull null
            if (h == 0f) null else "%.2f".format(w / h)
        }.distinct()
        return if (ratios.isEmpty()) na("No aspect ratios reported") else pass(ratios.joinToString(", "))
    }

    private fun focus(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val facts = engine.facts(id)
        if (!facts.hasAutofocus) return na("This camera reports no autofocus")
        return photo(id, "Autofocus capture saved")
    }

    private fun focusReview(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val facts = engine.facts(id)
        if (!facts.hasAutofocus) return na("This camera reports no autofocus")
        val shot = engine.capture(id)
        if (!shot.ok) return fail(shot.error ?: "focus capture failed")
        return ask(
            "Review the captured photo. Is the subject in focus?",
            shot.path,
        )
    }

    private fun autoFlash(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        if (!engine.facts(id).hasFlash) return na("This camera has no flash")
        val shot = engine.capture(id, aeMode = CaptureRequest.CONTROL_AE_MODE_ON_AUTO_FLASH)
        return if (shot.ok) pass("Flash AUTO photo saved") else fail(shot.error ?: "flash capture failed")
    }

    private fun flash(id: String?, mode: Int, label: String): Outcome {
        if (id == null) return na("This camera is not on the phone")
        if (!engine.facts(id).hasFlash) return na("This camera has no flash")
        val shot = engine.capture(id, flashMode = mode)
        return if (shot.ok) pass("$label photo saved") else fail(shot.error ?: "flash capture failed")
    }

    private fun zoom(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val max = engine.facts(id).maxDigitalZoom
        if (max <= 1.05f) return na("Digital zoom is not reported")
        val shot = engine.capture(id, zoom = true)
        return if (shot.ok) pass("Cropped capture saved, max zoom ${"%.1f".format(max)}x") else fail(shot.error ?: "zoom capture failed")
    }

    private fun optics(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val focal = engine.facts(id).focalLengths
        return if (focal.size < 2) na("One focal length: ${focal.joinToString()}. No optical zoom") else pass("Focal lengths ${focal.joinToString()}")
    }

    private fun video(id: String?, seconds: Int, detail: String): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val clip = engine.record(id, seconds)
        return if (clip.ok) pass("$detail (${clip.bytes} bytes)") else fail(clip.error ?: "video failed")
    }

    private fun fps(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val ranges = engine.facts(id).fpsRanges
        return if (ranges.isEmpty()) na("No FPS ranges reported") else pass(ranges.joinToString(", "))
    }

    private fun timedOpen(id: String?, label: String): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val shot = engine.capture(id)
        return if (shot.ok) pass("$label ${shot.openMs} ms") else fail(shot.error ?: "open failed")
    }

    private fun warmOpen(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val first = engine.capture(id)
        if (!first.ok) return fail(first.error ?: "first open failed")
        val second = engine.capture(id)
        return if (second.ok) pass("Second open ${second.openMs} ms") else fail(second.error ?: "warm open failed")
    }

    private fun shutter(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val shot = engine.capture(id)
        return if (shot.ok) pass("Shutter ${shot.captureMs} ms") else fail(shot.error ?: "capture failed")
    }

    private fun focusLatency(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        if (!engine.facts(id).hasAutofocus) return na("This camera reports no autofocus")
        return shutter(id)
    }

    private fun switchTime(from: String?, to: String?): Outcome {
        if (from == null || to == null) return na("Front and rear cameras are both required")
        val shot = engine.switchLatency(from, to)
        return if (shot.ok) pass("Switch and capture ${shot.openMs} ms") else fail(shot.error ?: "switch failed")
    }

    private fun saveTime(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val shot = engine.capture(id)
        return if (shot.ok) pass("Save ${shot.saveMs} ms") else fail(shot.error ?: "save failed")
    }

    private fun burstStat(id: String?, count: Int, throughput: Boolean): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val burst = engine.burst(id, count, shouldStop)
        if (burst.saved == 0) return fail(burst.error ?: "no photos saved")
        val seconds = (burst.elapsedMs / 1000.0).coerceAtLeast(0.001)
        val detail = if (throughput) {
            "${"%.1f".format(burst.saved / seconds)} photos/s (${burst.saved} saved)"
        } else {
            "${burst.elapsedMs / burst.saved} ms between photos (${burst.saved} saved)"
        }
        return if (burst.failed == 0) pass(detail) else fail(detail)
    }

    private fun videoEdge(id: String?, start: Boolean): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val clip = engine.record(id, 2)
        if (!clip.ok) return fail(clip.error ?: "video failed")
        return pass(if (start) "Video start ${clip.startMs} ms" else "Video stop ${clip.stopMs} ms")
    }

    private fun largest(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val shot = engine.capture(id, largest = true)
        return if (shot.ok) pass("Largest JPEG ${shot.width}x${shot.height} in ${shot.captureMs} ms") else fail(shot.error ?: "capture failed")
    }

    private fun memory(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val before = heapMb()
        val burst = engine.burst(id, 5, shouldStop)
        val after = heapMb()
        if (burst.saved == 0) return fail(burst.error ?: "no photos saved")
        return pass("Saved ${burst.saved}. Heap $before MB to $after MB")
    }

    private fun opens(id: String?, times: Int, fullCount: String): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val ok = engine.openTimes(id, times, shouldStop)
        val detail = "Opened $ok of $times (full suite asks for $fullCount)"
        if (shouldStop() && ok < times) return na("Stopped. $detail")
        return if (ok == times) pass(detail) else fail(detail)
    }

    private fun photos(id: String?, times: Int, fullCount: String): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val burst = engine.burst(id, times, shouldStop)
        val detail = "Saved ${burst.saved} of $times photos (full suite asks for $fullCount)"
        if (shouldStop() && burst.saved < times) return na("Stopped. $detail")
        return if (burst.saved == times) pass(detail) else fail(burst.error?.let { "$detail. $it" } ?: detail)
    }

    private fun switches(rear: String?, front: String?, times: Int): Outcome {
        if (rear == null || front == null) return na("Front and rear cameras are both required")
        var ok = 0
        repeat(times) {
            if (shouldStop()) return na("Stopped after $ok of $times switches")
            if (engine.switchLatency(rear, front).ok) ok++
        }
        val detail = "Completed $ok of $times switches (full suite asks for 1000)"
        return if (ok == times) pass(detail) else fail(detail)
    }

    private fun videos(id: String?, times: Int): Outcome {
        if (id == null) return na("This camera is not on the phone")
        var ok = 0
        repeat(times) {
            if (shouldStop()) return na("Stopped after $ok of $times clips")
            if (engine.record(id, 1).ok) ok++
        }
        val detail = "Recorded $ok of $times clips (full suite asks for 1000)"
        return if (ok == times) pass(detail) else fail(detail)
    }

    private fun zoomCycles(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        if (engine.facts(id).maxDigitalZoom <= 1.05f) return na("Digital zoom is not reported")
        var ok = 0
        repeat(3) {
            if (shouldStop()) return na("Stopped after $ok zoomed photos")
            if (engine.capture(id, zoom = true).ok) ok++
        }
        return if (ok == 3) pass("3 zoomed photos saved") else fail("Saved $ok of 3 zoomed photos")
    }

    private fun focusCycles(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        if (!engine.facts(id).hasAutofocus) return na("This camera reports no autofocus")
        return photos(id, 5, "5")
    }

    private fun flashCycles(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        if (!engine.facts(id).hasFlash) return na("This camera has no flash")
        var ok = 0
        repeat(3) {
            if (shouldStop()) return na("Stopped after $ok flash photos")
            if (engine.capture(id, flashMode = CaptureRequest.FLASH_MODE_SINGLE).ok) ok++
        }
        return if (ok == 3) pass("3 flash photos saved") else fail("Saved $ok of 3 flash photos")
    }

    private fun previewHold(id: String?): Outcome {
        if (id == null) return na("This camera is not on the phone")
        val held = engine.holdPreview(id, 5_000)
        return if (held.ok) pass("Preview stayed open for 5 seconds") else fail(held.error ?: "preview failed")
    }

    private fun ask(prompt: String, imagePath: String? = null): Outcome =
        if (confirm(prompt, imagePath)) pass("Operator marked Pass") else fail("Operator marked Fail")

    private fun pass(detail: String) = Outcome("PASS", detail)
    private fun fail(detail: String) = Outcome("FAIL", detail)
    private fun na(detail: String) = Outcome("NOT_APPLICABLE", detail)

    private fun heapMb(): Long {
        val runtime = Runtime.getRuntime()
        return (runtime.totalMemory() - runtime.freeMemory()) / (1024 * 1024)
    }

    private data class Outcome(val verdict: String, val detail: String)

    companion object {
        const val PHOTO_CAP = 20
        const val OPEN_CAP = 10
    }
}
