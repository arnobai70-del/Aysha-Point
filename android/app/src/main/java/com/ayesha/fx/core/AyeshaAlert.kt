package com.ayesha.fx.core

import java.util.Locale
import java.net.URLEncoder

/**
 * One setup alert produced by the AYESHA TradingView indicator.
 * Pure Kotlin (no Android imports) so it is unit-tested on the JVM.
 */
data class AyeshaAlert(
    val id: String,
    val direction: String,   // BUY | SELL
    val symbol: String,      // e.g. OANDA:EURUSD
    val ticker: String,      // e.g. EURUSD
    val timeframe: String,   // TradingView period, e.g. "15"
    val entry: Double,
    val stop: Double,
    val target: Double,
    val rr: Double,
    val chartLot: Double,    // lot estimated on the chart (0 = NO TRADE there)
    val expiryBars: Int,
    val source: String,      // liquidity that was swept, e.g. PDL
    val targetName: String,
    val version: String,
    val why: String,
    val receivedAtMs: Long,
    val raw: String,
    val isTest: Boolean = false,
) {
    val isBuy: Boolean get() = direction == "BUY"

    val timeframeMinutes: Int
        get() = timeframe.toIntOrNull() ?: when (timeframe) {
            "60" -> 60
            "D", "1D" -> 1440
            else -> 15
        }

    val expiresAtMs: Long get() = receivedAtMs + expiryBars.toLong() * timeframeMinutes * 60_000L

    fun isExpired(nowMs: Long): Boolean = nowMs >= expiresAtMs

    fun tradingViewUrl(): String {
        val sym = URLEncoder.encode(symbol, "UTF-8")
        return "https://www.tradingview.com/chart/?symbol=$sym&interval=$timeframe"
    }

    fun levelsText(): String =
        "$direction $ticker\nEntry ${fmt(entry)}\nSL ${fmt(stop)}\nTP ${fmt(target)}\nRR ${String.format(Locale.US, "%.2f", rr)}"

    fun fmt(v: Double): String = if (ticker.endsWith("JPY")) String.format(Locale.US, "%.3f", v) else String.format(Locale.US, "%.5f", v)
}

object AlertParser {
    private val head = Regex("""AYESHA\s+(BUY|SELL)\s+(\S+)([^\n]*)""")
    private val kv = Regex("""([A-Z]+)=(\S+)""")

    /**
     * Parse notification text. Only line 1 ("AYESHA BUY OANDA:EURUSD TF=15 E=... SL=... TP=...") is required;
     * the rest of the message, if present, becomes `why`. Returns null for anything else.
     */
    fun parse(text: String, receivedAtMs: Long, isTest: Boolean = false): AyeshaAlert? {
        val m = head.find(text) ?: return null
        val direction = m.groupValues[1]
        val symbol = m.groupValues[2]
        val keys = kv.findAll(m.groupValues[3]).associate { it.groupValues[1] to it.groupValues[2] }
        val entry = keys["E"]?.toDoubleOrNull() ?: return null
        val stop = keys["SL"]?.toDoubleOrNull() ?: return null
        val target = keys["TP"]?.toDoubleOrNull() ?: return null
        val sgn = if (direction == "BUY") 1 else -1
        if ((entry - stop) * sgn <= 0 || (target - entry) * sgn <= 0) return null
        val ticker = symbol.substringAfter(':').uppercase()
        val tf = keys["TF"] ?: "15"
        val after = text.substring(m.range.last + 1).trim()
        val why = after.lines().map { it.trim() }.filter { it.isNotEmpty() }.joinToString("\n")
        val tfMin = tf.toIntOrNull() ?: 15
        // Same setup re-posted within one bar gets the same id, so it is stored and alerted once.
        val bucket = receivedAtMs / (tfMin * 60_000L)
        val id = "$symbol|$direction|$entry|$bucket"
        return AyeshaAlert(
            id = id,
            direction = direction,
            symbol = symbol,
            ticker = ticker,
            timeframe = tf,
            entry = entry,
            stop = stop,
            target = target,
            rr = keys["RR"]?.toDoubleOrNull() ?: 0.0,
            chartLot = keys["LOT"]?.toDoubleOrNull() ?: 0.0,
            expiryBars = keys["EXP"]?.toIntOrNull() ?: 8,
            source = keys["SRC"] ?: "",
            targetName = keys["TGT"] ?: "",
            version = keys["V"] ?: "",
            why = why,
            receivedAtMs = receivedAtMs,
            raw = text,
            isTest = isTest,
        )
    }

    const val SAMPLE =
        "AYESHA BUY OANDA:EURUSD TF=15 E=1.08120 SL=1.07940 TP=1.08610 RR=2.55 LOT=0.00 EXP=8 SRC=PDL TGT=ASIA_H V=test\n" +
            "Why: 1) PDL swept 2) MSS up with displacement 3) FVG entry zone\n" +
            "TEST ALERT - not a real setup"
}
