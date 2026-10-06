package com.example.cameratest

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.view.Gravity
import android.view.WindowManager
import android.widget.TextView
import java.lang.ref.WeakReference

/**
 * Blank screen that gives the harness a real foreground state. Lifecycle and
 * background-access operations move it to the front / back; it has no logic.
 */
class ProbeActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(
            TextView(this).apply {
                text = "Camera Test Harness"
                gravity = Gravity.CENTER
                setTextColor(Color.WHITE)
                setBackgroundColor(Color.BLACK)
            },
        )
        current = WeakReference(this)
    }

    override fun onResume() {
        super.onResume()
        foreground = true
    }

    override fun onPause() {
        foreground = false
        super.onPause()
    }

    override fun onDestroy() {
        if (current?.get() === this) current = null
        super.onDestroy()
    }

    companion object {
        @Volatile
        var foreground: Boolean = false

        @Volatile
        var current: WeakReference<ProbeActivity>? = null
    }
}
