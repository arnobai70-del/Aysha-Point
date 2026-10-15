package com.ayesha.fx.core

import java.util.Locale
import kotlin.math.floor

/** Same model as desktop/ayesha/risk/engine.py: loss = |entry-stop| + spread + slippage; floor to 0.01; never round up. */
data class LotResult(
    val ok: Boolean,
    val lot: Double,
    val maxLossUsd: Double,
    val budgetUsd: Double,
    val minLotLossUsd: Double,
    val minLotLossPercent: Double,
    val stopPips: Double,
    val note: String,
)

object LotCalc {
    const val MIN_LOT = 0.01

    fun pipSize(ticker: String): Double = if (ticker.uppercase().endsWith("JPY")) 0.01 else 0.0001

    fun contractUnits(accountType: String): Double = if (accountType == "StandardCent") 1_000.0 else 100_000.0

    /** USD value of one unit of the quote currency, or null when it cannot be known from the pair alone. */
    fun quoteToUsd(ticker: String, price: Double): Double? {
        val t = ticker.uppercase()
        if (t.length < 6) return null
        return when {
            t.substring(3, 6) == "USD" -> 1.0
            t.substring(0, 3) == "USD" -> 1.0 / price
            else -> null
        }
    }

    fun calc(
        ticker: String,
        entry: Double,
        stop: Double,
        equityUsd: Double,
        riskPercent: Double,
        accountType: String,
        spreadPips: Double,
        slippagePips: Double,
    ): LotResult? {
        val q = quoteToUsd(ticker, entry) ?: return null
        val pip = pipSize(ticker)
        val pipValuePerLot = contractUnits(accountType) * pip * q
        val lossPips = kotlin.math.abs(entry - stop) / pip + spreadPips + slippagePips
        val perLot = lossPips * pipValuePerLot
        val budget = equityUsd * riskPercent / 100.0
        val lot = if (perLot > 0) floor(budget / perLot * 100 + 1e-9) / 100 else 0.0
        val minLoss = MIN_LOT * perLot
        val ok = lot >= MIN_LOT && equityUsd > 0
        val note = if (ok) "OK" else "NO TRADE: 0.01 lot risks $" + String.format(Locale.US, "%.2f", minLoss) +
            " but budget is $" + String.format(Locale.US, "%.3f", budget)
        return LotResult(
            ok = ok,
            lot = if (ok) lot else 0.0,
            maxLossUsd = if (ok) lot * perLot else 0.0,
            budgetUsd = budget,
            minLotLossUsd = minLoss,
            minLotLossPercent = if (equityUsd > 0) 100 * minLoss / equityUsd else 0.0,
            stopPips = kotlin.math.abs(entry - stop) / pip,
            note = note,
        )
    }
}
