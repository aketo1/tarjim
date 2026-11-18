package dev.tarjim.tv

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.Settings
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
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
 * receive subtitles, what its address is, which device is sending, and Start / Stop / Try for
 * the remote's D-pad. The same graphite and white look as the laptop and phone apps, sized to
 * be read from the sofa. Built in code with framework views only (the app has no libraries).
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
    private lateinit var rowSender: Row
    private lateinit var startButton: TextView
    private var testUntil = 0L
    private var testSeq = 0L

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
        root.background = GradientDrawable(GradientDrawable.Orientation.TL_BR, intArrayOf(INK, INK, INK_2))
        // a soft white glow behind the title, like the apps' glass
        val glow = View(this).apply {
            background = GradientDrawable().apply {
                gradientType = GradientDrawable.RADIAL_GRADIENT
                gradientRadius = dp(420f).toFloat()
                colors = intArrayOf(Color.argb(30, 255, 255, 255), Color.TRANSPARENT)
            }
        }
        root.addView(glow, FrameLayout.LayoutParams(dp(840f), dp(840f), Gravity.TOP or Gravity.END).apply {
            topMargin = -dp(300f)
            marginEnd = -dp(200f)
        })

        val page = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutDirection = View.LAYOUT_DIRECTION_RTL
            setPadding(dp(48f), dp(34f), dp(48f), dp(34f))  // the TV is 960 x 540 dp
        }
        root.addView(page, FrameLayout.LayoutParams(MATCH, MATCH))

        // -- first column (right side in Arabic): who we are and the state in one sentence
        val intro = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val brand = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val logo = ImageView(this).apply { setImageResource(R.mipmap.ic_launcher) }
        brand.addView(logo, LinearLayout.LayoutParams(dp(72f), dp(72f)).apply { marginEnd = dp(18f) })
        brand.addView(text("ترجِم", 44f, PAPER, bold = true))
        intro.addView(brand)
        intro.addView(text("ترجمة عربية فوق ألعابك، على نفس التلفزيون", 18f, MUTED), top(10f))

        val stateLine = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        lamp = View(this)
        stateLine.addView(lamp, LinearLayout.LayoutParams(dp(14f), dp(14f)).apply { marginEnd = dp(12f) })
        headline = text("", 30f, PAPER, bold = true)
        stateLine.addView(headline)
        intro.addView(stateLine, top(34f))
        detail = text("", 18f, MUTED).apply { setLineSpacing(dp(6f).toFloat(), 1f) }
        intro.addView(detail, LinearLayout.LayoutParams(MATCH, WRAP).apply { topMargin = dp(10f) })

        // two rows of two: the column is about 450 dp wide on a 960 dp TV
        val rowOne = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        startButton = button("تشغيل") { startForegroundService(Intent(this, OverlayService::class.java)) }
        val stopButton = button("إيقاف") { stopService(Intent(this, OverlayService::class.java)) }
        rowOne.addView(startButton, LinearLayout.LayoutParams(dp(170f), dp(50f)))
        rowOne.addView(stopButton, LinearLayout.LayoutParams(dp(170f), dp(50f)).apply { marginStart = dp(12f) })
        intro.addView(rowOne, top(26f))
        val rowTwo = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val tryButton = button("جرّب سطر") { showTestLine() }
        val settingsButton = button("الإعدادات") { openTvSettings() }
        rowTwo.addView(tryButton, LinearLayout.LayoutParams(dp(170f), dp(50f)))
        rowTwo.addView(settingsButton, LinearLayout.LayoutParams(dp(170f), dp(50f)).apply { marginStart = dp(12f) })
        intro.addView(rowTwo, top(12f))
        page.addView(intro, LinearLayout.LayoutParams(0, WRAP, 1f))

        // -- second column: the details, as a glass card
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = box(GLASS, 28f, LINE, 1f)
            setPadding(dp(30f), dp(26f), dp(30f), dp(22f))
        }
        card.addView(text("عنوان التلفزيون", 15f, MUTED))
        address = text("", 34f, PAPER, bold = true).apply { textDirection = View.TEXT_DIRECTION_LTR }
        card.addView(address, top(6f))
        card.addView(text("اكتبه في ترجِم على اللابتوب أو الجوال (الإعداد ‹ التلفزيون)", 15f, MUTED).apply {
            setLineSpacing(dp(3f).toFloat(), 1f)
        }, top(6f))
        card.addView(View(this).apply { setBackgroundColor(LINE) }, LinearLayout.LayoutParams(MATCH, dp(1f)).apply {
            topMargin = dp(18f)
            bottomMargin = dp(6f)
        })
        rowService = row(card, "استقبال الترجمة")
        rowWindowA = row(card, "الرسم فوق الشاشة")
        rowWindowB = row(card, "النافذة الاحتياطية")
        rowSender = row(card, "الجهاز المتصل")
        page.addView(card, LinearLayout.LayoutParams(dp(380f), WRAP).apply { marginStart = dp(36f) })

        val version = try { packageManager.getPackageInfo(packageName, 0).versionName } catch (e: Exception) { null }
        root.addView(text("الإصدار ${version ?: "?"}", 13f, FAINT), FrameLayout.LayoutParams(WRAP, WRAP, Gravity.BOTTOM or Gravity.START).apply {
            marginStart = dp(48f)
            bottomMargin = dp(16f)
        })

        setContentView(root)
        startButton.requestFocus()
    }

    private fun top(marginDp: Float) = LinearLayout.LayoutParams(WRAP, WRAP).apply { topMargin = dp(marginDp) }

    private fun row(parent: LinearLayout, label: String): Row {
        val line = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(11f), 0, dp(11f))
        }
        val mark = text("", 14f, INK, bold = true).apply { gravity = Gravity.CENTER }
        line.addView(mark, LinearLayout.LayoutParams(dp(28f), dp(28f)).apply { marginEnd = dp(14f) })
        line.addView(text(label, 18f, PAPER), LinearLayout.LayoutParams(0, WRAP, 1f))
        val value = text("", 16f, MUTED)
        line.addView(value)
        parent.addView(line, LinearLayout.LayoutParams(MATCH, WRAP))
        return Row(mark, value)
    }

    private fun setRow(row: Row, ok: Boolean, value: String, neutral: Boolean = false) {
        row.mark.text = if (ok) "✓" else if (neutral) "–" else "!"
        row.mark.background = box(if (ok) LIVE else if (neutral) FAINT else WARN, 14f)
        row.value.text = value
    }

    private fun button(label: String, action: () -> Unit) = text(label, 19f, PAPER, bold = true).apply {
        gravity = Gravity.CENTER
        isFocusable = true
        isFocusableInTouchMode = false
        isClickable = true
        background = box(GLASS_2, 999f, LINE, 1f)
        setOnClickListener { action(); handler.postDelayed({ render() }, 300) }
        setOnFocusChangeListener { v, focused ->
            // the apps' primary button: white with dark text
            v.background = if (focused) box(PAPER, 999f) else box(GLASS_2, 999f, LINE, 1f)
            (v as TextView).setTextColor(if (focused) INK else PAPER)
            v.animate().scaleX(if (focused) 1.06f else 1f).scaleY(if (focused) 1.06f else 1f).setDuration(140).start()
        }
    }

    /** The TV's accessibility settings, where the second window is switched on without a laptop. */
    private fun openTvSettings() {
        for (action in listOf(Settings.ACTION_ACCESSIBILITY_SETTINGS, Settings.ACTION_SETTINGS)) {
            try {
                startActivity(Intent(action).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                return
            } catch (e: Exception) {
                continue  // this TV has no such screen: try the next
            }
        }
        detail.text = "ما قدرت أفتح الإعدادات من هنا. افتحها من قائمة التلفزيون ‹ إمكانية الوصول."
    }

    /**
     * A sample Arabic line over the picture for a few seconds, drawn by the same windows the
     * laptop and the phone use: shows that drawing works without starting a game. It keeps the
     * watchdog fed only while it lasts, so it can never stay on the screen.
     */
    private fun showTestLine() {
        val windows = OverlayHub.windowNames
        if (!OverlayService.running || windows.isEmpty()) {
            detail.text = "شغّل الخدمة أول (زر «تشغيل»)، بعدين جرّب."
            return
        }
        val dm = resources.displayMetrics
        val sw = maxOf(dm.widthPixels, dm.heightPixels)
        val sh = minOf(dm.widthPixels, dm.heightPixels)
        val bitmap = sampleBitmap("هذا سطر تجربة: الترجمة العربية تطلع هنا فوق اللعبة", sh)
        val left = (sw - bitmap.width) / 2
        val topY = sh - bitmap.height - (sh * 0.08f).toInt()
        val win = windows.first()[0]
        val layer = Layer("tv-test", win, bitmap, Rect(left, topY, left + bitmap.width, topY + bitmap.height),
            z = 9, ttlMs = TEST_MS, seq = ++testSeq, fadeInMs = 180)
        testUntil = SystemClock.elapsedRealtime() + TEST_MS
        OverlayHub.touch()
        OverlayHub.show(win, listOf(layer), Runnable { })
        val feed = object : Runnable {
            override fun run() {
                if (SystemClock.elapsedRealtime() < testUntil) {
                    OverlayHub.touch()
                    handler.postDelayed(this, 300)
                }
            }
        }
        handler.post(feed)
    }

    private fun sampleBitmap(line: String, screenH: Int): Bitmap {
        val paint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            textSize = screenH * 0.045f
            typeface = Typeface.DEFAULT_BOLD
        }
        val textW = paint.measureText(line).toInt() + 2
        val layout = StaticLayout.Builder.obtain(line, 0, line.length, paint, textW)
            .setAlignment(Layout.Alignment.ALIGN_CENTER)
            .setTextDirection(android.text.TextDirectionHeuristics.RTL)
            .setIncludePad(false)
            .build()
        val padX = (screenH * 0.03f).toInt()
        val padY = (screenH * 0.016f).toInt()
        val bmp = Bitmap.createBitmap(textW + 2 * padX, layout.height + 2 * padY, Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp)
        val plate = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(190, 11, 11, 13) }
        val r = bmp.height * 0.3f
        c.drawRoundRect(RectF(0f, 0f, bmp.width.toFloat(), bmp.height.toFloat()), r, r, plate)
        c.save()
        c.translate(padX.toFloat(), padY.toFloat())
        layout.draw(c)
        c.restore()
        return bmp
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
        val sender = OverlayServer.connectedFrom
        val receiving = OverlayHub.layerCount > 0 ||
            (OverlayHub.lastMessageAt > 0 && SystemClock.elapsedRealtime() - OverlayHub.lastMessageAt < 1500)

        val (title, sub, color) = when {
            error != null -> Triple("فيه مشكلة", "ما قدرت أفتح المنفذ ${Wire.PORT}: $error", BAD)
            !running -> Triple("متوقف", "اضغط «تشغيل»، أو ابدأ الترجمة من ترجِم على اللابتوب أو الجوال وهو يشغّله لحاله.", MUTED)
            windows.isEmpty() -> Triple("ناقص إذن", "اضغط «الإعدادات» وفعّل ترجِم من إمكانية الوصول، أو جهّز التلفزيون من ترجِم على اللابتوب.", WARN)
            receiving && sender != null -> Triple("الترجمة توصل الحين", "الجهاز $sender يرسل الترجمة فوق اللعبة.", LIVE)
            sender != null -> Triple("متصل وجاهز", "الجهاز $sender متصل. أول ما يطلع حوار في اللعبة، العربي يطلع هنا.", LIVE)
            else -> Triple("جاهز", "ارجع للعبتك، وابدأ الترجمة من ترجِم على اللابتوب أو الجوال. وتقدر تجرّب بزر «جرّب سطر».", LIVE)
        }
        if (SystemClock.elapsedRealtime() >= testUntil) {
            headline.text = title
            detail.text = sub
        } else {
            headline.text = "تجربة"
            detail.text = "شوف تحت: هذا شكل الترجمة فوق الصورة. يختفي لحاله بعد ثواني."
        }
        lamp.background = box(color, 7f)
        address.text = localIp() ?: "غير متصل بالشبكة"

        setRow(rowService, running && error == null, if (running) "شغّال" else "واقف")
        setRow(rowWindowA, canDraw, if (canDraw) "مسموح" else "غير مسموح")
        setRow(rowWindowB, windowB, if (windowB) "مفعّلة" else "غير مفعّلة")
        setRow(rowSender, sender != null, sender ?: "ولا جهاز", neutral = sender == null)
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
        const val TEST_MS = 4000L
        // the apps' graphite and white
        val INK = Color.rgb(11, 11, 13)
        val INK_2 = Color.rgb(24, 24, 28)
        val GLASS = Color.argb(20, 255, 255, 255)
        val GLASS_2 = Color.argb(28, 255, 255, 255)
        val LINE = Color.argb(40, 255, 255, 255)
        val PAPER = Color.rgb(244, 244, 245)
        val MUTED = Color.rgb(161, 161, 170)
        val FAINT = Color.rgb(113, 113, 122)
        val LIVE = Color.rgb(55, 211, 154)
        val WARN = Color.rgb(251, 191, 36)
        val BAD = Color.rgb(255, 100, 112)
    }
}
