package com.devicetesting.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.ActivityInfo
import android.telecom.PhoneAccount
import android.telecom.PhoneAccountHandle
import android.telecom.TelecomManager
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.SurfaceTexture
import android.media.ExifInterface
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.view.LayoutInflater
import android.view.Surface
import android.view.TextureView
import android.view.View
import android.view.ViewGroup
import android.widget.BaseAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.GridView
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ListView
import android.widget.TextView
import android.widget.Toast
import android.widget.VideoView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

class MainActivity : AppCompatActivity() {
    private lateinit var cases: List<TestCase>
    private lateinit var callCases: List<TestCase>
    private lateinit var store: ResultStore
    private var feature = "camera"
    private var suite = "functionality"
    private var selectedFeatureId: String? = null
    @Volatile private var running = false
    private val stop = AtomicBoolean(false)
    private val worker = Executors.newSingleThreadExecutor()
    @Volatile private var engine: CameraEngine? = null
    private var pendingRun: List<TestCase>? = null
    private var pendingLabel: String = "Camera"
    private val previewSurface = AtomicReference<Surface?>(null)
    private var runProgress: TextView? = null
    private var runCase: TextView? = null
    private var runDetail: TextView? = null
    private var runStatus: TextView? = null
    private var runPreviewHint: TextView? = null
    private var runLastShot: ImageView? = null
    private var runChoice: LinearLayout? = null
    private var confirmDialog: AlertDialog? = null
    private var runScreenReady = false
    private var photoOverlay: View? = null
    private var callWatch: CallWatch? = null
    private var heartbeatReporter: HeartbeatReporter? = null
    private var monitorStatusView: TextView? = null
    private var lastMonitorStatus: String = "Monitor: starting…"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        cases = Catalog.load(this)
        callCases = CallsCatalog.load()
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
        callWatch?.stop()
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
        grid.adapter = DiagFeatureAdapter(features, selectedFeatureId)
        grid.setOnItemClickListener { _, _, position, _ ->
            onFeatureTapped(features[position])
        }
        root.findViewById<Button>(R.id.home_test_all).setOnClickListener {
            // UI-only: no execution yet
        }
    }

    private fun onFeatureTapped(feature: DiagFeature) {
        when (feature.id) {
            "camera" -> {
                selectedFeatureId = feature.id
                showCamera()
            }
            "calls" -> {
                selectedFeatureId = feature.id
                showCalls()
            }
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
            DiagFeature("calls", "Calls", R.drawable.ic_feat_calls, featureStatus("CALL-"), true),
            DiagFeature("camera", "Camera", R.drawable.ic_feat_camera, cameraStatus, true),
        )
    }

    private fun cameraFeatureStatus(): FeatureStatus = featureStatus("cam_")

    private fun featureStatus(prefix: String): FeatureStatus {
        val results = store.last?.results?.filter { it.id.startsWith(prefix) }.orEmpty()
        if (results.isEmpty() || results.none { it.verdict == "PASS" || it.verdict == "FAIL" }) return FeatureStatus.IDLE
        return if (results.any { it.verdict == "FAIL" }) FeatureStatus.ACTION_REQUIRED else FeatureStatus.NORMAL
    }

    private fun showCamera() {
        feature = "camera"
        showFeatureScreen("Camera")
    }

    private fun showCalls() {
        feature = "calls"
        showFeatureScreen("Calls")
    }

    private fun activeCases(): List<TestCase> = if (feature == "calls") callCases else cases

    private fun showFeatureScreen(title: String) {
        val root = inflate(R.layout.screen_camera)
        root.findViewById<TextView>(R.id.feature_title).text = title
        root.findViewById<TextView>(R.id.camera_back).setOnClickListener { showHome() }
        val row = root.findViewById<LinearLayout>(R.id.suite_row)
        row.removeAllViews()
        val suiteButtons = mutableListOf<Button>()
        val refreshSuites = {
            suiteButtons.forEach { button ->
                val selected = button.tag == suite
                button.setTextColor(if (selected) Color.WHITE else getColor(R.color.muted))
                button.setBackgroundResource(
                    if (selected) R.drawable.bg_test_all else R.drawable.bg_suite_idle
                )
            }
        }
        val gap = (8 * resources.displayMetrics.density).toInt()
        Catalog.suiteOrder.forEach { id ->
            val button = Button(this).apply {
                text = Catalog.suiteLabel(id)
                tag = id
                isAllCaps = false
                layoutParams = LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                ).apply { marginEnd = gap }
                setOnClickListener {
                    suite = id
                    refreshSuites()
                    bindCases(root)
                }
            }
            suiteButtons += button
            row.addView(button)
        }
        refreshSuites()
        val numberRow = root.findViewById<LinearLayout>(R.id.call_number_row)
        if (feature == "calls") {
            numberRow.visibility = View.VISIBLE
            val numberInput = root.findViewById<EditText>(R.id.call_number)
            numberInput.setText(CallNumberStore.get(this))
            root.findViewById<Button>(R.id.call_number_save).setOnClickListener {
                val error = CallNumberStore.save(this, numberInput.text.toString())
                if (error == null) numberInput.setText(CallNumberStore.get(this))
                toast(error ?: "Test number saved")
            }
        }
        root.findViewById<Button>(R.id.run_suite).setOnClickListener {
            if (feature == "calls") requestCallsRun() else requestSuiteRun()
        }
        bindCases(root)
    }

    private fun bindCases(root: View) {
        val shown = activeCases().filter { it.suite == suite }
        val list = root.findViewById<ListView>(R.id.case_list)
        list.adapter = CaseAdapter(shown, store, { orientedBitmap(it, 320, 320) }) { openMedia(it) }
        list.setOnItemClickListener { _, _, position, _ ->
            val item = shown[position]
            val saved = store.resultFor(item.id)
            showCaseDetail(
                item.title,
                saved?.detail ?: getString(R.string.case_no_result_ui_only),
                saved?.media.orEmpty(),
            )
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
        runChoice = root.findViewById(R.id.run_choice)
        root.findViewById<Button>(R.id.run_stop).setOnClickListener {
            stop.set(true)
            runChoice?.visibility = View.GONE
            confirmDialog?.dismiss()
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
        runChoice?.visibility = View.GONE
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
            val bitmap = orientedBitmap(path, 1280, 1280) ?: return@runOnUiThread
            runLastShot?.setImageBitmap(bitmap)
            runLastShot?.setOnClickListener { openMedia(path) }
            setRunStatus(if (isVideo(path)) "Last video ready for review" else "Last capture ready for review")
        }
    }

    private fun showCaseDetail(title: String, detail: String, media: List<String>) {
        val files = media.filter { File(it).exists() }
        val body = layoutInflater.inflate(R.layout.dialog_case_detail, null)
        body.findViewById<TextView>(R.id.detail_title).text = title
        body.findViewById<TextView>(R.id.detail_message).text = detail
        val count = body.findViewById<TextView>(R.id.detail_media_count)
        val container = body.findViewById<LinearLayout>(R.id.detail_media)
        if (files.isNotEmpty()) {
            val shown = previewSelection(files)
            if (shown.size < files.size) {
                count.visibility = View.VISIBLE
                count.text = "Showing ${shown.size} of ${files.size}"
            }
            shown.forEach { path -> addCaptureView(container, path) }
        }
        val dialog = AlertDialog.Builder(this)
            .setView(body)
            .setPositiveButton("Close", null)
            .create()
        dialog.show()
        val windowHeight = if (files.isEmpty()) {
            ViewGroup.LayoutParams.WRAP_CONTENT
        } else {
            (resources.displayMetrics.heightPixels * 0.86f).toInt()
        }
        dialog.window?.setLayout(
            (resources.displayMetrics.widthPixels * 0.92f).toInt(),
            windowHeight,
        )
    }

    private fun previewSelection(files: List<String>): List<String> {
        if (files.size <= 8) return files
        return files.take(4) + files.takeLast(4)
    }

    private fun addCaptureView(parent: LinearLayout, path: String) {
        val bitmap = orientedBitmap(path, 1600, 1600) ?: return
        val maxWidth = (resources.displayMetrics.widthPixels * 0.84f).toInt()
        val maxHeight = (resources.displayMetrics.heightPixels * 0.48f).toInt()
        val (width, height) = fittedSize(bitmap.width, bitmap.height, maxWidth, maxHeight)
        val image = ImageView(this).apply {
            layoutParams = LinearLayout.LayoutParams(width, height).apply {
                topMargin = dp(8)
                gravity = Gravity.CENTER_HORIZONTAL
            }
            scaleType = ImageView.ScaleType.FIT_XY
            contentDescription = if (isVideo(path)) "Captured video" else "Captured photo"
            setImageBitmap(bitmap)
            setOnClickListener { openMedia(path) }
        }
        parent.addView(image)
    }

    private fun fittedSize(srcWidth: Int, srcHeight: Int, maxWidth: Int, maxHeight: Int): Pair<Int, Int> {
        if (srcWidth <= 0 || srcHeight <= 0) return maxWidth to maxHeight
        val aspect = srcWidth.toFloat() / srcHeight.toFloat()
        var width = maxWidth
        var height = (width / aspect).toInt().coerceAtLeast(1)
        if (height > maxHeight) {
            height = maxHeight
            width = (height * aspect).toInt().coerceAtLeast(1)
        }
        return width to height
    }

    private fun openMedia(path: String) {
        if (isVideo(path)) playVideo(path) else openImage(path)
    }

    private fun openImage(path: String) {
        val bitmap = orientedBitmap(path, 2048, 2048) ?: return
        requestedOrientation = if (bitmap.width > bitmap.height) {
            ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        } else {
            ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        }
        window.decorView.post { showPhoto(bitmap) }
    }

    private fun showPhoto(bitmap: Bitmap) {
        closePhoto(restoreOrientation = false)
        val content = findViewById<ViewGroup>(android.R.id.content)
        val image = ImageView(this).apply {
            setBackgroundColor(Color.BLACK)
            scaleType = ImageView.ScaleType.FIT_CENTER
            setImageBitmap(bitmap)
            contentDescription = "Full photo"
            layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
            setOnClickListener { closePhoto() }
        }
        content.addView(image)
        photoOverlay = image
    }

    private fun closePhoto(restoreOrientation: Boolean = true) {
        val content = findViewById<ViewGroup>(android.R.id.content)
        photoOverlay?.let { content.removeView(it) }
        photoOverlay = null
        if (restoreOrientation) {
            requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        }
    }

    override fun onBackPressed() {
        if (photoOverlay != null) {
            closePhoto()
            return
        }
        super.onBackPressed()
    }

    private fun playVideo(path: String) {
        val video = VideoView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(280),
            )
            setVideoURI(Uri.fromFile(File(path)))
            setOnPreparedListener { it.isLooping = true; start() }
        }
        AlertDialog.Builder(this)
            .setTitle("Captured video")
            .setView(video)
            .setPositiveButton("Close", null)
            .setOnDismissListener { video.stopPlayback() }
            .show()
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
        list.adapter = ResultAdapter(record.results, { orientedBitmap(it, 320, 320) }) { openMedia(it) }
        list.setOnItemClickListener { _, _, position, _ ->
            val item = record.results[position]
            showCaseDetail("${item.id} · ${label(item.verdict)}", item.detail, item.media)
        }
        root.findViewById<Button>(R.id.results_done).setOnClickListener { showHome() }
    }

    private fun requestSuiteRun() {
        if (running) {
            toast("A suite is already running")
            return
        }
        val selected = activeCases().filter { it.suite == suite }
        if (selected.isEmpty()) {
            toast("This suite has no cases")
            return
        }
        val label = Catalog.suiteLabel(suite)
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            pendingRun = selected
            pendingLabel = label
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CAMERA), CAMERA_REQUEST)
            return
        }
        startRun(selected, label)
    }

    private fun startRun(selected: List<TestCase>, label: String) {
        if (running || selected.isEmpty()) return
        running = true
        stop.set(false)
        syncTestExecutionStatus()
        heartbeatReporter?.pulse()
        ensureRunScreen()
        worker.execute {
            val cam = CameraEngine(
                this,
                previewSurface,
                onStatus = { setRunStatus(it) },
                onStillSaved = { showLastShot(it) },
            )
            engine = cam
            try {
                waitForPreview(4_000)
                val runner = CaseRunner(cam, this::confirmOnUi, { stop.get() }, { setRunStatus(it) })
                val results = mutableListOf<CaseResult>()
                selected.forEachIndexed { index, test ->
                    if (stop.get()) return@forEachIndexed
                    runOnUiThread { updateRunCase(index + 1, selected.size, test) }
                    TestExecutionStatus.setRunning(suite, test.id, results.count { it.verdict == "FAIL" })
                    heartbeatReporter?.pulse()
                    results += runner.run(test)
                }
                val record = RunRecord(label, System.currentTimeMillis(), results)
                store.save(record)
                runOnUiThread {
                    if (!isFinishing) showResults(record)
                }
            } catch (e: Exception) {
                runOnUiThread {
                    if (!isFinishing) {
                        toast(e.message ?: "Run failed")
                        showCamera()
                    }
                }
            } finally {
                try {
                    cam.close()
                } catch (_: Exception) {
                }
                if (engine === cam) engine = null
                running = false
                syncTestExecutionStatus()
                heartbeatReporter?.pulse()
            }
        }
    }

    private fun requestCallsRun() {
        if (running) {
            toast("A suite is already running")
            return
        }
        val selected = callCases.filter { it.suite == suite }
        if (selected.isEmpty()) {
            toast("This suite has no cases")
            return
        }
        val label = Catalog.suiteLabel(suite)
        if (selected.any { it.id in DIAL_CASES } && CallNumberStore.get(this).isBlank()) {
            toast("Save a test number first")
            return
        }
        val missing = callPermissions().filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isNotEmpty()) {
            pendingRun = selected
            pendingLabel = label
            ActivityCompat.requestPermissions(this, missing.toTypedArray(), PHONE_REQUEST)
            return
        }
        startCallsRun(selected, label)
    }

    private fun callPermissions(): List<String> {
        val names = mutableListOf(
            Manifest.permission.READ_PHONE_STATE,
            Manifest.permission.CALL_PHONE,
            Manifest.permission.READ_CALL_LOG,
        )
        if (android.os.Build.VERSION.SDK_INT >= 26) names += Manifest.permission.ANSWER_PHONE_CALLS
        return names
    }

    private fun startCallsRun(selected: List<TestCase>, label: String) {
        if (running || selected.isEmpty()) return
        running = true
        stop.set(false)
        syncTestExecutionStatus()
        heartbeatReporter?.pulse()
        ensureRunScreen()
        runPreviewHint?.text = "Call status"
        val watch = CallWatch(this)
        callWatch = watch
        worker.execute {
            val ready = CountDownLatch(1)
            runOnUiThread {
                watch.start()
                ready.countDown()
            }
            ready.await(2, TimeUnit.SECONDS)
            val evidence = CallEvidence(this)
            val runner = CallsRunner(
                watch,
                evidence,
                { confirmOnUi(it, null) },
                { placeSavedCall() },
                { watch.endCall() },
                { CallNumberStore.get(this) },
                { stop.get() },
                { setRunStatus(it) },
            )
            try {
                val results = mutableListOf<CaseResult>()
                selected.forEachIndexed { index, test ->
                    if (stop.get()) return@forEachIndexed
                    runOnUiThread { updateRunCase(index + 1, selected.size, test) }
                    TestExecutionStatus.setRunning(suite, test.id, results.count { it.verdict == "FAIL" })
                    heartbeatReporter?.pulse()
                    results += runner.run(test)
                }
                val record = RunRecord(label, System.currentTimeMillis(), results)
                store.save(record)
                runOnUiThread {
                    if (!isFinishing) showResults(record)
                }
            } catch (e: Exception) {
                runOnUiThread {
                    if (!isFinishing) {
                        toast(e.message ?: "Run failed")
                        showCalls()
                    }
                }
            } finally {
                runOnUiThread { watch.stop() }
                if (callWatch === watch) callWatch = null
                running = false
                syncTestExecutionStatus()
                heartbeatReporter?.pulse()
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun placeSavedCall(): Boolean {
        val number = CallNumberStore.get(this)
        if (CallNumberStore.reject(this, number) != null) return false
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CALL_PHONE) != PackageManager.PERMISSION_GRANTED) {
            return false
        }
        val latch = CountDownLatch(1)
        val placed = AtomicBoolean(false)
        runOnUiThread {
            val uri = Uri.fromParts("tel", number, null)
            try {
                val telecom = getSystemService(TelecomManager::class.java)
                if (telecom != null) {
                    val extras = Bundle()
                    val handle = simAccount(telecom)
                    if (handle != null) {
                        extras.putParcelable(TelecomManager.EXTRA_PHONE_ACCOUNT_HANDLE, handle)
                    }
                    telecom.placeCall(uri, extras)
                } else {
                    startActivity(Intent(Intent.ACTION_CALL, uri))
                }
                placed.set(true)
            } catch (_: Exception) {
                try {
                    startActivity(Intent(Intent.ACTION_CALL, uri))
                    placed.set(true)
                } catch (_: Exception) {
                }
            } finally {
                latch.countDown()
            }
        }
        latch.await(5, TimeUnit.SECONDS)
        return placed.get()
    }

    @SuppressLint("MissingPermission")
    private fun simAccount(telecom: TelecomManager): PhoneAccountHandle? {
        val accounts = try {
            telecom.callCapablePhoneAccounts
        } catch (_: SecurityException) {
            emptyList()
        }
        val sim = accounts.firstOrNull { handle ->
            val account = try {
                telecom.getPhoneAccount(handle)
            } catch (_: SecurityException) {
                null
            }
            account?.hasCapabilities(PhoneAccount.CAPABILITY_SIM_SUBSCRIPTION) == true
        }
        return sim ?: accounts.firstOrNull()
    }

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
        if (stop.get()) return false
        val latch = CountDownLatch(1)
        val answer = AtomicBoolean(false)
        val record: (Boolean) -> Unit = { pass ->
            if (latch.count > 0) {
                answer.set(pass)
                runChoice?.visibility = View.GONE
                confirmDialog?.dismiss()
                setRunStatus(if (pass) "Recorded: Pass" else "Recorded: Fail")
                latch.countDown()
            }
        }
        runOnUiThread {
            if (isFinishing) {
                latch.countDown()
                return@runOnUiThread
            }
            val bringBack = Intent(this, MainActivity::class.java)
            bringBack.addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            startActivity(bringBack)
            setRunStatus(prompt)
            runChoice?.visibility = View.VISIBLE
            findViewById<Button>(R.id.run_pass)?.setOnClickListener { record(true) }
            findViewById<Button>(R.id.run_fail)?.setOnClickListener { record(false) }
            if (!imagePath.isNullOrBlank()) {
                val body = layoutInflater.inflate(R.layout.dialog_confirm_shot, null)
                body.findViewById<TextView>(R.id.confirm_message).text = prompt
                val image = body.findViewById<ImageView>(R.id.confirm_image)
                val bitmap = decodeSampled(imagePath, 1080, 1080)
                if (bitmap != null) {
                    image.setImageBitmap(bitmap)
                    image.visibility = View.VISIBLE
                }
                confirmDialog = AlertDialog.Builder(this)
                    .setTitle("Check on the phone")
                    .setView(body)
                    .setCancelable(false)
                    .setPositiveButton("Pass") { _, _ -> record(true) }
                    .setNegativeButton("Fail") { _, _ -> record(false) }
                    .create()
                try {
                    confirmDialog?.show()
                } catch (_: Exception) {
                    confirmDialog = null
                }
            }
        }
        val deadline = System.currentTimeMillis() + TimeUnit.MINUTES.toMillis(5)
        while (latch.count > 0 && System.currentTimeMillis() < deadline) {
            if (stop.get()) {
                runOnUiThread {
                    runChoice?.visibility = View.GONE
                    confirmDialog?.dismiss()
                }
                return false
            }
            latch.await(200, TimeUnit.MILLISECONDS)
        }
        return answer.get()
    }

    private fun orientedBitmap(path: String, maxWidth: Int, maxHeight: Int): Bitmap? {
        val raw = previewBitmap(path, maxWidth, maxHeight) ?: return null
        if (isVideo(path)) return raw
        val degrees = exifDegrees(path)
        if (degrees == 0) return raw
        val matrix = Matrix().apply { postRotate(degrees.toFloat()) }
        return Bitmap.createBitmap(raw, 0, 0, raw.width, raw.height, matrix, true)
    }

    private fun exifDegrees(path: String): Int {
        return try {
            when (ExifInterface(path).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)) {
                ExifInterface.ORIENTATION_ROTATE_90, ExifInterface.ORIENTATION_TRANSPOSE -> 90
                ExifInterface.ORIENTATION_ROTATE_180, ExifInterface.ORIENTATION_FLIP_VERTICAL -> 180
                ExifInterface.ORIENTATION_ROTATE_270, ExifInterface.ORIENTATION_TRANSVERSE -> 270
                else -> 0
            }
        } catch (_: Exception) {
            0
        }
    }

    private fun isVideo(path: String) = path.endsWith(".mp4", ignoreCase = true)

    private fun previewBitmap(path: String, maxWidth: Int, maxHeight: Int): Bitmap? {
        return if (isVideo(path)) videoPoster(path) else decodeSampled(path, maxWidth, maxHeight)
    }

    private fun videoPoster(path: String): Bitmap? {
        val retriever = MediaMetadataRetriever()
        return try {
            retriever.setDataSource(path)
            retriever.frameAtTime
        } catch (_: Exception) {
            null
        } finally {
            try {
                retriever.release()
            } catch (_: Exception) {
            }
        }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    private fun decodeSampled(path: String, maxWidth: Int, maxHeight: Int): Bitmap? {
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
        val selected = pendingRun
        val label = pendingLabel
        pendingRun = null
        if (requestCode == PHONE_REQUEST) {
            if (selected != null) startCallsRun(selected, label)
            return
        }
        if (requestCode != CAMERA_REQUEST) return
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED && selected != null) {
            startRun(selected, label)
        } else {
            toast("Camera permission is required to run the suite")
        }
    }

    private fun summaryText(record: RunRecord?): String {
        if (record == null || record.results.isEmpty()) return "No run yet"
        return "${record.label}: ${record.count("PASS")} pass · ${record.count("FAIL")} fail · ${record.count("BLOCKED")} blocked · ${record.count("NOT_APPLICABLE")} not applicable · ${record.count("NOT_VERIFIED")} not verified"
    }

    private fun label(verdict: String) = when (verdict) {
        "PASS" -> "Pass"
        "FAIL" -> "Fail"
        "NOT_APPLICABLE" -> "Not applicable"
        "BLOCKED" -> "Blocked"
        "NOT_VERIFIED" -> "Not verified"
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

    private class DiagFeatureAdapter(
        private val items: List<DiagFeature>,
        private val selectedId: String?,
    ) : BaseAdapter() {
        override fun getCount() = items.size
        override fun getItem(position: Int) = items[position]
        override fun getItemId(position: Int) = position.toLong()
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            val view = convertView ?: LayoutInflater.from(parent.context).inflate(R.layout.item_diag_feature, parent, false)
            val item = items[position]
            val selected = item.id == selectedId
            val name = view.findViewById<TextView>(R.id.feature_name)
            name.text = item.name
            name.setTextColor(view.context.getColor(if (selected) R.color.brand else R.color.ink))
            view.findViewById<ImageView>(R.id.feature_icon).setImageResource(item.iconRes)
            val circle = view.findViewById<FrameLayout>(R.id.feature_circle)
            val badge = view.findViewById<ImageView>(R.id.feature_badge)
            if (selected) {
                circle.setBackgroundResource(R.drawable.bg_circle_selected)
            }
            when (item.status) {
                FeatureStatus.NORMAL -> {
                    if (!selected) circle.setBackgroundResource(R.drawable.bg_circle_pass)
                    badge.visibility = View.VISIBLE
                    badge.setImageResource(R.drawable.ic_check_badge)
                }
                FeatureStatus.ACTION_REQUIRED -> {
                    if (!selected) circle.setBackgroundResource(R.drawable.bg_circle_fail)
                    badge.visibility = View.VISIBLE
                    badge.setImageResource(R.drawable.ic_alert_badge)
                }
                FeatureStatus.IDLE -> {
                    if (!selected) circle.setBackgroundResource(R.drawable.bg_circle_idle)
                    badge.visibility = View.GONE
                }
            }
            return view
        }
    }

    private class CaseAdapter(
        private val items: List<TestCase>,
        private val store: ResultStore,
        private val thumb: (String) -> Bitmap?,
        private val onOpen: (String) -> Unit,
    ) : BaseAdapter() {
        override fun getCount() = items.size
        override fun getItem(position: Int) = items[position]
        override fun getItemId(position: Int) = position.toLong()
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            val view = convertView ?: LayoutInflater.from(parent.context).inflate(R.layout.row_case, parent, false)
            val item = items[position]
            view.findViewById<TextView>(R.id.case_id).text = item.id
            view.findViewById<TextView>(R.id.case_title).text = item.title
            bindThumb(view, store.resultFor(item.id)?.media, thumb, onOpen)
            val verdict = store.verdictFor(item.id)
            val pill = view.findViewById<TextView>(R.id.case_verdict)
            pill.text = when (verdict) {
                "PASS" -> "Pass"
                "FAIL" -> "Fail"
                "NOT_APPLICABLE" -> "N/A"
                "BLOCKED" -> "Blocked"
                "NOT_VERIFIED" -> "Unverified"
                else -> ""
            }
            val color = when (verdict) {
                "PASS" -> R.color.pass
                "FAIL" -> R.color.fail
                "NOT_APPLICABLE", "BLOCKED" -> R.color.na
                "NOT_VERIFIED" -> R.color.pending
                else -> R.color.pending
            }
            pill.setTextColor(parent.context.getColor(color))
            return view
        }
    }

    private class ResultAdapter(
        private val items: List<CaseResult>,
        private val thumb: (String) -> Bitmap?,
        private val onOpen: (String) -> Unit,
    ) : BaseAdapter() {
        override fun getCount() = items.size
        override fun getItem(position: Int) = items[position]
        override fun getItemId(position: Int) = position.toLong()
        override fun getView(position: Int, convertView: View?, parent: ViewGroup): View {
            val view = convertView ?: LayoutInflater.from(parent.context).inflate(R.layout.row_case, parent, false)
            val item = items[position]
            view.findViewById<TextView>(R.id.case_id).text = item.id
            view.findViewById<TextView>(R.id.case_title).text = item.title
            bindThumb(view, item.media, thumb, onOpen)
            val pill = view.findViewById<TextView>(R.id.case_verdict)
            pill.text = when (item.verdict) {
                "PASS" -> "Pass"
                "FAIL" -> "Fail"
                "NOT_APPLICABLE" -> "N/A"
                "BLOCKED" -> "Blocked"
                "NOT_VERIFIED" -> "Unverified"
                else -> item.verdict
            }
            val color = when (item.verdict) {
                "PASS" -> R.color.pass
                "FAIL" -> R.color.fail
                "NOT_APPLICABLE", "BLOCKED" -> R.color.na
                "NOT_VERIFIED" -> R.color.pending
                else -> R.color.pending
            }
            pill.setTextColor(parent.context.getColor(color))
            return view
        }
    }

    companion object {
        private fun bindThumb(
            view: View,
            media: List<String>?,
            thumb: (String) -> Bitmap?,
            onOpen: (String) -> Unit,
        ) {
            val image = view.findViewById<ImageView>(R.id.case_thumb)
            val path = media?.firstOrNull { File(it).exists() }
            val bitmap = if (path == null) null else thumb(path)
            if (path == null || bitmap == null) {
                image.setOnClickListener(null)
                image.setImageDrawable(null)
                image.visibility = View.GONE
            } else {
                image.setImageBitmap(bitmap)
                image.visibility = View.VISIBLE
                image.setOnClickListener { onOpen(path) }
            }
        }

        private const val CAMERA_REQUEST = 21
        private const val PHONE_REQUEST = 22
        private val DIAL_CASES = setOf(
            "CALL-FUNC-002",
            "CALL-PERF-001",
            "CALL-PERF-003",
            "CALL-REL-001",
            "CALL-REL-002",
        )
    }
}
