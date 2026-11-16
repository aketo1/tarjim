package dev.tarjim.phone

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.SocketTimeoutException
import org.json.JSONArray
import org.json.JSONObject

/**
 * Tarjim for the phone: a remote control and second screen for the Tarjim program
 * running on a laptop in the same home network.
 *
 * The interface is the laptop's own page, shown in a WebView. This class only finds
 * the laptop (a UDP broadcast it answers), remembers it, and falls back to a small
 * built-in "connect" page when the laptop cannot be reached.
 */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private val prefs by lazy { getSharedPreferences("tarjim", Context.MODE_PRIVATE) }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        web = WebView(this)
        web.setBackgroundColor(Color.rgb(10, 11, 15))
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true // the pairing token lives in the page's storage
        web.settings.userAgentString = web.settings.userAgentString + " TarjimApp/0.2"
        web.overScrollMode = WebView.OVER_SCROLL_NEVER
        web.addJavascriptInterface(Bridge(), "TarjimApp")
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                val ours = url.scheme == "file" || (url.scheme == "http" && url.host == savedHost() && url.path != "/tarjim.apk")
                if (ours) return false
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, url))
                } catch (e: Exception) {
                    // no app can open it: stay where we are
                }
                return true
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (request.isForMainFrame && request.url.scheme == "http") showConnect(failed = true)
            }
        }
        setContentView(web)
        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState)
        } else {
            val host = savedHost()
            if (host == null) showConnect(failed = false) else web.loadUrl(laptopUrl(host))
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        web.saveState(outState)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack() && web.url?.startsWith("file:") == false) web.goBack() else super.onBackPressed()
    }

    private fun savedHost(): String? = prefs.getString("host", null)

    private fun laptopUrl(host: String) = "http://$host:$PORT/"

    private fun showConnect(failed: Boolean) {
        val host = savedHost() ?: ""
        web.loadUrl("file:///android_asset/connect.html?failed=${if (failed) 1 else 0}&host=${Uri.encode(host)}")
    }

    /** What the pages may ask the app to do. */
    inner class Bridge {
        /** Keep the screen on while the phone is used as the second screen. */
        @JavascriptInterface
        fun keepAwake(on: Boolean) = runOnUiThread {
            if (on) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }

        /** Look for Tarjim on the network; the page gets `onTarjimFound([...])` when done. */
        @JavascriptInterface
        fun discover() {
            Thread {
                val found = try {
                    search()
                } catch (e: Exception) {
                    JSONArray()
                }
                runOnUiThread { web.evaluateJavascript("window.onTarjimFound && window.onTarjimFound($found)", null) }
            }.start()
        }

        /** Remember this laptop and open it. Only a plain IPv4 address is accepted. */
        @JavascriptInterface
        fun connect(host: String) {
            val clean = host.trim()
            if (!Regex("""\d{1,3}(\.\d{1,3}){3}""").matches(clean)) return
            prefs.edit().putString("host", clean).apply()
            runOnUiThread { web.loadUrl(laptopUrl(clean)) }
        }
    }

    private fun search(): JSONArray {
        val ask = "TARJIM?".toByteArray()
        val targets = LinkedHashSet<InetAddress>()
        targets.add(InetAddress.getByName("255.255.255.255"))
        for (nif in NetworkInterface.getNetworkInterfaces()) {
            if (!nif.isUp || nif.isLoopback) continue
            for (addr in nif.interfaceAddresses) addr.broadcast?.let { targets.add(it) }
        }
        val out = JSONArray()
        val seen = HashSet<String>()
        DatagramSocket().use { socket ->
            socket.broadcast = true
            socket.soTimeout = 400
            repeat(2) {
                for (target in targets) {
                    try {
                        socket.send(DatagramPacket(ask, ask.size, target, DISCOVERY_PORT))
                    } catch (e: Exception) {
                        // one interface refusing the broadcast must not stop the others
                    }
                }
                val deadline = System.currentTimeMillis() + 900
                val buffer = ByteArray(512)
                while (System.currentTimeMillis() < deadline) {
                    val packet = DatagramPacket(buffer, buffer.size)
                    try {
                        socket.receive(packet)
                    } catch (e: SocketTimeoutException) {
                        continue
                    }
                    val host = packet.address.hostAddress ?: continue
                    val reply = try {
                        JSONObject(String(packet.data, 0, packet.length, Charsets.UTF_8))
                    } catch (e: Exception) {
                        continue
                    }
                    if (reply.optInt("tarjim") != 1 || !seen.add(host)) continue
                    out.put(JSONObject().put("host", host).put("name", reply.optString("name", host)))
                }
                if (out.length() > 0) return out
            }
        }
        return out
    }

    private companion object {
        const val PORT = 47901
        const val DISCOVERY_PORT = 47902
    }
}
