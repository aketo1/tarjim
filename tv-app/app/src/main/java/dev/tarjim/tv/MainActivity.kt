package dev.tarjim.tv

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.SocketException

/** Status screen for the TV launcher: IP, port, windows, permissions, Start and Stop. */
class MainActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var status: TextView
    private val refresh = object : Runnable {
        override fun run() {
            status.text = statusText()
            handler.postDelayed(this, 1000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (resources.displayMetrics.density * 48).toInt()
        val root = LinearLayout(this)
        root.orientation = LinearLayout.VERTICAL
        root.gravity = Gravity.CENTER_HORIZONTAL
        root.setPadding(pad, pad, pad, pad)

        val title = TextView(this)
        title.text = "Tarjim  ·  ترجِم"
        title.textSize = 34f
        root.addView(title)

        status = TextView(this)
        status.textSize = 20f
        status.setPadding(0, pad / 2, 0, pad / 2)
        root.addView(status)

        val buttons = LinearLayout(this)
        buttons.orientation = LinearLayout.HORIZONTAL
        val start = Button(this)
        start.text = "Start  ·  تشغيل"
        start.setOnClickListener { startForegroundService(Intent(this, OverlayService::class.java)) }
        val stop = Button(this)
        stop.text = "Stop  ·  إيقاف"
        stop.setOnClickListener { stopService(Intent(this, OverlayService::class.java)) }
        buttons.addView(start)
        buttons.addView(stop)
        root.addView(buttons)

        setContentView(root)
        start.requestFocus()
    }

    override fun onResume() {
        super.onResume()
        handler.post(refresh)
    }

    override fun onPause() {
        handler.removeCallbacks(refresh)
        super.onPause()
    }

    private fun statusText(): String {
        val windows = OverlayHub.windowNames
        val lines = ArrayList<String>()
        lines.add("IP: ${localIp() ?: "?"}    Port: ${Wire.PORT}")
        lines.add("Service: ${if (OverlayService.running) "running" else "stopped"}")
        OverlayService.serverError?.let { lines.add("Server error: $it") }
        lines.add("Window A permission (draw over apps): ${if (Settings.canDrawOverlays(this)) "granted" else "missing"}")
        lines.add("Window B service (accessibility): ${if (OverlayA11yService.connected) "enabled" else "disabled"}")
        lines.add("Active windows: ${if (windows.isEmpty()) "none" else windows.joinToString(", ")}")
        lines.add("Layers on screen: ${OverlayHub.layerCount}")
        return lines.joinToString("\n")
    }

    private fun localIp(): String? {
        try {
            for (nif in NetworkInterface.getNetworkInterfaces()) {
                if (!nif.isUp || nif.isLoopback) continue
                for (addr in nif.inetAddresses) {
                    if (addr is Inet4Address && !addr.isLoopbackAddress) return addr.hostAddress
                }
            }
        } catch (e: SocketException) {
            return null
        }
        return null
    }
}
