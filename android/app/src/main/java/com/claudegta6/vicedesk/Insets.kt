package com.claudegta6.vicedesk

import android.os.Build
import android.view.View
import android.view.WindowInsets

/**
 * Keeps content out from under the status bar, the camera cutout/notch, the navigation bar and the keyboard.
 * Android 15 draws apps edge-to-edge, so without this the top of the UI sat behind the notification panel.
 */
object Insets {
    fun applySafeArea(root: View) {
        root.setOnApplyWindowInsetsListener { v, insets ->
            if (Build.VERSION.SDK_INT >= 30) {
                val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                val ime = insets.getInsets(WindowInsets.Type.ime())
                v.setPadding(bars.left, bars.top, bars.right, maxOf(bars.bottom, ime.bottom))
            } else {
                @Suppress("DEPRECATION")
                val cut = insets.displayCutout
                @Suppress("DEPRECATION")
                v.setPadding(
                    maxOf(insets.systemWindowInsetLeft, cut?.safeInsetLeft ?: 0),
                    maxOf(insets.systemWindowInsetTop, cut?.safeInsetTop ?: 0),
                    maxOf(insets.systemWindowInsetRight, cut?.safeInsetRight ?: 0),
                    insets.systemWindowInsetBottom
                )
            }
            insets
        }
        root.requestApplyInsets()
    }
}
