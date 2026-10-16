package com.ayesha.fx.core

/**
 * Signed "News Watch" messages from the PC scanner: information and protection status only, never a
 * trade signal. Same format as desktop/ayesha/delivery/push.py `format_news`;
 * contracts/fixtures/pc-news-lockout.txt is the shared test vector.
 *
 *   AYESHA NEWS ID=<event> CCY=USD IMP=HIGH TIER=TOP_DATA T=<ms> PH=<phase> ST=<event state> WS=<ms> WE=<ms>
 *     SRC=<provider> VER=<ms> PAIRS=EURUSD,USDJPY SENT=<ms> RX=<reaction> SET=Y|N|NA V=<hash>
 *   Title: ... / Forecast: ... / Scenario: ... / Reaction: ... / Protection: ...
 */
data class NewsNotice(
    val eventId: String,
    val currency: String,
    val impact: String,
    val tier: String,
    val eventMs: Long,
    val phase: String,          // UPCOMING | PRE_EVENT_LOCKOUT | RELEASED | WINDOW_END
    val eventState: String,     // SCHEDULED | RESCHEDULED | CANCELLED_OR_MOVED | CORRECTED | CONFLICT
    val windowStartMs: Long,
    val windowEndMs: Long,
    val provider: String,
    val verifiedMs: Long?,
    val pairs: List<String>,
    val sentMs: Long,
    val reactionState: String,  // NA | UNAVAILABLE | CONFIRMS | CONFLICTS | WHIPSAW | OBSERVED_ONLY | UNCLEAR
    val settled: String,        // Y | N | NA: market settled after the window (closed M5 bars)
    val version: String,
    val title: String,
    val forecast: String,
    val scenario: String,
    val reaction: String,
    val receivedAtMs: Long,
    val raw: String,
) {
    /** One stored notice per event and phase. */
    val key: String get() = "$eventId|$phase"
    val category: String get() = News.category(phase)
}

object News {
    /** Separate categories (News spec A4): an alert, a protection notice, a post-news summary. */
    const val ALERT = "NEWS_ALERT"
    const val PROTECTION = "NEWS_PROTECTION"
    const val REACTION = "NEWS_REACTION"

    val PHASES = setOf("UPCOMING", "PRE_EVENT_LOCKOUT", "RELEASED", "WINDOW_END")

    /** After the window the phone keeps blocking this long unless the PC said the market settled. */
    const val POST_WINDOW_MS = 30 * 60_000L

    private val head = Regex("""^AYESHA NEWS ([^\n]*)""")
    private val kv = Regex("""([A-Z]+)=(\S+)""")
    private val idRe = Regex("""[A-Za-z0-9._~-]{4,40}""")
    private val pairRe = Regex("""[A-Z]{6}""")

    fun category(phase: String): String = when (phase) {
        "UPCOMING" -> ALERT
        "WINDOW_END" -> REACTION
        else -> PROTECTION
    }

    /** Parse a verified body. Null for anything malformed or from the future. */
    fun parse(body: String, receivedAtMs: Long): NewsNotice? {
        val lines = body.trim().lines()
        val m = head.find(lines.firstOrNull() ?: return null) ?: return null
        val k = kv.findAll(m.groupValues[1]).associate { it.groupValues[1] to it.groupValues[2] }
        fun ms(key: String): Long? = k[key]?.toLongOrNull()?.takeIf { it > 0 }
        val phase = k["PH"]?.takeIf { it in PHASES } ?: return null
        val id = k["ID"]?.takeIf { idRe.matches(it) } ?: return null
        val t = ms("T") ?: return null
        val ws = ms("WS") ?: return null
        val we = ms("WE") ?: return null
        if (ws > t || t > we) return null
        val sent = ms("SENT") ?: return null
        if (sent > receivedAtMs + AlertParser.MAX_CLOCK_SKEW_MS) return null
        val pairs = k["PAIRS"]?.split(',')?.map { it.uppercase() }?.filter { pairRe.matches(it) }.orEmpty()
        if (pairs.isEmpty()) return null
        fun line(prefix: String): String =
            lines.drop(1).firstOrNull { it.startsWith(prefix) }?.removePrefix(prefix)?.trim().orEmpty()
        return NewsNotice(
            eventId = id,
            currency = k["CCY"] ?: "",
            impact = k["IMP"] ?: "",
            tier = k["TIER"] ?: "",
            eventMs = t,
            phase = phase,
            eventState = k["ST"] ?: "SCHEDULED",
            windowStartMs = ws,
            windowEndMs = we,
            provider = k["SRC"] ?: "",
            verifiedMs = ms("VER"),
            pairs = pairs,
            sentMs = sent,
            reactionState = k["RX"] ?: "NA",
            settled = k["SET"] ?: "NA",
            version = k["V"] ?: "",
            title = line("Title:"),
            forecast = line("Forecast:"),
            scenario = line("Scenario:"),
            reaction = line("Reaction:"),
            receivedAtMs = receivedAtMs,
            raw = body,
        )
    }

    /**
     * A PC news window that blocks a new entry on this pair at any time in [nowMs, untilMs): the window
     * itself, then [POST_WINDOW_MS] more unless a post-news summary said the market settled.
     * Returns the notice that blocks, or null.
     */
    fun block(notices: List<NewsNotice>, ticker: String, nowMs: Long, untilMs: Long = nowMs + 1): NewsNotice? {
        val settled = notices.filter { it.phase == "WINDOW_END" && it.settled == "Y" }.map { it.eventId }.toSet()
        return notices.filter { ticker.uppercase() in it.pairs }
            .filter { n ->
                val end = if (n.eventId in settled) n.windowEndMs else n.windowEndMs + POST_WINDOW_MS
                n.windowStartMs < untilMs && nowMs < end
            }
            .minByOrNull { it.windowStartMs }
    }

    /** Bangla reason for a block, used in the assessment. */
    fun blockReason(n: NewsNotice, nowMs: Long): String = when {
        nowMs < n.windowStartMs -> "NEWS_LOCKOUT_BEFORE_EXPIRY: ${n.currency} ${n.title} — লকআউট শুরু হবে setup-এর মেয়াদ শেষের আগেই"
        nowMs < n.windowEndMs -> "NEWS_LOCKOUT: ${n.currency} ${n.title} — নিউজের সময় নতুন ট্রেড বন্ধ"
        else -> "POST_NEWS_NOT_CONFIRMED: ${n.currency} ${n.title} — নিউজের পরে বাজার শান্ত হয়েছে কিনা এখনো নিশ্চিত নয়"
    }

    /** Worth a notification: the window (plus the post-window watch) is not over yet. Older replays are stored silently. */
    fun worthNotifying(n: NewsNotice, nowMs: Long): Boolean = nowMs < n.windowEndMs + POST_WINDOW_MS

    /** Notification title in Bangla. Information and protection only: never BUY / SELL wording. */
    fun title(n: NewsNotice, nowMs: Long): String {
        val name = "${n.currency} ${n.title}".trim()
        return when (n.phase) {
            "UPCOMING" -> "📰 নিউজ আসছে: $name"
            "PRE_EVENT_LOCKOUT" -> {
                val min = ((n.eventMs - nowMs) / 60_000L).coerceAtLeast(0)
                "⛔ উচ্চ-প্রভাবের নিউজ ${if (min > 0) "$min মিনিট পরে" else "এখন"}: $name · নতুন ট্রেড বন্ধ"
            }
            "RELEASED" -> "⛔ নিউজ প্রকাশের সময়: $name · নতুন ট্রেড বন্ধ"
            else -> "📊 নিউজের পরে: $name · " + if (n.settled == "Y") "বাজার শান্ত হয়েছে" else "বাজার এখনো অস্থির"
        }
    }

    /** Notification / card lines. `hhmm` formats a time on the phone's own clock and time zone. */
    fun lines(n: NewsNotice, hhmm: (Long) -> String): List<String> {
        val out = mutableListOf(
            "Impact ${n.impact} (${n.tier}) · সময় ${hhmm(n.eventMs)} · লকআউট ${hhmm(n.windowStartMs)}–${hhmm(n.windowEndMs)}",
            "পেয়ার: ${n.pairs.joinToString(", ")}" + if (n.eventState != "SCHEDULED") " · ইভেন্ট ${n.eventState}" else "",
        )
        if (n.category == REACTION) {
            out.add("প্রতিক্রিয়া: ${reactionLabel(n.reactionState)}। বাজার শান্ত না হওয়া পর্যন্ত PC READY দেবে না।")
        } else {
            out.add("খোলা ট্রেড থাকলে stop-loss, ঝুঁকি আর সম্ভাব্য gap/slippage নিজে দেখে নিন। নতুন ট্রেড বন্ধ থাকবে।")
        }
        if (n.forecast.isNotBlank()) out.add("Forecast / Previous: ${n.forecast}")
        if (n.scenario.isNotBlank() && n.category != REACTION) out.add("শর্তসাপেক্ষ সম্ভাবনা, ভবিষ্যদ্বাণী নয়: ${n.scenario}")
        out.add("এটা ট্রেড সিগন্যাল নয়। উৎস ${n.provider}" + (n.verifiedMs?.let { " · ক্যালেন্ডার ${hhmm(it)}" } ?: ""))
        return out
    }

    fun reactionLabel(state: String): String = when (state) {
        "CONFIRMS" -> "প্রত্যাশিত দিকে নড়েছে (ব্যাখ্যা মাত্র, নিশ্চয়তা নয়)"
        "CONFLICTS" -> "প্রত্যাশার উল্টো দিকে নড়েছে"
        "WHIPSAW" -> "দুই দিকেই বড় ঝাঁকুনি (whipsaw): ব্লক থাকবে"
        "OBSERVED_ONLY" -> "actual যাচাই করা যায়নি; শুধু বাজারের নড়াচড়া দেখা হয়েছে"
        "UNCLEAR" -> "স্পষ্ট নয়"
        else -> "তথ্য নেই"
    }

    /** Notices to show on the home screen: upcoming within a day, active, or ended less than 2 h ago. */
    fun current(notices: List<NewsNotice>, nowMs: Long): List<NewsNotice> =
        notices.groupBy { it.eventId }.values.mapNotNull { g -> g.maxByOrNull { it.sentMs } }
            .filter { it.windowStartMs - nowMs < 24 * 3_600_000L && nowMs - it.windowEndMs < 2 * 3_600_000L }
            .sortedBy { it.eventMs }
}
