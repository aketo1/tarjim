package dev.tarjim.tv

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.Rect
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.DisplayMetrics
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.WindowManager

class Layer(
    val id: String,
    val win: Char,
    val bitmap: Bitmap,
    val dst: Rect,
    val z: Int,
    val ttlMs: Long,
    val seq: Long,
    val fadeInMs: Long,
) {
    var expiresAt = 0L
    var shownAt = 0L
    var fadeOutAt = 0L
    var fadeOutMs = 0L

    fun alphaAt(now: Long): Int {
        var a = 1f
        if (fadeInMs > 0 && now - shownAt < fadeInMs) a = (now - shownAt).toFloat() / fadeInMs
        if (fadeOutMs > 0) a *= 1f - ((now - fadeOutAt).toFloat() / fadeOutMs).coerceIn(0f, 1f)
        return (a.coerceIn(0f, 1f) * 255f).toInt()
    }

    fun animatingAt(now: Long): Boolean =
        (fadeInMs > 0 && now - shownAt < fadeInMs) || (fadeOutMs > 0 && now - fadeOutAt < fadeOutMs)
}

/** One transparent full-screen view per window; draws its layers 1:1. */
class OverlayView(context: Context, val win: Char) : View(context) {
    private val paint = Paint(Paint.FILTER_BITMAP_FLAG)
    var drawList: List<Layer> = emptyList()
    val afterDraw = ArrayList<Runnable>()

    override fun onDraw(canvas: Canvas) {
        val now = SystemClock.elapsedRealtime()
        var animating = false
        for (layer in drawList) {
            if (layer.bitmap.isRecycled) continue
            val alpha = layer.alphaAt(now)
            if (alpha > 0) {
                paint.alpha = alpha
                val d = layer.dst
                if (layer.bitmap.width == d.width() && layer.bitmap.height == d.height()) {
                    canvas.drawBitmap(layer.bitmap, d.left.toFloat(), d.top.toFloat(), paint)
                } else {
                    canvas.drawBitmap(layer.bitmap, null, d, paint)
                }
            }
            if (layer.animatingAt(now)) animating = true
        }
        if (afterDraw.isNotEmpty()) {
            val callbacks = ArrayList(afterDraw)
            afterDraw.clear()
            for (c in callbacks) c.run()
        }
        if (animating) postInvalidateOnAnimation()
    }
}

enum class ShowResult { DRAWN, NO_WINDOW, TOO_MANY_LAYERS }

/**
 * Shared by both services (same process). Layer state lives on the main
 * thread; only [lastMessageAt] and [windowNames] are touched from others.
 */
object OverlayHub {
    private const val TAG = "TarjimHub"
    private const val TICK_MS = 100L

    private val main = Handler(Looper.getMainLooper())
    private val views = HashMap<Char, OverlayView>()
    private val layers = HashMap<String, Layer>()
    private var ticking = false

    @Volatile var lastMessageAt = 0L
    @Volatile var windowNames: List<String> = emptyList()
        private set
    @Volatile var layerCount = 0
        private set

    private val tick = object : Runnable {
        override fun run() {
            val now = SystemClock.elapsedRealtime()
            if (layers.isNotEmpty()) {
                if (now - lastMessageAt > Wire.WATCHDOG_MS) {
                    Log.w(TAG, "no message for ${Wire.WATCHDOG_MS} ms: clearing")
                    clearAll()
                } else {
                    val expired = layers.values.filter { it.expiresAt <= now }
                    if (expired.isNotEmpty()) {
                        for (l in expired) layers.remove(l.id)
                        rebuild(expired)
                    }
                }
            }
            if (layers.isEmpty()) ticking = false else main.postDelayed(this, TICK_MS)
        }
    }

    fun touch() {
        lastMessageAt = SystemClock.elapsedRealtime()
    }

    // -- windows (main thread) --------------------------------------------

    fun addWindow(context: Context, wm: WindowManager, win: Char, type: Int): OverlayView? {
        views[win]?.let { return it }
        val view = OverlayView(context, win)
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
                WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
            PixelFormat.TRANSLUCENT,
        )
        params.gravity = Gravity.TOP or Gravity.START
        params.title = "tarjim-$win"
        return try {
            wm.addView(view, params)
            views[win] = view
            publishWindows()
            Log.i(TAG, "window $win added")
            view
        } catch (e: RuntimeException) {
            Log.e(TAG, "cannot add window $win", e)
            null
        }
    }

    fun removeWindow(wm: WindowManager, win: Char) {
        val view = views.remove(win) ?: return
        val gone = layers.values.filter { it.win == win }
        for (l in gone) layers.remove(l.id)
        view.drawList = emptyList()
        recycleLater(gone)
        try {
            wm.removeViewImmediate(view)
        } catch (e: RuntimeException) {
            Log.w(TAG, "removing window $win", e)
        }
        publishWindows()
        layerCount = layers.size
    }

    private fun publishWindows() {
        windowNames = views.keys.sorted().map { it.toString() }
    }

    fun displayMetrics(context: Context): DisplayMetrics {
        val metrics = DisplayMetrics()
        val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        @Suppress("DEPRECATION")
        wm.defaultDisplay.getRealMetrics(metrics)
        return metrics
    }

    // -- layers (main thread) ---------------------------------------------

    /** Applies all layers of one `show` in a single draw. */
    fun show(win: Char, incoming: List<Layer>, onDrawn: Runnable): ShowResult {
        val view = views[win]
        if (view == null) {
            recycleLater(incoming)
            return ShowResult.NO_WINDOW
        }
        val newIds = incoming.map { it.id }.toSet()
        val others = layers.values.count { it.win == win && it.id !in newIds }
        if (others + newIds.size > Wire.MAX_LAYERS) {
            recycleLater(incoming)
            return ShowResult.TOO_MANY_LAYERS
        }
        val now = SystemClock.elapsedRealtime()
        val replaced = ArrayList<Layer>()
        for (layer in incoming) {
            val current = layers[layer.id]
            if (current != null && current.seq > layer.seq) {
                replaced.add(layer) // an older seq never replaces a newer one
                continue
            }
            layer.shownAt = now
            layer.expiresAt = now + layer.ttlMs
            if (current != null) replaced.add(current)
            layers[layer.id] = layer
        }
        view.afterDraw.add(onDrawn)
        rebuild(replaced)
        startTicking()
        return ShowResult.DRAWN
    }

    fun keep(ids: List<String>) {
        val now = SystemClock.elapsedRealtime()
        for (id in ids) {
            val layer = layers[id] ?: continue
            if (layer.fadeOutMs == 0L) layer.expiresAt = now + layer.ttlMs
        }
    }

    fun clear(ids: List<String>?, fadeMs: Long) {
        val targets = if (ids == null) layers.values.toList() else ids.mapNotNull { layers[it] }
        if (targets.isEmpty()) return
        if (fadeMs <= 0) {
            for (l in targets) layers.remove(l.id)
            rebuild(targets)
            return
        }
        val now = SystemClock.elapsedRealtime()
        for (l in targets) {
            if (l.fadeOutMs == 0L) {
                l.fadeOutAt = now
                l.fadeOutMs = fadeMs
                l.expiresAt = now + fadeMs
            }
        }
        for (v in views.values) v.invalidate()
    }

    fun clearAll() {
        if (layers.isEmpty()) return
        val gone = layers.values.toList()
        layers.clear()
        rebuild(gone)
    }

    private fun rebuild(removed: List<Layer>) {
        for ((win, view) in views) {
            view.drawList = layers.values.filter { it.win == win }.sortedWith(compareBy({ it.z }, { it.id }))
            view.invalidate()
        }
        layerCount = layers.size
        recycleLater(removed)
    }

    /** Recycle after the next frames are out, so no pending draw still uses the bitmap. */
    private fun recycleLater(gone: List<Layer>) {
        if (gone.isEmpty()) return
        main.postDelayed({ for (l in gone) if (!l.bitmap.isRecycled) l.bitmap.recycle() }, 500)
    }

    private fun startTicking() {
        if (!ticking) {
            ticking = true
            main.postDelayed(tick, TICK_MS)
        }
    }

    fun runOnMain(block: Runnable) {
        main.post(block)
    }
}
