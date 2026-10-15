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
    /** Close time (UTC ms) of the chart bar that produced the setup, from the BAR= key. Null for old indicator versions. */
    val barCloseMs: Long? = null,
    /** USD per 1 unit of the quote currency as TradingView saw it (QUSD=). Null when missing. */
    val quoteUsd: Double? = null,
    /** Status the sender declared (ST=): CHART_CANDIDATE from TradingView; READY / NO_TRADE / WATCH from the PC. "" = missing. */
    val status: String = "",
    /** "TV" for TradingView notifications, "PC" for the AYESHA PC scanner (FROM=PC). */
    val origin: String = "TV",
    /** PC canonical signal id (ID=), shared with the PC registry. */
    val signalId: String = "",
    /** PC-declared expiry (EXPU=, UTC ms). */
    val expiresUtcMs: Long? = null,
    /** PC risk-gate reason codes (BLK=). */
    val blockers: List<String> = emptyList(),
    /** True only when the message carried a valid signature for this phone's pairing code. */
    val signatureOk: Boolean = false,
) {
    companion object {
        const val CHART_CANDIDATE = "CHART_CANDIDATE"
    }

    val isPc: Boolean get() = origin == "PC"

    val isBuy: Boolean get() = direction == "BUY"

    val timeframeMinutes: Int
        get() = timeframe.toIntOrNull() ?: when (timeframe) {
            "60" -> 60
            "D", "1D" -> 1440
            else -> 15
        }

    /** Time the setup was produced: the signal bar's close when known, else when the phone got it. */
    val signalTimeMs: Long get() = barCloseMs ?: receivedAtMs

    /** Expiry counts from the signal bar, so a push that arrives late does not get extra life. */
    val expiresAtMs: Long get() = expiresUtcMs ?: (signalTimeMs + expiryBars.toLong() * timeframeMinutes * 60_000L)

    /** How late the push reached the phone, or null if the indicator did not send BAR=. */
    val deliveryDelayMs: Long? get() = barCloseMs?.let { receivedAtMs - it }

    /** Arrived more than one bar after the signal bar closed. */
    val isDelayed: Boolean get() = (deliveryDelayMs ?: 0L) > timeframeMinutes * 60_000L

    /** True when the signal bar time is known (new indicator). Without it expiry is only approximate. */
    val hasBarTime: Boolean get() = barCloseMs != null

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
    /** A bar time more than this far ahead of the phone clock is treated as bad data. */
    const val MAX_CLOCK_SKEW_MS = 10 * 60_000L

    /**
     * Parse notification text. Only line 1 ("AYESHA BUY OANDA:EURUSD TF=15 E=... SL=... TP=...") is required;
     * the rest of the message, if present, becomes `why`. Returns null for anything else or for bad levels.
     */
    fun parse(text: String, receivedAtMs: Long, isTest: Boolean = false, signatureOk: Boolean = false): AyeshaAlert? {
        val m = head.find(text) ?: return null
        val direction = m.groupValues[1]
        val symbol = m.groupValues[2]
        val keys = kv.findAll(m.groupValues[3]).associate { it.groupValues[1] to it.groupValues[2] }
        val entry = num(keys["E"]) ?: return null
        val stop = num(keys["SL"]) ?: return null
        val target = num(keys["TP"]) ?: return null
        if (entry <= 0 || stop <= 0 || target <= 0) return null
        val sgn = if (direction == "BUY") 1 else -1
        if ((entry - stop) * sgn <= 0 || (target - entry) * sgn <= 0) return null
        val ticker = symbol.substringAfter(':').uppercase()
        val tf = keys["TF"] ?: "15"
        val after = text.substring(m.range.last + 1).trim()
        val why = after.lines().map { it.trim() }.filter { it.isNotEmpty() && !it.startsWith("SIG=") }.joinToString("\n")
        val tfMin = tf.toIntOrNull()?.takeIf { it > 0 } ?: 15
        val origin = if (keys["FROM"] == "PC") "PC" else "TV"
        val expiryBars = keys["EXP"]?.toIntOrNull()?.takeIf { it in 1..500 } ?: StrategyInfo.EXPIRY_BARS
        val expU = keys["EXPU"]?.toLongOrNull()?.takeIf { it > 0 }
        val sigId = keys["ID"]?.takeIf { Regex("[0-9a-f]{8,64}").matches(it) } ?: ""
        val bar = keys["BAR"]?.toLongOrNull()?.takeIf { it > 0 }
        if (bar != null && bar > receivedAtMs + MAX_CLOCK_SKEW_MS) return null
        val quoteUsd = num(keys["QUSD"])?.takeIf { it > 0 }
        // Same setup (same pair, side, chart bar) always gets the same id, however late or often it is pushed.
        // Old indicator versions without BAR= fall back to the arrival-time bucket.
        val id = when {
            origin == "PC" && sigId.isNotEmpty() -> "PC|$sigId"
            bar != null -> "$symbol|$direction|$tf|$bar"
            else -> "$symbol|$direction|$entry|${receivedAtMs / (tfMin * 60_000L)}"
        }
        return AyeshaAlert(
            id = id,
            direction = direction,
            symbol = symbol,
            ticker = ticker,
            timeframe = tf,
            entry = entry,
            stop = stop,
            target = target,
            rr = num(keys["RR"]) ?: 0.0,
            chartLot = num(keys["LOT"]) ?: 0.0,
            expiryBars = expiryBars,
            source = keys["SRC"] ?: "",
            targetName = keys["TGT"] ?: "",
            version = keys["V"] ?: "",
            why = why,
            receivedAtMs = receivedAtMs,
            raw = text,
            isTest = isTest,
            barCloseMs = bar,
            quoteUsd = quoteUsd,
            status = keys["ST"] ?: "",
            origin = origin,
            signalId = sigId,
            expiresUtcMs = expU,
            blockers = keys["BLK"]?.split(',')?.filter { it.isNotBlank() && it != "NONE" } ?: emptyList(),
            signatureOk = signatureOk && origin == "PC",
        )
    }

    private fun num(s: String?): Double? = s?.toDoubleOrNull()?.takeIf { it.isFinite() }

    val SAMPLE =
        "AYESHA BUY OANDA:EURUSD TF=15 E=1.08120 SL=1.07940 TP=1.08610 RR=2.55 LOT=0.00 EXP=8 SRC=PDL TGT=ASIA_H QUSD=1 ST=CHART_CANDIDATE V=" + StrategyInfo.HASH + "\n" +
            "Why: 1) PDL swept 2) MSS up with displacement 3) FVG entry zone\n" +
            "TEST ALERT - not a real setup"

    /** Test alert stamped with a just-closed 15m bar, so it looks like a fresh live alert. */
    fun sample(nowMs: Long): String {
        val bar = nowMs - nowMs % (15 * 60_000L)
        return SAMPLE.replaceFirst(" V=", " BAR=$bar V=")
    }
}
