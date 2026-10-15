package com.ayesha.fx.core

import java.util.Locale
import kotlin.math.abs
import kotlin.math.floor

/**
 * Lot sizing. Same model as desktop/ayesha/risk/engine.py: loss = |entry-stop| + spread + slippage; floor to 0.01;
 * never round up. Fails closed: anything it cannot verify gives a non-OK status and lot 0, never a guessed lot.
 */
data class LotResult(
    val status: String,      // one of LotCalc.OK, NO_TRADE_MIN_LOT, RISK_UNVERIFIED, INVALID_SETTINGS, INVALID_LEVELS
    val lot: Double,
    val maxLossUsd: Double,
    val budgetUsd: Double,
    val minLotLossUsd: Double,
    val minLotLossPercent: Double,
    val stopPips: Double,
    val note: String,
    val rateSource: String = "",   // where the quote->USD rate came from: "PAIR" or "CHART"
) {
    val ok: Boolean get() = status == LotCalc.OK
}

/** Owner-typed capital settings. Validated before any lot is computed. */
object SettingsCheck {
    const val MAX_RISK_PERCENT = 1.0
    const val MIN_RISK_PERCENT = 0.1
    const val MAX_EQUITY_USD = 10_000_000.0
    const val MAX_COST_PIPS = 20.0

    /** Returns a list of problems in Bangla; empty means the settings are usable. */
    fun problems(equityUsd: Double, riskPercent: Double, spreadPips: Double, slippagePips: Double): List<String> {
        val out = mutableListOf<String>()
        if (!equityUsd.isFinite() || equityUsd <= 0 || equityUsd > MAX_EQUITY_USD) out.add("Equity ০-এর বেশি একটা সঠিক সংখ্যা দিন")
        if (!riskPercent.isFinite() || riskPercent < MIN_RISK_PERCENT || riskPercent > MAX_RISK_PERCENT) out.add("Risk % ০.১ থেকে ১-এর মধ্যে দিন")
        if (!spreadPips.isFinite() || spreadPips < 0 || spreadPips > MAX_COST_PIPS) out.add("Spread ০ থেকে ২০ pips-এর মধ্যে দিন")
        if (!slippagePips.isFinite() || slippagePips < 0 || slippagePips > MAX_COST_PIPS) out.add("Slippage ০ থেকে ২০ pips-এর মধ্যে দিন")
        return out
    }
}

object LotCalc {
    const val MIN_LOT = 0.01
    const val OK = "OK"
    const val NO_TRADE_MIN_LOT = "NO_TRADE_MIN_LOT"
    const val RISK_UNVERIFIED = "RISK_UNVERIFIED"
    const val INVALID_SETTINGS = "INVALID_SETTINGS"
    const val INVALID_LEVELS = "INVALID_LEVELS"

    private val FX = setOf("USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF")

    fun pipSize(ticker: String): Double = if (ticker.uppercase().endsWith("JPY")) 0.01 else 0.0001

    fun contractUnits(accountType: String): Double = if (accountType == "StandardCent") 1_000.0 else 100_000.0

    /** True only for 6-letter pairs of major currencies; metals, indices and crypto are not sized on the phone. */
    fun isFxPair(ticker: String): Boolean {
        val t = ticker.uppercase()
        return t.length == 6 && t.substring(0, 3) in FX && t.substring(3, 6) in FX && t.substring(0, 3) != t.substring(3, 6)
    }

    /** USD value of one unit of the quote currency when it follows from the pair itself (xxxUSD, USDxxx). */
    fun quoteToUsd(ticker: String, price: Double): Double? {
        val t = ticker.uppercase()
        if (!isFxPair(t) || !price.isFinite() || price <= 0) return null
        return when {
            t.substring(3, 6) == "USD" -> 1.0
            t.substring(0, 3) == "USD" -> 1.0 / price
            else -> null
        }
    }

    private fun fail(status: String, note: String, stopPips: Double = 0.0, budget: Double = 0.0) =
        LotResult(status, 0.0, 0.0, budget, 0.0, 0.0, stopPips, note)

    /**
     * @param chartQuoteUsd quote->USD rate sent by the indicator (QUSD=), used only for crosses such as EURJPY.
     */
    fun calc(
        ticker: String,
        entry: Double,
        stop: Double,
        equityUsd: Double,
        riskPercent: Double,
        accountType: String,
        spreadPips: Double,
        slippagePips: Double,
        chartQuoteUsd: Double? = null,
    ): LotResult {
        val bad = SettingsCheck.problems(equityUsd, riskPercent, spreadPips, slippagePips)
        if (bad.isNotEmpty()) return fail(INVALID_SETTINGS, "Settings ঠিক নেই: " + bad.joinToString("; "))
        if (!entry.isFinite() || !stop.isFinite() || entry <= 0 || stop <= 0 || entry == stop) {
            return fail(INVALID_LEVELS, "Entry/SL ঠিক নেই")
        }
        val pip = pipSize(ticker)
        val stopPips = abs(entry - stop) / pip
        val budget = equityUsd * riskPercent / 100.0
        if (!isFxPair(ticker)) return fail(RISK_UNVERIFIED, "$ticker-এর লট এই অ্যাপ হিসাব করে না", stopPips, budget)
        val pairRate = quoteToUsd(ticker, entry)
        val chartRate = chartQuoteUsd?.takeIf { it.isFinite() && it > 0 }
        val q = pairRate ?: chartRate
            ?: return fail(RISK_UNVERIFIED, "$ticker-এর USD রেট জানা নেই (indicator আপডেট করুন)", stopPips, budget)
        val pipValuePerLot = contractUnits(accountType) * pip * q
        val lossPips = stopPips + spreadPips + slippagePips
        val perLot = lossPips * pipValuePerLot
        val lot = floor(budget / perLot * 100 + 1e-9) / 100
        val minLoss = MIN_LOT * perLot
        val ok = lot >= MIN_LOT && lot * perLot <= budget + 1e-9
        val note = if (ok) "OK" else "NO TRADE: 0.01 lot risks $" + String.format(Locale.US, "%.2f", minLoss) +
            " but budget is $" + String.format(Locale.US, "%.3f", budget)
        return LotResult(
            status = if (ok) OK else NO_TRADE_MIN_LOT,
            lot = if (ok) lot else 0.0,
            maxLossUsd = if (ok) lot * perLot else 0.0,
            budgetUsd = budget,
            minLotLossUsd = minLoss,
            minLotLossPercent = 100 * minLoss / equityUsd,
            stopPips = stopPips,
            note = note,
            rateSource = if (pairRate != null) "PAIR" else "CHART",
        )
    }
}
