package dev.tarjim.tv

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.content.Intent
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent

/**
 * Reads nothing: no event types, no window content. It exists only because an
 * accessibility service may add a TYPE_ACCESSIBILITY_OVERLAY window (window B).
 */
class OverlayA11yService : AccessibilityService() {

    override fun onServiceConnected() {
        super.onServiceConnected()
        // Must be this service's own WindowManager: the overlay type needs its token.
        val wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        OverlayHub.addWindow(this, wm, 'B', WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY)
        connected = true
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit

    override fun onInterrupt() = Unit

    override fun onUnbind(intent: Intent?): Boolean {
        removeWindow()
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        removeWindow()
        super.onDestroy()
    }

    private fun removeWindow() {
        connected = false
        OverlayHub.removeWindow(getSystemService(Context.WINDOW_SERVICE) as WindowManager, 'B')
    }

    companion object {
        @Volatile var connected = false
            private set
    }
}
