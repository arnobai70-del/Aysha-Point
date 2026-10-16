package com.ayesha.fx.core

/**
 * What the phone may do with an alert. Only READY and CHART_CANDIDATE can raise an entry
 * notification; everything else is archived with its reasons. Fails closed on anything
 * missing, unsigned, stale, from another strategy version or outside the watchlist.
 */
data class Assessment(val state: String, val reasons: List<String>) {
    val actionable: Boolean get() = state == Assess.READY || state == Assess.CHART_CANDIDATE
    /** Shown in the active list (WATCH too, but WATCH never raises an entry notification). */
    val active: Boolean get() = actionable || state == Assess.WATCH
}

object Assess {
    const val READY = "READY"                     // PC scanner: every PC gate passed, signed, fresh
    const val CHART_CANDIDATE = "CHART_CANDIDATE" // TradingView chart rules only; news/spread/broker unchecked
    const val NO_TRADE = "NO_TRADE"
    const val UNVERIFIED = "UNVERIFIED"
    const val EXPIRED = "EXPIRED"
    const val WATCH = "WATCH"                     // PC: setup valid but not an entry yet (waiting for M5, or not A+)

    /** Oldest PC wire format whose READY / WATCH the phone accepts (news phase and capital digest keys). */
    const val MIN_WIRE_FORMAT = 4
    const val NEWS_MAX_AGE_MS = 24 * 3_600_000L
    val NEWS_ALLOWS_ENTRY = setOf("CLEAR", "UPCOMING")

    /**
     * @param phoneCapital [Capital.digest] of this phone's equity setting (null when no pairing code or equity).
     * @param newsBlock a PC news window blocking this pair before the alert expires ([News.block]), or null.
     */
    fun assess(
        a: AyeshaAlert,
        nowMs: Long,
        lot: LotResult,
        watchlist: Set<String>,
        expectedHash: String = StrategyInfo.HASH,
        phoneCapital: String? = null,
        newsBlock: NewsNotice? = null,
    ): Assessment {
        val unverified = mutableListOf<String>()
        val noTrade = mutableListOf<String>()
        val watch = mutableListOf<String>()

        if (a.barCloseMs == null) unverified.add("সিগন্যাল বারের সময় (BAR) নেই — পুরনো indicator")
        if (a.version != expectedHash) unverified.add("strategy version মেলে না (${a.version.ifBlank { "নেই" }} ≠ $expectedHash)")
        if (a.timeframe != StrategyInfo.SETUP_TF) unverified.add("${a.timeframe}m চার্ট; নিয়ম শুধু ${StrategyInfo.SETUP_TF}m-এর জন্য")
        if (a.ticker !in watchlist) unverified.add("${a.ticker} আপনার watchlist-এ নেই")
        if (a.isDelayed) unverified.add("নোটিফিকেশন ${(a.deliveryDelayMs ?: 0) / 60_000} মিনিট দেরিতে এসেছে")

        if (a.isPc) {
            if (!a.signatureOk) unverified.add("PC বার্তার সই (signature) ঠিক নেই")
            if (a.signalId.isEmpty()) unverified.add("PC signal id নেই")
            if (a.expiresUtcMs == null) unverified.add("PC expiry নেই")
            when (a.status) {
                "READY" -> {}
                "NO_TRADE" -> noTrade.add("PC: " + (a.blockers.ifEmpty { listOf(a.status) }).joinToString(", "))
                "WATCH" -> if (a.blockers.isNotEmpty()) noTrade.add("PC: " + a.blockers.joinToString(", "))
                    else watch.add(if (a.mtf["M5"] == "PENDING") "PC: M5 confirmation-এর অপেক্ষা, এখনো entry নয়"
                        else "PC: setup বৈধ কিন্তু A+ নয়, শুধু নজরে রাখুন")
                else -> unverified.add("অজানা PC status '${a.status}'")
            }
            if (a.status == "READY" || a.status == "WATCH") pcChecks(a, nowMs, phoneCapital, unverified)
        } else {
            if (a.status != CHART_CANDIDATE) unverified.add("status (ST) নেই বা ভুল")
        }
        if (a.rr < StrategyInfo.MIN_NET_RR) noTrade.add("RR ${"%.2f".format(java.util.Locale.US, a.rr)} < ${StrategyInfo.MIN_NET_RR}")
        if (newsBlock != null) noTrade.add(News.blockReason(newsBlock, nowMs))

        when (lot.status) {
            LotCalc.OK -> {}
            LotCalc.NO_TRADE_MIN_LOT -> noTrade.add("0.01 লটেও ঝুঁকি বাজেটের বেশি")
            else -> unverified.add(lot.note)
        }

        return when {
            a.isExpired(nowMs) -> Assessment(EXPIRED, listOf("মেয়াদ শেষ") + unverified + noTrade)
            unverified.isNotEmpty() -> Assessment(UNVERIFIED, unverified + noTrade)
            noTrade.isNotEmpty() -> Assessment(NO_TRADE, noTrade)
            watch.isNotEmpty() -> Assessment(WATCH, watch)
            a.isPc -> Assessment(READY, listOf("PC: নিউজ (${a.newsPhase}), capital (ফোনের সাথে মিল), feed spread, " +
                "Exness spec (মালিক-নিশ্চিত) যাচাই হয়েছে"))
            else -> Assessment(CHART_CANDIDATE, listOf("চার্টের নিয়ম মিলেছে; নিউজ, আসল spread, Exness নিয়ম যাচাই হয়নি"))
        }
    }

    /** A PC READY / WATCH must carry fresh news and capital evidence that matches this phone (wire format 4). */
    private fun pcChecks(a: AyeshaAlert, nowMs: Long, phoneCapital: String?, unverified: MutableList<String>) {
        if (a.wireFormat < MIN_WIRE_FORMAT) {
            unverified.add("PC সফটওয়্যার পুরনো (wire format ${a.wireFormat}, দরকার $MIN_WIRE_FORMAT): PC আপডেট করুন")
            return
        }
        when (Capital.compare(a.capitalDigest, phoneCapital)) {
            Capital.MISMATCH -> unverified.add("${Capital.MISMATCH}: ফোন আর PC-র Exness equity মেলে না — দুই জায়গায় একই equity লিখুন")
            Capital.UNVERIFIED -> unverified.add("${Capital.UNVERIFIED}: PC বা ফোনের equity যাচাই করা যায়নি")
        }
        val capT = a.capitalTimeMs
        if (capT == null || nowMs - capT > Capital.MAX_AGE_MS || capT > nowMs + AlertParser.MAX_CLOCK_SKEW_MS) {
            unverified.add("${Capital.STALE}: PC-র capital snapshot ২৪ ঘণ্টার বেশি পুরনো বা সময় ভুল")
        }
        val nv = a.newsVerifiedMs
        if (nv == null || nowMs - nv > NEWS_MAX_AGE_MS || nv > nowMs + AlertParser.MAX_CLOCK_SKEW_MS) {
            unverified.add("NEWS_UNVERIFIED: PC-র নিউজ ক্যালেন্ডার পুরনো, নেই বা সময় ভুল")
        }
        if (a.status == "READY") {
            if (a.newsPhase !in NEWS_ALLOWS_ENTRY) {
                unverified.add("PC READY কিন্তু নিউজ অবস্থা '${a.newsPhase.ifBlank { "নেই" }}' — অসঙ্গত বার্তা, নেবেন না")
            }
            if (a.specKind != "OWNER" && a.specKind != "MT5") unverified.add("BROKER_SPEC_UNVERIFIED: Exness contract যাচাই হয়নি")
            val rp = a.riskPercent
            if (rp == null || rp > SettingsCheck.MAX_RISK_PERCENT) unverified.add("PC risk % নেই বা ১%-এর বেশি")
        }
    }
}
