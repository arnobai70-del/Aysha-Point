package com.ayesha.fx.core

/**
 * The PC's one combined multi-timeframe explanation (MTF= key), e.g.
 * "H4:UP,H1:UP,H1L:BOS_UP,Z:DISCOUNT,M15:PDL_SWEEP>CHOCH>FVG,M5:OFF".
 * Higher timeframes are context for ONE setup; they never produce their own signals.
 */
object Mtf {
    fun parse(s: String?): Map<String, String> {
        if (s.isNullOrBlank() || s == "NA") return emptyMap()
        return s.split(',').mapNotNull { part ->
            val i = part.indexOf(':')
            if (i <= 0 || i == part.length - 1) null else part.substring(0, i) to part.substring(i + 1)
        }.toMap()
    }

    fun encode(m: Map<String, String>): String = m.entries.joinToString(",") { "${it.key}:${it.value}" }

    private fun trend(v: String?): String = when (v) {
        "UP" -> "ঊর্ধ্বমুখী (UP)"
        "DOWN" -> "নিম্নমুখী (DOWN)"
        "RANGE" -> "সাইডওয়ে (স্পষ্ট দিক নেই)"
        "OFF" -> "বন্ধ"
        null, "" -> "জানা নেই"
        else -> v
    }

    /** +1 when this timeframe points the same way as the trade, -1 against, 0 neutral/unknown. */
    fun align(v: String?, buy: Boolean): Int = when (v) {
        "UP" -> if (buy) 1 else -1
        "DOWN" -> if (buy) -1 else 1
        else -> 0
    }

    /** Short Bangla lines for the detail screen and the notification. Empty when the sender gave no MTF. */
    fun explain(m: Map<String, String>, buy: Boolean): List<String> {
        if (m.isEmpty()) return emptyList()
        val out = mutableListOf<String>()
        fun mark(v: String?) = when (align(v, buy)) { 1 -> "✅"; -1 -> "⚠️"; else -> "➖" }
        m["H4"]?.let { out.add("${mark(it)} H4 (বড় ছবি): ${trend(it)}") }
        m["H1"]?.let { h1 ->
            val last = m["H1L"]?.takeIf { it != "NONE" }?.let { " · শেষ ব্রেক ${it.replace('_', ' ')}" } ?: ""
            out.add("${mark(h1)} H1 bias: ${trend(h1)}$last")
        }
        m["Z"]?.let { z ->
            val good = (z == "DISCOUNT" && buy) || (z == "PREMIUM" && !buy)
            val txt = when (z) {
                "DISCOUNT" -> "entry H1 রেঞ্জের নিচের অর্ধেকে (discount)"
                "PREMIUM" -> "entry H1 রেঞ্জের উপরের অর্ধেকে (premium)"
                "OUTSIDE_RANGE" -> "entry H1 রেঞ্জের বাইরে"
                else -> "H1 রেঞ্জ জানা নেই"
            }
            out.add((if (good) "✅ " else "➖ ") + txt)
        }
        m["M15"]?.let { out.add("✅ M15 setup: " + it.replace("_SWEEP", " sweep").replace(">", " → ")) }
        m["M5"]?.let {
            out.add(when (it) {
                "OFF" -> "➖ M5 confirmation: বন্ধ (M15-এর FVG limit entry)"
                "PENDING" -> "⏳ M5 confirmation-এর অপেক্ষা: দাম zone-এ এসে M5 candle শক্তভাবে ঘুরলে তবেই READY"
                "CONFIRMED_UP", "CONFIRMED_DOWN" -> "✅ M5 confirmation হয়েছে: entry এখনকার দামের কাছে (market), কয়েক মিনিটের জন্য"
                "FAILED" -> "❌ M5 confirmation হয়নি: setup বাতিল"
                else -> "M5: $it"
            })
        }
        return out
    }

    /** "H4 ✅ · H1 ✅ · Z discount" style one-liner for notifications. */
    fun summary(m: Map<String, String>, buy: Boolean): String {
        if (m.isEmpty()) return ""
        fun s(k: String) = when (align(m[k], buy)) { 1 -> "✅"; -1 -> "⚠️"; else -> "➖" }
        val parts = mutableListOf<String>()
        if ("H4" in m) parts.add("H4 ${s("H4")}")
        if ("H1" in m) parts.add("H1 ${s("H1")}")
        m["Z"]?.let { parts.add(it.lowercase()) }
        m["M5"]?.takeIf { it != "OFF" }?.let { parts.add("M5 ${it.lowercase()}") }
        return parts.joinToString(" · ")
    }
}

/**
 * Which PC status updates may replace a stored one (same signal id). Anything else is a replay and is ignored.
 * WATCH -> READY (M5 confirmed) or NO_TRADE; READY -> NO_TRADE (INVALIDATED before entry, e.g. a new news
 * lockout). A block is never lifted: NO_TRADE never becomes READY again.
 */
object Transitions {
    fun allowed(old: String, new: String): Boolean =
        (old == "WATCH" && (new == "READY" || new == "NO_TRADE")) || (old == "READY" && new == "NO_TRADE")
}

/** PC link freshness judged by the PC's own heartbeat time, so a replayed old heartbeat cannot look "online". */
object LinkHealth {
    const val OFFLINE_AFTER_MS = 12 * 60_000L
    const val MAX_FUTURE_SKEW_MS = 10 * 60_000L

    const val NONE = "NONE"
    const val ONLINE = "ONLINE"
    const val OFFLINE = "OFFLINE"
    const val STOPPED = "STOPPED"
    const val DATA_PROBLEM = "DATA_PROBLEM"
    const val TEST = "TEST"

    /** Accept only heartbeats newer than the last one and not from the future. */
    fun accept(hb: Heartbeat, lastPcMs: Long, nowMs: Long): Boolean =
        hb.pcTimeMs > lastPcMs && hb.pcTimeMs <= nowMs + MAX_FUTURE_SKEW_MS

    fun status(lastPcMs: Long, state: String, nowMs: Long): String = when {
        lastPcMs <= 0L -> NONE
        state == "STOPPED" -> STOPPED
        nowMs - lastPcMs > OFFLINE_AFTER_MS -> OFFLINE
        state == "OK" -> ONLINE
        state == "TEST" -> TEST
        else -> DATA_PROBLEM
    }
}
