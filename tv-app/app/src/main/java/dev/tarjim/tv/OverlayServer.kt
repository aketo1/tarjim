package dev.tarjim.tv

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Rect
import android.os.Build
import android.os.SystemClock
import android.util.Log
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.BufferedInputStream
import java.io.DataInputStream
import java.io.IOException
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException

/** TCP server for protocol v1. One client at a time; a new connection replaces the old one. */
class OverlayServer(private val context: Context) {
    private val tag = "TarjimServer"
    @Volatile private var serverSocket: ServerSocket? = null
    @Volatile private var current: Connection? = null
    @Volatile var clientAddress: String? = null
        private set

    fun start() {
        if (serverSocket != null) return
        val socket = ServerSocket()
        socket.reuseAddress = true
        socket.bind(InetSocketAddress(Wire.PORT))
        serverSocket = socket
        Thread({ acceptLoop(socket) }, "tarjim-accept").start()
    }

    fun stop() {
        try {
            serverSocket?.close()
        } catch (e: IOException) {
            Log.w(tag, "closing server socket", e)
        }
        serverSocket = null
        current?.close()
    }

    private fun acceptLoop(server: ServerSocket) {
        while (!server.isClosed) {
            val socket = try {
                server.accept()
            } catch (e: IOException) {
                break
            }
            current?.close()
            val conn = Connection(socket)
            current = conn
            clientAddress = socket.inetAddress?.hostAddress
            OverlayHub.runOnMain { OverlayHub.clearAll() }
            Thread({ conn.readLoop() }, "tarjim-conn").start()
        }
    }

    private inner class Connection(private val socket: Socket) {
        private val writer: ExecutorService = Executors.newSingleThreadExecutor()
        private val decoder: ExecutorService = Executors.newSingleThreadExecutor()
        private val newestSeq = ConcurrentHashMap<String, Long>()
        @Volatile private var closed = false

        fun readLoop() {
            try {
                socket.tcpNoDelay = true
                val input = DataInputStream(BufferedInputStream(socket.getInputStream(), 256 * 1024))
                while (!closed) {
                    val frame = Wire.read(input) ?: break
                    OverlayHub.touch()
                    handle(frame)
                }
            } catch (e: ProtocolException) {
                Log.w(tag, "protocol error, closing: ${e.message}")
            } catch (e: JSONException) {
                Log.w(tag, "bad message, closing: ${e.message}")
            } catch (e: IOException) {
                Log.i(tag, "connection ended: ${e.message}")
            } catch (e: RuntimeException) {
                Log.e(tag, "unexpected error, closing connection", e)
            } finally {
                close()
            }
        }

        fun close() {
            if (closed) return
            closed = true
            try {
                socket.close()
            } catch (e: IOException) {
                Log.w(tag, "closing socket", e)
            }
            writer.shutdownNow()
            decoder.shutdownNow()
            if (current === this) {
                current = null
                clientAddress = null
                OverlayHub.runOnMain { OverlayHub.clearAll() }
            }
        }

        private fun send(header: JSONObject) {
            try {
                writer.execute {
                    try {
                        Wire.write(socket.getOutputStream(), header)
                    } catch (e: IOException) {
                        close()
                    }
                }
            } catch (e: RejectedExecutionException) {
                // connection already closed
            }
        }

        private fun handle(frame: Frame) {
            val h = frame.header
            when (h.getString("type")) {
                "hello" -> {
                    if (h.optInt("v", -1) != Wire.VERSION) throw ProtocolException("unsupported version")
                    val m = OverlayHub.displayMetrics(context)
                    send(
                        JSONObject()
                            .put("type", "hello_ack")
                            .put("v", Wire.VERSION)
                            .put("w", m.widthPixels)
                            .put("h", m.heightPixels)
                            .put("density", m.densityDpi)
                            .put("sdk", Build.VERSION.SDK_INT)
                            .put("model", Build.MODEL)
                            .put("windows", JSONArray(OverlayHub.windowNames)),
                    )
                }
                "ping" -> send(
                    JSONObject()
                        .put("type", "pong")
                        .put("ts", h.opt("ts"))
                        .put("tv_ts", SystemClock.elapsedRealtime()),
                )
                "show" -> handleShow(h, frame.payload)
                "keep" -> {
                    val ids = stringList(h.getJSONArray("ids"))
                    OverlayHub.runOnMain { OverlayHub.keep(ids) }
                }
                "clear" -> {
                    val ids = if (h.optBoolean("all", false)) null else stringList(h.getJSONArray("ids"))
                    val fade = h.optLong("fade_ms", 0L)
                    OverlayHub.runOnMain { OverlayHub.clear(ids, fade) }
                }
                else -> throw ProtocolException("unknown message type")
            }
        }

        private inner class Entry(
            val id: String, val z: Int, val x: Int, val y: Int, val w: Int, val h: Int,
            val ttlMs: Long, val fadeMs: Long, val offset: Int, val len: Int,
        )

        private fun handleShow(h: JSONObject, payload: ByteArray) {
            val tRecv = SystemClock.elapsedRealtime()
            val seq = h.getLong("seq")
            val winName = h.getString("win")
            if (winName != "A" && winName != "B") throw ProtocolException("bad window")
            val win = winName[0]
            val array = h.getJSONArray("layers")
            if (array.length() < 1 || array.length() > Wire.MAX_LAYERS) throw ProtocolException("bad layer count")
            val entries = ArrayList<Entry>()
            for (i in 0 until array.length()) {
                val o = array.getJSONObject(i)
                val e = Entry(
                    o.getString("id"), o.getInt("z"), o.getInt("x"), o.getInt("y"), o.getInt("w"), o.getInt("h"),
                    o.getLong("ttl_ms"), o.optLong("fade_ms", 0L), o.getInt("offset"), o.getInt("len"),
                )
                if (e.id.isEmpty()) throw ProtocolException("empty layer id")
                if (e.w < 1 || e.w > Wire.MAX_LAYER_W || e.h < 1 || e.h > Wire.MAX_LAYER_H) {
                    throw ProtocolException("layer size out of range")
                }
                if (e.ttlMs <= 0 || e.offset < 0 || e.len <= 0 || e.offset.toLong() + e.len > payload.size) {
                    throw ProtocolException("layer bytes outside the payload")
                }
                entries.add(e)
                newestSeq.merge(e.id, seq) { a, b -> maxOf(a, b) }
            }
            try {
                decoder.execute { decodeAndShow(seq, win, entries, payload, tRecv) }
            } catch (e: RejectedExecutionException) {
                // connection already closed
            }
        }

        /** Runs off the UI thread. A layer is skipped when a newer seq for it is already waiting. */
        private fun decodeAndShow(seq: Long, win: Char, entries: List<Entry>, payload: ByteArray, tRecv: Long) {
            val layers = ArrayList<Layer>()
            val options = BitmapFactory.Options()
            options.inPreferredConfig = Bitmap.Config.ARGB_8888
            for (e in entries) {
                if ((newestSeq[e.id] ?: seq) > seq) continue
                val bitmap = try {
                    BitmapFactory.decodeByteArray(payload, e.offset, e.len, options)
                } catch (oom: OutOfMemoryError) {
                    null
                }
                if (bitmap == null || bitmap.width != e.w || bitmap.height != e.h) {
                    bitmap?.recycle()
                    for (l in layers) l.bitmap.recycle()
                    Log.w(tag, "layer ${e.id}: image does not decode to ${e.w}x${e.h}, closing")
                    close()
                    return
                }
                layers.add(Layer(e.id, win, bitmap, Rect(e.x, e.y, e.x + e.w, e.y + e.h), e.z, e.ttlMs, seq, e.fadeMs))
            }
            val tDecoded = SystemClock.elapsedRealtime()
            val ack = JSONObject().put("type", "ack").put("seq", seq).put("t_recv", tRecv).put("t_decoded", tDecoded)
            if (layers.isEmpty()) {
                send(ack.put("t_drawn", JSONObject.NULL).put("status", "superseded"))
                return
            }
            OverlayHub.runOnMain {
                if (closed) {
                    for (l in layers) l.bitmap.recycle()
                    return@runOnMain
                }
                val result = OverlayHub.show(win, layers) {
                    send(ack.put("t_drawn", SystemClock.elapsedRealtime()).put("status", "drawn"))
                }
                when (result) {
                    ShowResult.DRAWN -> Unit
                    ShowResult.NO_WINDOW -> send(ack.put("t_drawn", JSONObject.NULL).put("status", "no_window"))
                    ShowResult.TOO_MANY_LAYERS -> {
                        Log.w(tag, "more than ${Wire.MAX_LAYERS} layers in window $win, closing")
                        close()
                    }
                }
            }
        }

        private fun stringList(array: JSONArray): List<String> {
            val out = ArrayList<String>(array.length())
            for (i in 0 until array.length()) {
                val v = array.get(i)
                if (v !is String) throw ProtocolException("ids must be strings")
                out.add(v)
            }
            return out
        }
    }
}
