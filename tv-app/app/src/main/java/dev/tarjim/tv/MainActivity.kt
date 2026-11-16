package dev.tarjim.tv

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.SocketException

/**
 * The screen the user sees when opening Tarjim from the TV launcher: is the TV ready to
 * receive subtitles, what its address is, and Start / Stop for the remote's D-pad.
 * Built in code with framework views only (the app has no libraries).
 */
class MainActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var headline: TextView
    private lateinit var detail: TextView
    private lateinit var lamp: View
    private lateinit var address: TextView
    private lateinit var rowService: Row
    private lateinit var rowWindowA: Row
    private lateinit var rowWindowB: Row
    private lateinit var startButton: TextView
    private lateinit var stopButton: TextView

    private val refresh = object : Runnable {
        override fun run() {
            render()
            handler.postDelayed(this, 1000)
        }
    }

    private class Row(val mark: TextView, val value: TextView)

    private fun dp(value: Float): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, resources.displayMetrics).toInt()

    private fun box(color: Int, radius: Float, strokeColor: Int = 0, strokeDp: Float = 0f) = GradientDrawable().apply {
        setColor(color)
        cornerRadius = dp(radius).toFloat()
        if (strokeDp > 0f) setStroke(dp(strokeDp), strokeColor)
    }

    private fun text(value: String, sp: Float, color: Int, bold: Boolean = false) = TextView(this).apply {
        text = value
        setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
        setTextColor(color)
        if (bold) typeface = Typeface.DEFAULT_BOLD
        textDirection = View.TEXT_DIRECTION_ANY_RTL
        includeFontPadding = false
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.decorView.layoutDirection = View.LAYOUT_DIRECTION_RTL

        val root = FrameLayout(this)
        root.background = GradientDrawable(
            GradientDrawable.Orientation.TL_BR, intArrayOf(INK, INK, Color.rgb(26, 21, 12)),
        )

        val page = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutDirection = View.LAYOUT_DIRECTION_RTL
            setPadding(dp(56f), dp(40f), dp(56f), dp(40f))
        }
        root.addView(page, FrameLayout.LayoutParams(MATCH, MATCH))

        // -- first column (right side in Arabic): who we are and the state in one sentence
        val intro = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val logo = ImageView(this).apply { setImageResource(R.mipmap.ic_launcher) }
        intro.addView(logo, LinearLayout.LayoutParams(dp(64f), dp(64f)))
        intro.addView(text("ترجِم", 30f, PAPER, bold = true), top(14f))

        val stateLine = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        lamp = View(this)
        stateLine.addView(lamp, LinearLayout.LayoutParams(dp(12f), dp(12f)).apply { marginEnd = dp(10f) })
        headline = text("", 22f, PAPER, bold = true)
        stateLine.addView(headline)
        intro.addView(stateLine, top(26f))
        detail = text("", 14f, MUTED).apply { setLineSpacing(dp(4f).toFloat(), 1f) }
        intro.addView(detail, top(8f))

        val buttons = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        startButton = button("تشغيل") { startForegroundService(Intent(this, OverlayService::class.java)) }
        stopButton = button("إيقاف") { stopService(Intent(this, OverlayService::class.java)) }
        buttons.addView(startButton, LinearLayout.LayoutParams(dp(132f), dp(46f)))
        buttons.addView(stopButton, LinearLayout.LayoutParams(dp(132f), dp(46f)).apply { marginStart = dp(12f) })
        intro.addView(buttons, top(28f))
        page.addView(intro, LinearLayout.LayoutParams(0, WRAP, 1f))

        // -- second column: the details, as a card
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = box(CARD, 20f, LINE, 1f)
            setPadding(dp(24f), dp(20f), dp(24f), dp(20f))
        }
        card.addView(text("عنوان التلفزيون", 12.5f, MUTED))
        address = text("", 24f, AMBER, bold = true).apply { textDirection = View.TEXT_DIRECTION_LTR }
        card.addView(address, top(4f))
        card.addView(text("هذا اللي تكتبه في ترجِم على اللابتوب ‹ الدليل ‹ التلفزيون", 12.5f, MUTED), top(4f))
        card.addView(View(this).apply { setBackgroundColor(LINE) }, LinearLayout.LayoutParams(MATCH, dp(1f)).apply {
            topMargin = dp(16f)
            bottomMargin = dp(6f)
        })
        rowService = row(card, "خدمة استقبال الترجمة")
        rowWindowA = row(card, "الرسم فوق الشاشة")
        rowWindowB = row(card, "نافذة احتياطية")
        page.addView(card, LinearLayout.LayoutParams(dp(380f), WRAP).apply { marginStart = dp(40f) })

        setContentView(root)
        startButton.requestFocus()
    }

    private fun top(marginDp: Float) = LinearLayout.LayoutParams(WRAP, WRAP).apply { topMargin = dp(marginDp) }

    private fun row(parent: LinearLayout, label: String): Row {
        val line = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(9f), 0, dp(9f))
        }
        val mark = text("", 13f, INK, bold = true).apply { gravity = Gravity.CENTER }
        line.addView(mark, LinearLayout.LayoutParams(dp(24f), dp(24f)).apply { marginEnd = dp(12f) })
        line.addView(text(label, 15f, PAPER), LinearLayout.LayoutParams(0, WRAP, 1f))
        val value = text("", 13f, MUTED)
        line.addView(value)
        parent.addView(line, LinearLayout.LayoutParams(MATCH, WRAP))
        return Row(mark, value)
    }

    private fun setRow(row: Row, ok: Boolean, value: String) {
        row.mark.text = if (ok) "✓" else "!"
        row.mark.background = box(if (ok) LIVE else AMBER, 12f)
        row.value.text = value
    }

    private fun button(label: String, action: () -> Unit) = text(label, 16f, PAPER, bold = true).apply {
        gravity = Gravity.CENTER
        isFocusable = true
        isFocusableInTouchMode = false
        isClickable = true
        background = box(CARD, 14f, LINE, 1f)
        setOnClickListener { action(); handler.postDelayed({ render() }, 300) }
        setOnFocusChangeListener { v, focused ->
            v.background = if (focused) box(AMBER, 14f) else box(CARD, 14f, LINE, 1f)
            (v as TextView).setTextColor(if (focused) AMBER_INK else PAPER)
            v.animate().scaleX(if (focused) 1.06f else 1f).scaleY(if (focused) 1.06f else 1f).setDuration(140).start()
        }
    }

    override fun onResume() {
        super.onResume()
        handler.post(refresh)
    }

    override fun onPause() {
        handler.removeCallbacks(refresh)
        super.onPause()
    }

    private fun render() {
        val running = OverlayService.running
        val error = OverlayService.serverError
        val canDraw = Settings.canDrawOverlays(this)
        val windowB = OverlayA11yService.connected
        val windows = OverlayHub.windowNames
        val receiving = OverlayHub.layerCount > 0 ||
            (OverlayHub.lastMessageAt > 0 && SystemClock.elapsedRealtime() - OverlayHub.lastMessageAt < 1500)

        val (title, sub, color) = when {
            error != null -> Triple("فيه مشكلة", "الخدمة ما قدرت تفتح المنفذ ${Wire.PORT}: $error", BAD)
            !running -> Triple("متوقف", "اضغط «تشغيل»، أو ابدأ الترجمة من اللابتوب وهو يشغّله لحاله.", MUTED)
            windows.isEmpty() -> Triple("ناقص إذن", "افتح ترجِم على اللابتوب ‹ الدليل ‹ «جهّز التلفزيون» مرة ثانية.", AMBER)
            receiving -> Triple("الترجمة توصل الحين", "اللابتوب متصل ويرسل الترجمة فوق اللعبة.", LIVE)
            else -> Triple("جاهز", "ارجع للعبتك، وابدأ الترجمة من ترجِم على اللابتوب أو الجوال.", LIVE)
        }
        headline.text = title
        detail.text = sub
        lamp.background = box(color, 6f)
        address.text = localIp() ?: "غير متصل بالشبكة"

        setRow(rowService, running && error == null, if (running) "شغّالة" else "واقفة")
        setRow(rowWindowA, canDraw, if (canDraw) "مسموح" else "غير مسموح")
        setRow(rowWindowB, windowB, if (windowB) "مفعّلة" else "غير مفعّلة")
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

    private companion object {
        const val MATCH = ViewGroup.LayoutParams.MATCH_PARENT
        const val WRAP = ViewGroup.LayoutParams.WRAP_CONTENT
        val INK = Color.rgb(10, 11, 15)
        val CARD = Color.rgb(17, 19, 25)
        val LINE = Color.rgb(38, 40, 50)
        val PAPER = Color.rgb(243, 241, 234)
        val MUTED = Color.rgb(142, 145, 159)
        val AMBER = Color.rgb(255, 194, 51)
        val AMBER_INK = Color.rgb(28, 20, 0)
        val LIVE = Color.rgb(55, 211, 154)
        val BAD = Color.rgb(255, 100, 112)
    }
}
