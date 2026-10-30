package com.devicetesting.app

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.graphics.SurfaceTexture
import android.os.Bundle
import android.view.LayoutInflater
import android.view.Surface
import android.view.TextureView
import android.view.View
import android.view.ViewGroup
import android.widget.BaseAdapter
import android.widget.Button
import android.widget.FrameLayout
import android.widget.GridView
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

class MainActivity : AppCompatActivity() {
    private lateinit var cases: List<TestCase>
    private lateinit var store: ResultStore
    private var suite = "functionality"
    private var running = false
    private val stop = AtomicBoolean(false)
    private val worker = Executors.newSingleThreadExecutor()
    private var engine: CameraEngine? = null
    private var pendingRun: List<TestCase>? = null
    private var pendingLabel: String = "Camera"
    private val previewSurface = AtomicReference<Surface?>(null)
    private var runProgress: TextView? = null
    private var runCase: TextView? = null
    private var runDetail: TextView? = null
    private var runStatus: TextView? = null
    private var runPreviewHint: TextView? = null
    private var runLastShot: ImageView? = null
    private var runScreenReady = false
    private var heartbeatReporter: HeartbeatReporter? = null
    private var monitorStatusView: TextView? = null
    private var lastMonitorStatus: String = "Monitor: starting…"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        cases = Catalog.load(this)
        store = ResultStore(this)
        syncTestExecutionStatus()
        heartbeatReporter = HeartbeatReporter(applicationContext) { status ->
            lastMonitorStatus = status
            monitorStatusView?.text = status
        }.also { it.start() }
        showHome()
    }

    private fun syncTestExecutionStatus() {
        val failures = store.last?.count("FAIL") ?: 0
        if (running) {
            TestExecutionStatus.setRunning(suite, null, failures)
        } else {
            TestExecutionStatus.setIdle(failures)
        }
    }

    override fun onDestroy() {
        stop.set(true)
        engine?.close()
        worker.shutdownNow()
        heartbeatReporter?.stop()
        heartbeatReporter = null
        super.onDestroy()
    }

    private fun showHome() {
        val root = inflate(R.layout.screen_home)
        val features = diagnosticFeatures()
        val normal = features.count { it.status == FeatureStatus.NORMAL }
        val action = features.count { it.status == FeatureStatus.ACTION_REQUIRED }
        root.findViewById<TextView>(R.id.home_normal_count).text = normal.toString()
        root.findViewById<TextView>(R.id.home_action_count).text = action.toString()
        monitorStatusView = root.findViewById(R.id.home_monitor_status)
        monitorStatusView?.text = lastMonitorStatus
        root.findViewById<ImageButton>(R.id.home_back).setOnClickListener { finish() }

        val grid = root.findViewById<GridView>(R.id.home_features)
        grid.adapter = DiagFeatureAdapter(features)
        grid.setOnItemClickListener { _, _, position, _ ->
            onFeatureTapped(features[position])
        }
        root.findViewById<Button>(R.id.home_test_all).setOnClickListener {
            // UI-only: no execution yet
        }
    }

    private fun onFeatureTapped(feature: DiagFeature) {
        when (feature.id) {
            "camera" -> showCamera()
            else -> toast(getString(R.string.feature_not_ready, feature.name))
        }
    }

    private fun diagnosticFeatures(): List<DiagFeature> {
        val cameraStatus = cameraFeatureStatus()
        return listOf(
            DiagFeature("battery", "Battery status", R.drawable.ic_feat_battery, FeatureStatus.IDLE, false),
            DiagFeature("nfc", "NFC", R.drawable.ic_feat_nfc, FeatureStatus.IDLE, false),
            DiagFeature("sim", "SIM", R.drawable.ic_feat_sim, FeatureStatus.IDLE, false),
            DiagFeature("sd", "SD card", R.drawable.ic_feat_sd, FeatureStatus.IDLE, false),
            DiagFeature("restart", "Power restart status", R.drawable.ic_feat_restart, FeatureStatus.IDLE, false),
            DiagFeature("software", "Official software", R.drawable.ic_feat_software, FeatureStatus.IDLE, false),
            DiagFeature("network", "Mobile network", R.drawable.ic_feat_network, FeatureStatus.IDLE, false),
            DiagFeature("sensors", "Sensors", R.drawable.ic_feat_sensors, FeatureStatus.IDLE, false),
            DiagFeature("location", "Location accuracy", R.drawable.ic_feat_location, FeatureStatus.IDLE, false),
            DiagFeature("wifi", "Wi-Fi", R.drawable.ic_feat_wifi, FeatureStatus.IDLE, false),
            DiagFeature("bluetooth", "Bluetooth", R.drawable.ic_feat_bluetooth, FeatureStatus.IDLE, false),
            DiagFeature("buttons", "Buttons", R.drawable.ic_feat_buttons, FeatureStatus.IDLE, false),
            DiagFeature("vibration", "Vibration", R.drawable.ic_feat_vibration, FeatureStatus.IDLE, false),
            DiagFeature("speaker", "Speaker", R.drawable.ic_feat_speaker, FeatureStatus.IDLE, false),
            DiagFeature("mic", "Microphone", R.drawable.ic_feat_mic, FeatureStatus.IDLE, false),
            DiagFeature("camera", "Camera", R.drawable.ic_feat_camera, cameraStatus, true),
        )
    }

    private fun cameraFeatureStatus(): FeatureStatus {
        val results = store.last?.results.orEmpty()
        if (results.isEmpty()) return FeatureStatus.IDLE
        return if (results.any { it.verdict == "FAIL" }) FeatureStatus.ACTION_REQUIRED else FeatureStatus.NORMAL
    }

    private fun showCamera() {
        val root = inflate(R.layout.screen_camera)
        root.findViewById<TextView>(R.id.camera_back).setOnClickListener { showHome() }
        val row = root.findViewById<LinearLayout>(R.id.suite_row)
        row.removeAllViews()
        Catalog.suiteOrder.forEach { id ->
            val count = cases.count { it.suite == id }
            val button = Button(this).apply {
                text = "${Catalog.suiteLabel(id)} ($count)"
                isAllCaps = false
                setOnClickListener {
                    suite = id
                    bindCases(root)
                }
            }
            row.addView(button)
        }
        root.findViewById<Button>(R.id.run_suite).setOnClickListener {
            // UI-only: no execution yet
        }
        bindCases(root)
    }

    private fun bindCases(root: View) {
        val shown = cases.filter { it.suite == suite }
        val list = root.findViewById<ListView>(R.id.case_list)
        list.adapter = CaseAdapter(shown, store)
        list.setOnItemClickListener { _, _, position, _ ->
            val item = shown[position]
            val saved = store.resultFor(item.id)
            val message = saved?.detail ?: getString(R.string.case_no_result_ui_only)
            AlertDialog.Builder(this)
                .setTitle(item.title)
                .setMessage(message)
                .setPositiveButton("Close", null)
                .show()
        }
    }

    private fun ensureRunScreen() {
        if (runScreenReady) return
        val root = inflate(R.layout.screen_run)
        runProgress = root.findViewById(R.id.run_progress)
        runCase = root.findViewById(R.id.run_case)
        runDetail = root.findViewById(R.id.run_detail)
        runStatus = root.findViewById(R.id.run_status)
        runPreviewHint = root.findViewById(R.id.run_preview_hint)
        runLastShot = root.findViewById(R.id.run_last_shot)
        root.findViewById<Button>(R.id.run_stop).setOnClickListener {
            stop.set(true)
            toast("Stopping after this case")
        }
        val preview = root.findViewById<TextureView>(R.id.run_preview)
        preview.surfaceTextureListener = object : TextureView.SurfaceTextureListener {
            override fun onSurfaceTextureAvailable(surface: SurfaceTexture, width: Int, height: Int) {
                surface.setDefaultBufferSize(1280, 720)
                previewSurface.set(Surface(surface))
                runPreviewHint?.visibility = View.GONE
                setRunStatus("Preview ready")
            }

            override fun onSurfaceTextureSizeChanged(surface: SurfaceTexture, width: Int, height: Int) = Unit

            override fun onSurfaceTextureDestroyed(surface: SurfaceTexture): Boolean {
                previewSurface.getAndSet(null)?.release()
                runPreviewHint?.visibility = View.VISIBLE
                return true
            }

            override fun onSurfaceTextureUpdated(surface: SurfaceTexture) = Unit
        }
        if (preview.isAvailable) {
            preview.surfaceTexture?.let {
                it.setDefaultBufferSize(1280, 720)
                previewSurface.set(Surface(it))
                runPreviewHint?.visibility = View.GONE
            }
        }
        window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        runScreenReady = true
    }

    private fun updateRunCase(index: Int, total: Int, test: TestCase) {
        ensureRunScreen()
        runProgress?.text = "$index of $total"
        runCase?.text = test.title
        runDetail?.text = test.id
        setRunStatus("Starting case…")
    }

    private fun setRunStatus(text: String) {
        runOnUiThread {
            if (!isFinishing) runStatus?.text = text
        }
    }

    private fun showLastShot(path: String) {
        runOnUiThread {
            if (isFinishing) return@runOnUiThread
            val bitmap = decodeSampled(path, 720, 480) ?: return@runOnUiThread
            runLastShot?.setImageBitmap(bitmap)
            setRunStatus("Last capture ready for review")
        }
    }

    private fun clearRunUi() {
        previewSurface.getAndSet(null)?.release()
        runProgress = null
        runCase = null
        runDetail = null
        runStatus = null
        runPreviewHint = null
        runLastShot = null
        runScreenReady = false
    }

    private fun showResults(record: RunRecord) {
        window.clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        clearRunUi()
        val root = inflate(R.layout.screen_results)
        root.findViewById<TextView>(R.id.results_summary).text = summaryText(record)
        val list = root.findViewById<ListView>(R.id.results_list)
        list.adapter = ResultAdapter(record.results)
        list.setOnItemClickListener { _, _, position, _ ->
            val item = record.results[position]
            AlertDialog.Builder(this)
                .setTitle("${item.id} · ${label(item.verdict)}")
                .setMessage(item.detail)
                .setPositiveButton("Close", null)
                .show()
        }
        root.findViewById<Button>(R.id.results_done).setOnClickListener { showHome() }
    }

    // Execution intentionally disabled for this UI-only build.
    // Next iteration: restore startRun → CaseRunner / CameraEngine here.
    @Suppress("unused")
    private fun startRun(selected: List<TestCase>, label: String) = Unit

    private fun waitForPreview(timeoutMs: Long) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val surface = previewSurface.get()
            if (surface != null && surface.isValid) return
            try {
                Thread.sleep(50)
            } catch (_: InterruptedException) {
                return
            }
        }
    }

    private fun confirmOnUi(prompt: String, imagePath: String?): Boolean {
        val latch = CountDownLatch(1)
        val answer = AtomicBoolean(false)
        runOnUiThread {
            if (isFinishing) {
                latch.countDown()
                return@runOnUiThread
            }
            val body = layoutInflater.inflate(R.layout.dialog_confirm_shot, null)
            body.findViewById<TextView>(R.id.confirm_message).text = prompt
            val image = body.findViewById<ImageView>(R.id.confirm_image)
            if (!imagePath.isNullOrBlank()) {
                val bitmap = decodeSampled(imagePath, 1080, 1080)
                if (bitmap != null) {
                    image.setImageBitmap(bitmap)
                    image.visibility = View.VISIBLE
                }
            }
            AlertDialog.Builder(this)
                .setTitle("Check on the phone")
                .setView(body)
                .setCancelable(false)
                .setPositiveButton("Pass") { _, _ ->
                    answer.set(true)
                    latch.countDown()
                }
                .setNegativeButton("Fail") { _, _ -> latch.countDown() }
                .show()
        }
        latch.await(5, TimeUnit.MINUTES)
        return answer.get()
    }

    private fun decodeSampled(path: String, maxWidth: Int, maxHeight: Int): android.graphics.Bitmap? {
        return try {
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(path, bounds)
            var sample = 1
            while (bounds.outWidth / sample > maxWidth || bounds.outHeight / sample > maxHeight) {
                sample *= 2
            }
            val opts = BitmapFactory.Options().apply { inSampleSize = sample }
            BitmapFactory.decodeFile(path, opts)
        } catch (_: Exception) {
            null
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != CAMERA_REQUEST) return
        val selected = pendingRun
        val label = pendingLabel
        pendingRun = null
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED && selected != null) {
            startRun(selected, label)
        } else {
            toast("Camera permission is required to run the suite")
        }
    }

    private fun summaryText(record: RunRecord?): String {
        if (record == null || record.results.isEmpty()) return "No camera run yet"
        return "${record.label}: ${record.count("PASS")} pass · ${record.count("FAIL")} fail · ${record.count("NOT_APPLICABLE")} not applicable"
    }

    private fun label(verdict: String) = when (verdict) {
        "PASS" -> "Pass"
        "FAIL" -> "Fail"
        "NOT_APPLICABLE" -> "Not applicable"
        else -> verdict
    }

    private fun inflate(layout: Int): View {
        val container = findViewById<ViewGroup>(R.id.container)
        container.removeAllViews()
        return layoutInflater.inflate(layout, container, true)
    }

    private fun toast(text: String) {
        Toast.makeText(this, text, Toast.LENGTH_SHORT).show()
    }

    private enum class FeatureStatus { IDLE, NORMAL, ACTION_REQUIRED }

    private data class DiagFeature(
        val id: String,
        val name: String,
        val iconRes: Int,
        val status: FeatureStatus,
        val ready: Boolean,
    )

    private class DiagFeatureAdapter(private val items: List<DiagFeature>) : BaseAdapter() {
        override fun getCount() = items.size
        override fun getItem(position: Int) = items[position]
        override fun getItemId(position: Int) = position.toLong()
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            val view = convertView ?: LayoutInflater.from(parent.context).inflate(R.layout.item_diag_feature, parent, false)
            val item = items[position]
            view.findViewById<TextView>(R.id.feature_name).text = item.name
            view.findViewById<ImageView>(R.id.feature_icon).setImageResource(item.iconRes)
            val circle = view.findViewById<FrameLayout>(R.id.feature_circle)
            val badge = view.findViewById<ImageView>(R.id.feature_badge)
            when (item.status) {
                FeatureStatus.NORMAL -> {
                    circle.setBackgroundResource(R.drawable.bg_circle_pass)
                    badge.visibility = View.VISIBLE
                    badge.setImageResource(R.drawable.ic_check_badge)
                }
                FeatureStatus.ACTION_REQUIRED -> {
                    circle.setBackgroundResource(R.drawable.bg_circle_fail)
                    badge.visibility = View.VISIBLE
                    badge.setImageResource(R.drawable.ic_alert_badge)
                }
                FeatureStatus.IDLE -> {
                    circle.setBackgroundResource(R.drawable.bg_circle_idle)
                    badge.visibility = View.GONE
                }
            }
            return view
        }
    }

    private class CaseAdapter(private val items: List<TestCase>, private val store: ResultStore) : BaseAdapter() {
        override fun getCount() = items.size
        override fun getItem(position: Int) = items[position]
        override fun getItemId(position: Int) = position.toLong()
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            val view = convertView ?: LayoutInflater.from(parent.context).inflate(R.layout.row_case, parent, false)
            val item = items[position]
            view.findViewById<TextView>(R.id.case_id).text = item.id
            view.findViewById<TextView>(R.id.case_title).text = item.title
            val verdict = store.verdictFor(item.id)
            val pill = view.findViewById<TextView>(R.id.case_verdict)
            pill.text = when (verdict) {
                "PASS" -> "Pass"
                "FAIL" -> "Fail"
                "NOT_APPLICABLE" -> "N/A"
                else -> ""
            }
            val color = when (verdict) {
                "PASS" -> R.color.pass
                "FAIL" -> R.color.fail
                "NOT_APPLICABLE" -> R.color.na
                else -> R.color.pending
            }
            pill.setTextColor(parent.context.getColor(color))
            return view
        }
    }

    private class ResultAdapter(private val items: List<CaseResult>) : BaseAdapter() {
        override fun getCount() = items.size
        override fun getItem(position: Int) = items[position]
        override fun getItemId(position: Int) = position.toLong()
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            val view = convertView ?: LayoutInflater.from(parent.context).inflate(R.layout.row_case, parent, false)
            val item = items[position]
            view.findViewById<TextView>(R.id.case_id).text = item.id
            view.findViewById<TextView>(R.id.case_title).text = item.title
            val pill = view.findViewById<TextView>(R.id.case_verdict)
            pill.text = when (item.verdict) {
                "PASS" -> "Pass"
                "FAIL" -> "Fail"
                "NOT_APPLICABLE" -> "N/A"
                else -> item.verdict
            }
            val color = when (item.verdict) {
                "PASS" -> R.color.pass
                "FAIL" -> R.color.fail
                "NOT_APPLICABLE" -> R.color.na
                else -> R.color.pending
            }
            pill.setTextColor(parent.context.getColor(color))
            return view
        }
    }

    companion object {
        /** UI-only build: no Camera2 / CaseRunner execution. Flip when wiring the backend. */
        private const val UI_ONLY = true
        private const val CAMERA_REQUEST = 21
    }
}
