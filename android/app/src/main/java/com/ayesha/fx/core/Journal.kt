package com.ayesha.fx.core

/**
 * The owner's own trade results, typed by hand after closing a trade in the Exness app. These are
 * REAL results only: signals, backtests and hypothetical outcomes never enter these statistics.
 */
data class JournalTrade(
    val id: String,
    val pair: String,
    val origin: String,      // PC | TV
    val closedAtMs: Long,
    val resultUsd: Double,
    val riskUsd: Double?,    // planned max loss when marked; null if unknown
)

data class JournalStats(
    val trades: Int,
    val wins: Int,
    val losses: Int,
    val breakeven: Int,
    val netUsd: Double,
    val winRate: Double?,
    val avgWinUsd: Double?,
    val avgLossUsd: Double?,
    val profitFactor: Double?,
    val maxDrawdownUsd: Double,
    val avgR: Double?,
    val smallSample: Boolean,
)

object Journal {
    const val SMALL_SAMPLE = 30

    fun stats(list: List<JournalTrade>): JournalStats {
        val ts = list.sortedBy { it.closedAtMs }
        val wins = ts.filter { it.resultUsd > 0 }
        val losses = ts.filter { it.resultUsd < 0 }
        var eq = 0.0
        var peak = 0.0
        var dd = 0.0
        for (t in ts) {
            eq += t.resultUsd
            peak = maxOf(peak, eq)
            dd = maxOf(dd, peak - eq)
        }
        val gw = wins.sumOf { it.resultUsd }
        val gl = -losses.sumOf { it.resultUsd }
        val rs = ts.mapNotNull { t -> t.riskUsd?.takeIf { it > 0 }?.let { t.resultUsd / it } }
        val decided = wins.size + losses.size
        return JournalStats(
            trades = ts.size,
            wins = wins.size,
            losses = losses.size,
            breakeven = ts.size - decided,
            netUsd = ts.sumOf { it.resultUsd },
            winRate = if (decided > 0) wins.size.toDouble() / decided else null,
            avgWinUsd = if (wins.isNotEmpty()) gw / wins.size else null,
            avgLossUsd = if (losses.isNotEmpty()) -gl / losses.size else null,
            profitFactor = if (gl > 0) gw / gl else null,
            maxDrawdownUsd = dd,
            avgR = if (rs.isNotEmpty()) rs.average() else null,
            smallSample = ts.size < SMALL_SAMPLE,
        )
    }

    /** Parse a typed result like "-0.12", "+0.30", "0,25". Null when it is not a finite number. */
    fun parseUsd(s: String): Double? = s.trim().replace(',', '.').removePrefix("+").toDoubleOrNull()?.takeIf { it.isFinite() }
}
