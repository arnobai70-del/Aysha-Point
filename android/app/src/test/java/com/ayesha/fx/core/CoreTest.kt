package com.ayesha.fx.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CoreTest {
    private val t0 = 1_760_000_000_000L

    @Test
    fun parsesIndicatorAlert() {
        val a = AlertParser.parse(AlertParser.SAMPLE, t0)
        assertNotNull(a)
        a!!
        assertEquals("BUY", a.direction)
        assertEquals("OANDA:EURUSD", a.symbol)
        assertEquals("EURUSD", a.ticker)
        assertEquals(1.08120, a.entry, 1e-9)
        assertEquals(1.07940, a.stop, 1e-9)
        assertEquals(1.08610, a.target, 1e-9)
        assertEquals(2.55, a.rr, 1e-9)
        assertEquals(8, a.expiryBars)
        assertEquals("PDL", a.source)
        assertTrue(a.why.startsWith("Why: 1) PDL swept"))
        assertEquals(t0 + 8 * 15 * 60_000L, a.expiresAtMs)
        assertTrue(a.tradingViewUrl().contains("symbol=OANDA%3AEURUSD"))
        assertTrue(a.tradingViewUrl().endsWith("interval=15"))
    }

    @Test
    fun parsesWhenTradingViewPrefixesTitle() {
        val text = "Alert on EURUSD\n" + AlertParser.SAMPLE
        assertNotNull(AlertParser.parse(text, t0))
    }

    @Test
    fun parsesTruncatedFirstLineOnly() {
        val a = AlertParser.parse("AYESHA SELL FX:GBPJPY TF=15 E=190.500 SL=190.800 TP=189.700", t0)
        assertNotNull(a)
        assertEquals("GBPJPY", a!!.ticker)
        assertEquals("", a.why)
    }

    @Test
    fun rejectsOtherNotificationsAndBadLevels() {
        assertNull(AlertParser.parse("EURUSD crossing 1.0800", t0))
        assertNull(AlertParser.parse("AYESHA BUY OANDA:EURUSD TF=15 E=1.08 SL=1.09 TP=1.10", t0))
        assertNull(AlertParser.parse("AYESHA BUY OANDA:EURUSD TF=15 SL=1.07 TP=1.10", t0))
    }

    @Test
    fun sameSetupWithinOneBarHasSameId() {
        val a = AlertParser.parse(AlertParser.SAMPLE, t0)!!
        val b = AlertParser.parse(AlertParser.SAMPLE, t0 + 30_000)!!
        assertEquals(a.id, b.id)
    }

    @Test
    fun expiry() {
        val a = AlertParser.parse(AlertParser.SAMPLE, t0)!!
        assertFalse(a.isExpired(t0 + 60_000))
        assertTrue(a.isExpired(t0 + 2 * 3_600_000))
    }

    @Test
    fun smallStandardAccountIsNoTrade() {
        // $25, 0.5%, 18 pip stop on EURUSD: 0.01 lot risks ~$1.91 > $0.125 budget
        val r = LotCalc.calc("EURUSD", 1.08120, 1.07940, 25.0, 0.5, "Standard", 0.8, 0.3)!!
        assertFalse(r.ok)
        assertEquals(0.0, r.lot, 0.0)
        assertTrue(r.note.startsWith("NO TRADE"))
        assertTrue(r.minLotLossPercent > 5)
    }

    @Test
    fun centAccountMakesItTradeable() {
        val r = LotCalc.calc("EURUSD", 1.08120, 1.07940, 25.0, 0.5, "StandardCent", 0.8, 0.3)!!
        assertTrue(r.ok)
        assertTrue(r.maxLossUsd <= r.budgetUsd + 1e-9)
    }

    @Test
    fun lotFloorsNeverRoundsUp() {
        // $1000, 0.5% = $5; loss/lot = (18 + 0.8 + 0.3) pips * $10 = $191 -> 0.0261 -> 0.02
        val r = LotCalc.calc("EURUSD", 1.08120, 1.07940, 1000.0, 0.5, "Standard", 0.8, 0.3)!!
        assertEquals(0.02, r.lot, 1e-9)
        assertTrue(r.maxLossUsd <= r.budgetUsd)
    }

    @Test
    fun jpyAndCrosses() {
        val r = LotCalc.calc("USDJPY", 150.00, 149.80, 10_000.0, 0.5, "Standard", 0.8, 0.3)!!
        assertEquals(20.0, r.stopPips, 1e-6)
        assertTrue(r.ok)
        // a cross without a chart-supplied USD rate is never sized
        val x = LotCalc.calc("EURJPY", 162.0, 161.8, 10_000.0, 0.5, "Standard", 0.8, 0.3)
        assertEquals(LotCalc.RISK_UNVERIFIED, x.status)
        assertEquals(0.0, x.lot, 0.0)
    }

    @Test
    fun crossUsesChartRateWhenSent() {
        // EURJPY with QUSD = 1/150: pip value per lot = 100000 * 0.01 / 150 = $6.667
        val r = LotCalc.calc("EURJPY", 162.0, 161.8, 10_000.0, 0.5, "Standard", 0.8, 0.3, chartQuoteUsd = 1.0 / 150)
        assertTrue(r.ok)
        assertEquals("CHART", r.rateSource)
        // budget $50 / (21.1 pips * 6.667) = 0.355 -> 0.35
        assertEquals(0.35, r.lot, 1e-9)
        assertTrue(r.maxLossUsd <= r.budgetUsd)
    }

    @Test
    fun unknownInstrumentsFailClosed() {
        for (t in listOf("XAUUSD", "US30", "BTCUSD", "EUR")) {
            val r = LotCalc.calc(t, 100.0, 99.0, 10_000.0, 0.5, "Standard", 0.8, 0.3, chartQuoteUsd = 1.0)
            assertEquals(t, LotCalc.RISK_UNVERIFIED, r.status)
            assertFalse(r.ok)
        }
    }

    @Test
    fun badSettingsFailClosed() {
        val bad = listOf(
            doubleArrayOf(-25.0, 0.5, 0.8, 0.3), doubleArrayOf(0.0, 0.5, 0.8, 0.3), doubleArrayOf(Double.NaN, 0.5, 0.8, 0.3),
            doubleArrayOf(Double.POSITIVE_INFINITY, 0.5, 0.8, 0.3), doubleArrayOf(25.0, 5.0, 0.8, 0.3),
            doubleArrayOf(25.0, Double.NaN, 0.8, 0.3), doubleArrayOf(25.0, 0.0, 0.8, 0.3), doubleArrayOf(25.0, 0.5, -1.0, 0.3),
            doubleArrayOf(25.0, 0.5, 0.8, Double.NaN), doubleArrayOf(25.0, 0.5, 99.0, 0.3),
        )
        for (b in bad) {
            val r = LotCalc.calc("EURUSD", 1.08120, 1.07940, b[0], b[1], "StandardCent", b[2], b[3])
            assertEquals(b.joinToString(), LotCalc.INVALID_SETTINGS, r.status)
            assertEquals(0.0, r.lot, 0.0)
        }
        assertTrue(SettingsCheck.problems(25.0, 0.5, 0.8, 0.3).isEmpty())
        assertEquals(LotCalc.INVALID_LEVELS, LotCalc.calc("EURUSD", 1.08, 1.08, 25.0, 0.5, "StandardCent", 0.8, 0.3).status)
        assertEquals(LotCalc.INVALID_LEVELS, LotCalc.calc("EURUSD", Double.NaN, 1.08, 25.0, 0.5, "StandardCent", 0.8, 0.3).status)
    }

    @Test
    fun smallAccountsNeverExceedBudget() {
        // $20/$25/$30 owners, 18 pip EURUSD stop, 1% cap: Standard is always NO TRADE, Cent stays inside budget.
        for (eq in listOf(20.0, 25.0, 30.0)) {
            for (risk in listOf(0.5, 1.0)) {
                val std = LotCalc.calc("EURUSD", 1.08120, 1.07940, eq, risk, "Standard", 0.8, 0.3)
                assertEquals(LotCalc.NO_TRADE_MIN_LOT, std.status)
                val cent = LotCalc.calc("EURUSD", 1.08120, 1.07940, eq, risk, "StandardCent", 0.8, 0.3)
                if (cent.ok) assertTrue(cent.maxLossUsd <= eq * risk / 100 + 1e-9)
                else assertEquals(0.0, cent.lot, 0.0)
            }
        }
    }

    @Test
    fun barTimeDrivesExpiryAndId() {
        val bar = t0 - 5 * 60_000L
        val text = AlertParser.SAMPLE.replaceFirst(" V=test", " BAR=$bar V=test")
        val a = AlertParser.parse(text, t0)!!
        assertEquals(bar, a.barCloseMs)
        assertEquals(bar + 8 * 15 * 60_000L, a.expiresAtMs)
        assertEquals(1.0, a.quoteUsd!!, 0.0)
        assertEquals(AyeshaAlert.CHART_CANDIDATE, a.status)
        // the same bar pushed again 40 minutes later is still the same setup
        val late = AlertParser.parse(text, t0 + 40 * 60_000L)!!
        assertEquals(a.id, late.id)
        assertTrue(late.isDelayed)
        assertFalse(a.isDelayed)
        // a push that arrives after the setup expired is expired on arrival
        val tooLate = AlertParser.parse(text, bar + 3 * 3_600_000L)!!
        assertTrue(tooLate.isExpired(tooLate.receivedAtMs))
        // a different bar is a different setup
        val next = AlertParser.parse(AlertParser.SAMPLE.replaceFirst(" V=test", " BAR=${bar + 900_000} V=test"), t0 + 900_000)!!
        assertFalse(a.id == next.id)
    }

    @Test
    fun rejectsFutureBarAndNonFiniteLevels() {
        val future = AlertParser.SAMPLE.replaceFirst(" V=test", " BAR=${t0 + 3_600_000} V=test")
        assertNull(AlertParser.parse(future, t0))
        assertNull(AlertParser.parse("AYESHA BUY OANDA:EURUSD TF=15 E=NaN SL=1.07 TP=1.10", t0))
        assertNull(AlertParser.parse("AYESHA BUY OANDA:EURUSD TF=15 E=Infinity SL=1.07 TP=1.10", t0))
        val noRate = AlertParser.parse("AYESHA BUY OANDA:EURJPY TF=15 E=162.0 SL=161.8 TP=163 QUSD=NA", t0)!!
        assertNull(noRate.quoteUsd)
        assertTrue(AlertParser.parse(AlertParser.sample(t0), t0)!!.hasBarTime)
    }
}
