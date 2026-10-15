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
        assertNull(LotCalc.calc("EURJPY", 162.0, 161.8, 10_000.0, 0.5, "Standard", 0.8, 0.3))
    }
}
