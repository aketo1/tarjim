package dev.tarjim.tv

import org.json.JSONException
import org.json.JSONObject
import java.io.DataInputStream
import java.io.EOFException
import java.io.OutputStream
import java.nio.ByteBuffer

class ProtocolException(message: String) : Exception(message)

class Frame(val header: JSONObject, val payload: ByteArray)

/** Wire protocol v1: uint32 BE json_len, uint32 BE bin_len, JSON, binary. See docs/PROTOCOL.md. */
object Wire {
    const val VERSION = 1
    const val PORT = 47800
    const val MAX_JSON_LEN = 64 * 1024
    const val MAX_BIN_LEN = 8 * 1024 * 1024
    const val MAX_LAYERS = 4
    const val MAX_LAYER_W = 1920
    const val MAX_LAYER_H = 480
    const val WATCHDOG_MS = 1000L

    /** Returns null on a clean end of stream before a new frame starts. */
    fun read(input: DataInputStream): Frame? {
        val first = input.read()
        if (first < 0) return null
        val rest = ByteArray(7)
        input.readFully(rest)
        val prefix = ByteBuffer.allocate(8).put(first.toByte()).put(rest)
        prefix.flip()
        val jsonLen = prefix.int
        val binLen = prefix.int
        if (jsonLen <= 0 || jsonLen > MAX_JSON_LEN) throw ProtocolException("bad json_len $jsonLen")
        if (binLen < 0 || binLen > MAX_BIN_LEN) throw ProtocolException("bad bin_len $binLen")
        val json = ByteArray(jsonLen)
        val payload = ByteArray(binLen)
        try {
            input.readFully(json)
            input.readFully(payload)
        } catch (e: EOFException) {
            throw ProtocolException("stream ended inside a frame")
        }
        val header = try {
            JSONObject(String(json, Charsets.UTF_8))
        } catch (e: JSONException) {
            throw ProtocolException("bad json header")
        }
        if (header.opt("type") !is String) throw ProtocolException("header needs a string 'type'")
        return Frame(header, payload)
    }

    fun write(output: OutputStream, header: JSONObject) {
        val json = header.toString().toByteArray(Charsets.UTF_8)
        val buf = ByteBuffer.allocate(8 + json.size)
        buf.putInt(json.size).putInt(0).put(json)
        output.write(buf.array())
        output.flush()
    }
}
