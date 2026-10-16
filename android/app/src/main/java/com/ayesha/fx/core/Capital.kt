package com.ayesha.fx.core

import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Adaptive capital on the phone (News spec module B). The owner types the Exness equity on the PC
 * (`ayesha capital`) and here; neither side ever sends the amount over the relay. The PC sends a keyed
 * digest (CAPH=) of its equity; the phone computes the same digest from its own setting, so a mismatch
 * (CAPITAL_MISMATCH) is visible without the amount leaving either device.
 * Same algorithm as desktop/ayesha/capital.py `digest` (shared test vectors).
 */
object Capital {
    /** The phone's own equity setting is trusted for sizing for this long after the owner confirmed it. */
    const val MAX_AGE_MS = 24 * 3_600_000L
    private const val FUTURE_SKEW_MS = 10 * 60_000L

    const val OK = "OK"
    const val MISMATCH = "CAPITAL_MISMATCH"
    const val UNVERIFIED = "CAPITAL_UNVERIFIED"
    const val STALE = "CAPITAL_STALE"

    /** HMAC-SHA256(pairing code, "capital:v1:<cents>"), first 16 hex chars. Null for a bad code or amount. */
    fun digest(code: String, equityUsd: Double): String? {
        val c = Signer.normalize(code) ?: return null
        if (!equityUsd.isFinite() || equityUsd <= 0) return null
        val cents = Math.round(equityUsd * 100)
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(c.toByteArray(), "HmacSHA256"))
        return mac.doFinal("capital:v1:$cents".toByteArray(Charsets.UTF_8))
            .joinToString("") { String.format("%02x", it.toInt() and 0xff) }.take(16)
    }

    /** True when the owner has not confirmed the phone's equity within [MAX_AGE_MS] (or never). */
    fun isStale(confirmedAtMs: Long, nowMs: Long): Boolean =
        confirmedAtMs <= 0 || nowMs - confirmedAtMs > MAX_AGE_MS || confirmedAtMs > nowMs + FUTURE_SKEW_MS

    /** PC digest vs this phone's equity: OK, CAPITAL_MISMATCH, or CAPITAL_UNVERIFIED when either side is missing. */
    fun compare(pcDigest: String, phoneDigest: String?): String = when {
        pcDigest.isBlank() || pcDigest == "NA" || phoneDigest == null -> UNVERIFIED
        pcDigest == phoneDigest -> OK
        else -> MISMATCH
    }

    /**
     * Why the phone must not size from its own equity right now, or null when it may.
     * A stale phone setting is fine for a PC alert whose digest matches it (then it equals the PC's fresh snapshot).
     */
    fun lotBlock(confirmedAtMs: Long, nowMs: Long, pcDigestMatches: Boolean): String? =
        if (isStale(confirmedAtMs, nowMs) && !pcDigestMatches)
            "$STALE: ফোনের equity ২৪ ঘণ্টার মধ্যে নিশ্চিত করা হয়নি — Exness অ্যাপ দেখে Update capital করুন"
        else null
}
