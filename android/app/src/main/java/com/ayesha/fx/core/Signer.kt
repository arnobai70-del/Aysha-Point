package com.ayesha.fx.core

import java.security.MessageDigest
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Pairing code, relay topic and message signatures. Same algorithm as desktop/ayesha/delivery/push.py
 * (a shared test vector keeps them in step): HMAC-SHA256(code, body), first 32 hex chars.
 */
object Signer {
    private const val ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

    /** Upper-case, dashes removed; null if it is not a valid 16-character code. */
    fun normalize(code: String): String? {
        val c = code.uppercase().filter { it.isLetterOrDigit() }
        return if (c.length == 16 && c.all { it in ALPHABET }) c else null
    }

    private fun hex(b: ByteArray) = b.joinToString("") { String.format("%02x", it.toInt() and 0xff) }

    fun topic(code: String): String? {
        val c = normalize(code) ?: return null
        return "ayesha-" + hex(MessageDigest.getInstance("SHA-256").digest(("topic:$c").toByteArray())).take(24)
    }

    fun sign(code: String, body: String): String? {
        val c = normalize(code) ?: return null
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(c.toByteArray(), "HmacSHA256"))
        return hex(mac.doFinal(body.toByteArray(Charsets.UTF_8))).take(32)
    }

    /** Returns the signed body when the trailing "SIG=" line is valid for this code, else null. */
    fun verify(code: String, message: String): String? {
        val i = message.lastIndexOf("\nSIG=")
        if (i < 0) return null
        val body = message.substring(0, i)
        val sig = message.substring(i + 5).trim()
        val want = sign(code, body) ?: return null
        return if (MessageDigest.isEqual(want.toByteArray(), sig.toByteArray())) body else null
    }
}

/** "AYESHA HB T=<ms> STATE=OK PAIRS=5 V=<hash>": the PC scanner says it is alive and whether its data is fresh. */
data class Heartbeat(val pcTimeMs: Long, val state: String, val pairs: Int, val version: String) {
    companion object {
        private val re = Regex("""^AYESHA HB T=(\d+) STATE=([A-Z_]+) PAIRS=(\d+) V=(\S+)""")

        fun parse(body: String): Heartbeat? {
            val m = re.find(body.trim()) ?: return null
            return Heartbeat(m.groupValues[1].toLong(), m.groupValues[2], m.groupValues[3].toInt(), m.groupValues[4])
        }
    }
}
