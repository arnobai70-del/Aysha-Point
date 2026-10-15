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
        val text = AlertParser.SAMPLE.replaceFirst(" V=", " BAR=$bar V=")
        val a = AlertParser.parse(text, t0)!!
        assertEquals(bar, a.barCloseMs)
        assertEquals(bar + 8 * 15 * 60_000L, a.expiresAtMs)
        assertEquals(1.0, a.quoteUsd!!, 0.0)
        assertEquals(AyeshaAlert.CHART_CANDIDATE, a.status)
        assertEquals("TV", a.origin)
        // the same bar pushed again 40 minutes later is still the same setup
        val late = AlertParser.parse(text, t0 + 40 * 60_000L)!!
        assertEquals(a.id, late.id)
        assertTrue(late.isDelayed)
        assertFalse(a.isDelayed)
        // a push that arrives after the setup expired is expired on arrival
        val tooLate = AlertParser.parse(text, bar + 3 * 3_600_000L)!!
        assertTrue(tooLate.isExpired(tooLate.receivedAtMs))
        // a different bar is a different setup
        val next = AlertParser.parse(AlertParser.SAMPLE.replaceFirst(" V=", " BAR=${bar + 900_000} V="), t0 + 900_000)!!
        assertFalse(a.id == next.id)
    }

    @Test
    fun rejectsFutureBarAndNonFiniteLevels() {
        val future = AlertParser.SAMPLE.replaceFirst(" V=", " BAR=${t0 + 3_600_000} V=")
        assertNull(AlertParser.parse(future, t0))
        assertNull(AlertParser.parse("AYESHA BUY OANDA:EURUSD TF=15 E=NaN SL=1.07 TP=1.10", t0))
        assertNull(AlertParser.parse("AYESHA BUY OANDA:EURUSD TF=15 E=Infinity SL=1.07 TP=1.10", t0))
        val noRate = AlertParser.parse("AYESHA BUY OANDA:EURJPY TF=15 E=162.0 SL=161.8 TP=163 QUSD=NA", t0)!!
        assertNull(noRate.quoteUsd)
        assertTrue(AlertParser.parse(AlertParser.sample(t0), t0)!!.hasBarTime)
    }

    // ---- signing (same vector as desktop/tests/test_no_mt5_path.py) ----
    private val code = "ABCD-EFGH-JKMN-PQRS"

    @Test
    fun signatureMatchesPythonVector() {
        val body = "AYESHA HB T=1760000000000 STATE=OK PAIRS=5 V=abc123def456"
        assertEquals("be7e74e951d5dad03d7fce53f5d2d4d3", Signer.sign(code, body))
        assertEquals(body, Signer.verify(code, body + "\nSIG=be7e74e951d5dad03d7fce53f5d2d4d3"))
        assertNull(Signer.verify(code, body.replace("OK", "XX") + "\nSIG=be7e74e951d5dad03d7fce53f5d2d4d3"))
        assertNull(Signer.verify("BBBB-EFGH-JKMN-PQRS", body + "\nSIG=be7e74e951d5dad03d7fce53f5d2d4d3"))
        assertNull(Signer.verify(code, body))
        assertNull(Signer.normalize("ABCD-0000-1111-IIII"))
        assertEquals(31, Signer.topic(code)!!.length)
        val hb = Heartbeat.parse(body)!!
        assertEquals("OK", hb.state)
        assertEquals(5, hb.pairs)
    }

    // ---- assessment ----
    private val watch = StrategyInfo.PAIRS.toSet()
    private val okLot = LotCalc.calc("EURUSD", 1.08120, 1.07940, 10_000.0, 0.5, "Standard", 0.8, 0.3)

    private fun tv(extra: String = "", bar: Long? = t0 - 60_000, v: String = StrategyInfo.HASH, tf: String = "15"): AyeshaAlert {
        val b = if (bar != null) " BAR=$bar" else ""
        return AlertParser.parse("AYESHA BUY OANDA:EURUSD TF=$tf E=1.08120 SL=1.07940 TP=1.08610 RR=2.55 LOT=0.00 EXP=8 " +
            "SRC=PDL TGT=ASIA_H$b QUSD=1 ST=CHART_CANDIDATE$extra V=$v", t0)!!
    }

    @Test
    fun freshCurrentTvAlertIsChartCandidateOnly() {
        val r = Assess.assess(tv(), t0, okLot, watch)
        assertEquals(Assess.CHART_CANDIDATE, r.state)
        assertTrue(r.actionable)
    }

    @Test
    fun oldOrMalformedTvPayloadsAreUnverified() {
        assertEquals(Assess.UNVERIFIED, Assess.assess(tv(bar = null), t0, okLot, watch).state)       // no BAR
        assertEquals(Assess.UNVERIFIED, Assess.assess(tv(v = "deadbeef0000"), t0, okLot, watch).state) // other version
        assertEquals(Assess.UNVERIFIED, Assess.assess(tv(tf = "5"), t0, okLot, watch).state)          // wrong chart TF
        assertEquals(Assess.UNVERIFIED, Assess.assess(tv(), t0, okLot, setOf("GBPUSD")).state)       // not watched
        val noSt = AlertParser.parse("AYESHA BUY OANDA:EURUSD TF=15 E=1.08120 SL=1.07940 TP=1.08610 RR=2.5 BAR=${t0 - 60_000} V=${StrategyInfo.HASH}", t0)!!
        assertEquals(Assess.UNVERIFIED, Assess.assess(noSt, t0, okLot, watch).state)
        // late push (more than one bar after the signal bar)
        val late = AlertParser.parse(tv().raw, t0 + 30 * 60_000L)!!
        assertEquals(Assess.UNVERIFIED, Assess.assess(late, t0 + 30 * 60_000L, okLot, watch).state)
        // expired on arrival
        val exp = AlertParser.parse(tv().raw, t0 + 3 * 3_600_000L)!!
        assertEquals(Assess.EXPIRED, Assess.assess(exp, exp.receivedAtMs, okLot, watch).state)
        // risk not computable / settings bad
        val bad = LotCalc.calc("EURUSD", 1.08120, 1.07940, Double.NaN, 0.5, "Standard", 0.8, 0.3)
        assertEquals(Assess.UNVERIFIED, Assess.assess(tv(), t0, bad, watch).state)
        val small = LotCalc.calc("EURUSD", 1.08120, 1.07940, 25.0, 0.5, "Standard", 0.8, 0.3)
        assertEquals(Assess.NO_TRADE, Assess.assess(tv(), t0, small, watch).state)
        assertFalse(Assess.assess(tv(), t0, small, watch).actionable)
    }

    private fun pc(st: String = "READY", blk: String = "NONE"): String {
        val bar = t0 - 60_000
        return "AYESHA BUY OANDA:EURUSD TF=15 E=1.08120 SL=1.07940 TP=1.08610 RR=2.55 LOT=0.02 EXP=0 SRC=PDL TGT=ASIA_H " +
            "BAR=$bar ST=$st FROM=PC ID=0123456789abcdef EXPU=${bar + 8 * 900_000} BLK=$blk V=${StrategyInfo.HASH}\nWhy: test"
    }

    @Test
    fun pcMessagesNeedValidSignature() {
        val body = pc()
        val msg = body + "\nSIG=" + Signer.sign(code, body)
        val verified = Signer.verify(code, msg)!!
        val a = AlertParser.parse(verified, t0, signatureOk = true)!!
        assertEquals("PC|0123456789abcdef", a.id)
        assertEquals("Why: test", a.why)
        assertEquals(Assess.READY, Assess.assess(a, t0, okLot, watch).state)
        // the same text without a valid signature (e.g. copied into a TradingView alert) is never READY
        val forged = AlertParser.parse(body, t0, signatureOk = false)!!
        assertEquals(Assess.UNVERIFIED, Assess.assess(forged, t0, okLot, watch).state)
        // PC said NO_TRADE: archive with the PC's reasons
        val nt = AlertParser.parse(pc("NO_TRADE", "MIN_LOT_EXCEEDS_RISK,NEWS_UNVERIFIED"), t0, signatureOk = true)!!
        val r = Assess.assess(nt, t0, okLot, watch)
        assertEquals(Assess.NO_TRADE, r.state)
        assertTrue(r.reasons.first().contains("MIN_LOT_EXCEEDS_RISK"))
        assertEquals(listOf("MIN_LOT_EXCEEDS_RISK", "NEWS_UNVERIFIED"), nt.blockers)
        // PC expiry is taken from EXPU
        assertEquals(t0 - 60_000 + 8 * 900_000L, a.expiresAtMs)
    }

    @Test
    fun parsesPythonGeneratedPcPush() {
        // contracts/fixtures/pc-push-ready.txt is written by desktop/tests/test_no_mt5_path.py
        val f = listOf("../../contracts/fixtures/pc-push-ready.txt", "../contracts/fixtures/pc-push-ready.txt",
            "contracts/fixtures/pc-push-ready.txt").map { java.io.File(it) }.first { it.exists() }
        val body = Signer.verify(code, f.readText())
        assertNotNull("signature from Python must verify in Kotlin", body)
        val a = AlertParser.parse(body!!, 1791969300000L + 60_000, signatureOk = true)!!
        assertEquals("PC|0123456789abcdef", a.id)
        assertEquals("READY", a.status)
        assertEquals(1791976500000L, a.expiresAtMs)
        assertEquals(1.0861, a.target, 1e-9)
        assertEquals("FIXTUREHASH", a.version)
        // the fixture's hash is not this build's strategy: correctly UNVERIFIED
        assertEquals(Assess.UNVERIFIED, Assess.assess(a, a.receivedAtMs, okLot, watch).state)
        assertEquals(Assess.READY, Assess.assess(a, a.receivedAtMs, okLot, watch, expectedHash = "FIXTUREHASH").state)
    }

    // --- v0.4.0 app: multi-timeframe, WATCH, heartbeat replay, status upgrades, journal -------------

    @Test
    fun fixtureCarriesMtfExplanation() {
        val f = listOf("../../contracts/fixtures/pc-push-ready.txt", "../contracts/fixtures/pc-push-ready.txt",
            "contracts/fixtures/pc-push-ready.txt").map { java.io.File(it) }.first { it.exists() }
        val a = AlertParser.parse(Signer.verify(code, f.readText())!!, 1791969300000L + 60_000, signatureOk = true)!!
        assertEquals("UP", a.mtf["H4"])
        assertEquals("DISCOUNT", a.mtf["Z"])
        assertEquals("PDL_SWEEP>CHOCH>FVG", a.mtf["M15"])
        val lines = Mtf.explain(a.mtf, buy = true)
        assertTrue(lines.any { it.startsWith("✅ H4") })
        assertTrue(lines.any { it.contains("discount") })
        assertTrue(lines.any { it.contains("PDL sweep → CHOCH → FVG") })
        assertEquals("H4 ✅ · H1 ✅ · discount", Mtf.summary(a.mtf, true))
        // a SELL with the same context is against both higher timeframes
        assertEquals("H4 ⚠️ · H1 ⚠️ · discount", Mtf.summary(a.mtf, false))
        assertEquals(a.mtf, Mtf.parse(Mtf.encode(a.mtf)))
    }

    @Test
    fun mtfParseIsTolerant() {
        assertTrue(Mtf.parse(null).isEmpty())
        assertTrue(Mtf.parse("NA").isEmpty())
        assertEquals(mapOf("H4" to "UP"), Mtf.parse("H4:UP,broken,:x,Z:"))
        assertTrue(Mtf.explain(emptyMap(), true).isEmpty())
    }

    private fun pcAlert(status: String, extra: String = ""): AyeshaAlert {
        val bar = t0 - 60_000
        val body = "AYESHA BUY OANDA:EURUSD TF=15 E=1.08120 SL=1.07940 TP=1.08610 RR=2.55 LOT=0.02 EXP=0 SRC=PDL TGT=ASIA_H " +
            "BAR=$bar ST=$status FROM=PC ID=0123456789abcdef EXPU=${bar + 8 * 900_000L} BLK=NONE $extra V=${StrategyInfo.HASH}"
        return AlertParser.parse(body, t0, signatureOk = true)!!
    }

    @Test
    fun pcWatchIsItsOwnStateNeverAnEntry() {
        val w = Assess.assess(pcAlert("WATCH", "MTF=H4:UP,M5:PENDING"), t0, okLot, watch)
        assertEquals(Assess.WATCH, w.state)
        assertFalse(w.actionable)
        assertTrue(w.active)
        assertTrue(w.reasons.single().contains("M5"))
        assertEquals(Assess.READY, Assess.assess(pcAlert("READY"), t0, okLot, watch).state)
    }

    @Test
    fun onlyWatchToReadyOrNoTradeMayReplaceAStoredSignal() {
        assertTrue(Transitions.allowed("WATCH", "READY"))
        assertTrue(Transitions.allowed("WATCH", "NO_TRADE"))
        assertFalse(Transitions.allowed("READY", "WATCH"))   // replayed older message
        assertFalse(Transitions.allowed("READY", "READY"))   // duplicate
        assertFalse(Transitions.allowed("NO_TRADE", "READY")) // a block is never lifted
    }

    @Test
    fun replayedHeartbeatCannotMakePcLookOnline() {
        val now = t0
        val fresh = Heartbeat(now - 60_000, "OK", 6, "h")
        assertTrue(LinkHealth.accept(fresh, 0L, now))
        assertEquals(LinkHealth.ONLINE, LinkHealth.status(fresh.pcTimeMs, "OK", now))
        // ntfy catch-up delivers a 2-hour-old heartbeat "now": rejected, and status stays OFFLINE
        val old = Heartbeat(now - 2 * 3_600_000L, "OK", 6, "h")
        assertFalse(LinkHealth.accept(old, fresh.pcTimeMs, now))
        assertEquals(LinkHealth.OFFLINE, LinkHealth.status(old.pcTimeMs, "OK", now))
        // even as the very first heartbeat, freshness comes from the PC time, not the arrival time
        assertTrue(LinkHealth.accept(old, 0L, now))
        assertEquals(LinkHealth.OFFLINE, LinkHealth.status(old.pcTimeMs, "OK", now))
        assertFalse(LinkHealth.accept(Heartbeat(now + 3_600_000L, "OK", 6, "h"), 0L, now)) // future clock
        assertEquals(LinkHealth.STOPPED, LinkHealth.status(now, "STOPPED", now))
        assertEquals(LinkHealth.DATA_PROBLEM, LinkHealth.status(now, "DATA_STALE", now))
        assertEquals(LinkHealth.NONE, LinkHealth.status(0L, "", now))
    }

    @Test
    fun journalStatsUseOnlyTypedResults() {
        val ts = listOf(
            JournalTrade("a", "EURUSD", "PC", 1, 0.40, 0.10),
            JournalTrade("b", "EURUSD", "PC", 2, -0.10, 0.10),
            JournalTrade("c", "GBPUSD", "TV", 3, -0.10, null),
            JournalTrade("d", "USDJPY", "PC", 4, 0.0, 0.10),
        )
        val s = Journal.stats(ts)
        assertEquals(4, s.trades)
        assertEquals(1, s.wins)
        assertEquals(2, s.losses)
        assertEquals(1, s.breakeven)
        assertEquals(0.20, s.netUsd, 1e-9)
        assertEquals(1.0 / 3, s.winRate!!, 1e-9)
        assertEquals(2.0, s.profitFactor!!, 1e-9)
        assertEquals(0.20, s.maxDrawdownUsd, 1e-9)
        assertEquals((4.0 - 1.0 + 0.0) / 3, s.avgR!!, 1e-9)
        assertTrue(s.smallSample)
        val empty = Journal.stats(emptyList())
        assertEquals(0, empty.trades)
        assertNull(empty.winRate)
        assertEquals(-0.12, Journal.parseUsd(" -0,12 ")!!, 1e-9)
        assertEquals(0.3, Journal.parseUsd("+0.30")!!, 1e-9)
        assertNull(Journal.parseUsd("abc"))
        assertNull(Journal.parseUsd("NaN"))
    }

    @Test
    fun backupRestoreNeverLosesATypedResult() {
        val none = Backup.Mark("NEW", null, null)
        val taken = Backup.Mark("TAKEN", null, null)
        val closed = Backup.Mark("TAKEN", -0.10, 100L)
        val newer = Backup.Mark("TAKEN", 0.25, 200L)
        assertTrue(Backup.preferIncoming(none, taken))
        assertFalse(Backup.preferIncoming(taken, none))
        assertTrue(Backup.preferIncoming(taken, closed))
        assertFalse(Backup.preferIncoming(closed, taken))     // an older backup cannot erase a result
        assertTrue(Backup.preferIncoming(closed, newer))
        assertFalse(Backup.preferIncoming(newer, closed))
        assertFalse(Backup.preferIncoming(closed, closed))
    }

    @Test
    fun inboxLimitNeverDropsJournalTrades() {
        // newest first; every 10th is a journal trade, the oldest ones included
        val items = (0 until 1000).map { it to (it % 10 == 0) }
        val kept = Backup.retain(items, { it.second }, 300)
        assertEquals(100, kept.count { it.second })              // all 100 journal trades kept
        assertEquals(300, kept.count { !it.second })             // newest 300 others
        assertTrue(kept.filter { !it.second }.all { it.first < 334 })
        assertTrue(kept.any { it.first == 990 })                 // the oldest journal trade survives
    }
}
