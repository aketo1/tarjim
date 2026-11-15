package dev.tarjim.tv

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.provider.Settings
import android.util.Log
import android.view.WindowManager
import java.io.IOException

/** Foreground service: owns the TCP server and window A (TYPE_APPLICATION_OVERLAY). */
class OverlayService : Service() {
    private var server: OverlayServer? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, getString(R.string.notif_channel), NotificationManager.IMPORTANCE_LOW),
        )
        val notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.icon)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.notif_text))
            .setOngoing(true)
            .build()
        startForeground(1, notification)
        val s = OverlayServer(applicationContext)
        try {
            s.start()
            server = s
            serverError = null
        } catch (e: IOException) {
            serverError = e.message ?: "cannot listen on port ${Wire.PORT}"
            Log.e(TAG, "cannot start the server", e)
        }
        running = true
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        ensureWindowA() // the permission may have been granted after the service started
        return START_STICKY
    }

    private fun ensureWindowA() {
        if (!Settings.canDrawOverlays(this)) {
            Log.w(TAG, "SYSTEM_ALERT_WINDOW not granted: window A unavailable")
            return
        }
        val wm = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        OverlayHub.addWindow(this, wm, 'A', WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY)
    }

    override fun onDestroy() {
        running = false
        server?.stop()
        server = null
        OverlayHub.clearAll()
        OverlayHub.removeWindow(getSystemService(Context.WINDOW_SERVICE) as WindowManager, 'A')
        super.onDestroy()
    }

    companion object {
        private const val TAG = "TarjimService"
        private const val CHANNEL = "overlay"
        @Volatile var running = false
            private set
        @Volatile var serverError: String? = null
            private set
    }
}
