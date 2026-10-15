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

    fun assess(
        a: AyeshaAlert,
        nowMs: Long,
        lot: LotResult,
        watchlist: Set<String>,
        expectedHash: String = StrategyInfo.HASH,
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
        } else {
            if (a.status != CHART_CANDIDATE) unverified.add("status (ST) নেই বা ভুল")
        }
        if (a.rr < StrategyInfo.MIN_NET_RR) noTrade.add("RR ${"%.2f".format(java.util.Locale.US, a.rr)} < ${StrategyInfo.MIN_NET_RR}")

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
            a.isPc -> Assessment(READY, listOf("PC: নিউজ, feed spread, Exness spec (মালিক-নিশ্চিত) যাচাই হয়েছে"))
            else -> Assessment(CHART_CANDIDATE, listOf("চার্টের নিয়ম মিলেছে; নিউজ, আসল spread, Exness নিয়ম যাচাই হয়নি"))
        }
    }
}
