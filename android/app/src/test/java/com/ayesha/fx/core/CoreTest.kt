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

    /** This phone's equity digest in the tests: equity $500 with the shared pairing code. */
    private val phoneCap = Capital.digest(code, 500.0)

    /** Wire format 4 keys (PC 0.8.0): news phase, calendar time, capital snapshot and digest, risk %, spec. */
    private fun v4(np: String = "CLEAR", caph: String? = phoneCap, capT: Long = t0 - 3_600_000L, nv: Long = t0 - 600_000L,
                   spec: String = "OWNER", riskp: String = "0.5") =
        "WF=4 NP=$np NE=NONE NT=0 NI=NONE NV=$nv CAPV=3 CAPT=$capT CAPH=${caph ?: "NA"} RISKP=$riskp SPEC=$spec"

    private fun pc(st: String = "READY", blk: String = "NONE", keys: String = v4()): String {
        val bar = t0 - 60_000
        return "AYESHA BUY OANDA:EURUSD TF=15 E=1.08120 SL=1.07940 TP=1.08610 RR=2.55 LOT=0.02 EXP=0 SRC=PDL TGT=ASIA_H " +
            "BAR=$bar ST=$st FROM=PC ID=0123456789abcdef EXPU=${bar + 8 * 900_000} BLK=$blk $keys V=${StrategyInfo.HASH}\nWhy: test"
    }

    @Test
    fun pcMessagesNeedValidSignature() {
        val body = pc()
        val msg = body + "\nSIG=" + Signer.sign(code, body)
        val verified = Signer.verify(code, msg)!!
        val a = AlertParser.parse(verified, t0, signatureOk = true)!!
        assertEquals("PC|0123456789abcdef", a.id)
        assertEquals("Why: test", a.why)
        assertEquals(Assess.READY, Assess.assess(a, t0, okLot, watch, phoneCapital = phoneCap).state)
        // the same text without a valid signature (e.g. copied into a TradingView alert) is never READY
        val forged = AlertParser.parse(body, t0, signatureOk = false)!!
        assertEquals(Assess.UNVERIFIED, Assess.assess(forged, t0, okLot, watch, phoneCapital = phoneCap).state)
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
        assertEquals(Assess.UNVERIFIED, Assess.assess(a, a.receivedAtMs, okLot, watch, phoneCapital = phoneCap).state)
        assertEquals(Assess.READY, Assess.assess(a, a.receivedAtMs, okLot, watch, expectedHash = "FIXTUREHASH",
            phoneCapital = phoneCap).state)
        // wire format 4 fields written by Python: news phase, calendar time, capital snapshot (digest only)
        assertEquals(4, a.wireFormat)
        assertEquals("CLEAR", a.newsPhase)
        assertEquals(1791968400000L, a.newsVerifiedMs)
        assertEquals(3, a.capitalVersion)
        assertEquals(1791964800000L, a.capitalTimeMs)
        assertEquals("577ceeadaab51850", a.capitalDigest)
        assertEquals("OWNER", a.specKind)
        assertFalse("the relay text never carries the equity amount",
            Regex("""(?<![0-9.])500(\.0+)?(?![0-9])""").containsMatchIn(body) || body.contains("EQ="))
        // the PC sized from $500; a phone set to $25 sees the mismatch without either amount being sent
        val other = Assess.assess(a, a.receivedAtMs, okLot, watch, expectedHash = "FIXTUREHASH",
            phoneCapital = Capital.digest(code, 25.0))
        assertEquals(Assess.UNVERIFIED, other.state)
        assertTrue(other.reasons.any { it.startsWith(Capital.MISMATCH) })
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

    private fun pcAlert(status: String, extra: String = "", blk: String = "NONE", keys: String = v4()): AyeshaAlert {
        val bar = t0 - 60_000
        val body = "AYESHA BUY OANDA:EURUSD TF=15 E=1.08120 SL=1.07940 TP=1.08610 RR=2.55 LOT=0.02 EXP=0 SRC=PDL TGT=ASIA_H " +
            "BAR=$bar ST=$status FROM=PC ID=0123456789abcdef EXPU=${bar + 8 * 900_000L} BLK=$blk $extra $keys V=${StrategyInfo.HASH}"
        return AlertParser.parse(body, t0, signatureOk = true)!!
    }

    @Test
    fun pcWatchIsItsOwnStateNeverAnEntry() {
        val w = Assess.assess(pcAlert("WATCH", "MTF=H4:UP,M5:PENDING"), t0, okLot, watch, phoneCapital = phoneCap)
        assertEquals(Assess.WATCH, w.state)
        assertFalse(w.actionable)
        assertTrue(w.active)
        assertTrue(w.reasons.single().contains("M5"))
        assertEquals(Assess.READY, Assess.assess(pcAlert("READY"), t0, okLot, watch, phoneCapital = phoneCap).state)
    }

    @Test
    fun onlyForwardStatusChangesMayReplaceAStoredSignal() {
        assertTrue(Transitions.allowed("WATCH", "READY"))
        assertTrue(Transitions.allowed("WATCH", "NO_TRADE"))
        assertTrue(Transitions.allowed("READY", "NO_TRADE"))  // INVALIDATED before entry (e.g. new news lockout)
        assertFalse(Transitions.allowed("READY", "WATCH"))   // replayed older message
        assertFalse(Transitions.allowed("READY", "READY"))   // duplicate
        assertFalse(Transitions.allowed("NO_TRADE", "READY")) // a block is never lifted
        assertFalse(Transitions.allowed("NO_TRADE", "WATCH"))
    }

    // --- 0.5.0 app: News Intelligence + Adaptive Capital (News spec v1.0, N11 / C09 / I-tests) ----------

    @Test
    fun capitalDigestMatchesPythonVector() {
        // same vectors as desktop/tests/test_news_capital.py (C09)
        assertEquals("577ceeadaab51850", Capital.digest(code, 500.0))
        assertEquals("98cf4ff9f4e20de8", Capital.digest(code, 25.0))
        assertEquals(Capital.digest(code, 25.0), Capital.digest("abcdefghjkmnpqrs", 25.0)) // same code, any typing
        assertNull(Capital.digest("not-a-code", 25.0))
        assertNull(Capital.digest(code, 0.0))
        assertNull(Capital.digest(code, Double.NaN))
        assertEquals(Capital.OK, Capital.compare("577ceeadaab51850", Capital.digest(code, 500.0)))
        assertEquals(Capital.MISMATCH, Capital.compare("577ceeadaab51850", Capital.digest(code, 500.01)))
        assertEquals(Capital.UNVERIFIED, Capital.compare("", Capital.digest(code, 500.0)))
        assertEquals(Capital.UNVERIFIED, Capital.compare("577ceeadaab51850", null))
    }

    @Test
    fun pcReadyNeedsWireFormat4FreshNewsAndMatchingCapital() {
        fun st(a: AyeshaAlert, cap: String? = phoneCap) = Assess.assess(a, t0, okLot, watch, phoneCapital = cap)
        assertEquals(Assess.READY, st(pcAlert("READY")).state)
        // an older PC (no wire format 4 keys) can no longer produce READY on this app
        assertEquals(Assess.UNVERIFIED, st(pcAlert("READY", keys = "")).state)
        // capital: mismatch, missing digest, stale PC snapshot, no phone equity
        assertTrue(st(pcAlert("READY"), Capital.digest(code, 30.0)).reasons.any { it.startsWith(Capital.MISMATCH) })
        assertEquals(Assess.UNVERIFIED, st(pcAlert("READY", keys = v4(caph = null))).state)
        assertEquals(Assess.UNVERIFIED, st(pcAlert("READY", keys = v4(capT = t0 - 25 * 3_600_000L))).state)
        assertEquals(Assess.UNVERIFIED, st(pcAlert("READY"), null).state)
        // news: stale calendar, a READY that claims a blocking phase, assumed broker spec, risk above 1 %
        assertEquals(Assess.UNVERIFIED, st(pcAlert("READY", keys = v4(nv = t0 - 25 * 3_600_000L))).state)
        for (np in listOf("PRE_EVENT_LOCKOUT", "EVENT_LIVE", "POST_EVENT_COOLDOWN", "REACTION_WATCH", "NEWS_UNVERIFIED", "")) {
            assertEquals(np, Assess.UNVERIFIED, st(pcAlert("READY", keys = v4(np = np))).state)
        }
        assertEquals(Assess.READY, st(pcAlert("READY", keys = v4(np = "UPCOMING"))).state)
        assertEquals(Assess.UNVERIFIED, st(pcAlert("READY", keys = v4(spec = "ASSUMED"))).state)
        assertEquals(Assess.UNVERIFIED, st(pcAlert("READY", keys = v4(riskp = "1.5"))).state)
        // a PC NO_TRADE stays NO_TRADE with its own reasons (no capital noise on an archived block)
        assertEquals(Assess.NO_TRADE, st(pcAlert("NO_TRADE", blk = "NEWS_PRE_EVENT_LOCKOUT", keys = v4(np = "PRE_EVENT_LOCKOUT")), null).state)
    }

    @Test
    fun invalidatedReadyIsNoTradeAndCancelled() {
        val inv = pcAlert("NO_TRADE", blk = "INVALIDATED,NEWS_LOCKOUT_BEFORE_EXPIRY", keys = v4(np = "UPCOMING"))
        assertTrue(inv.isInvalidated)
        assertFalse(pcAlert("READY").isInvalidated)
        val r = Assess.assess(inv, t0, okLot, watch, phoneCapital = phoneCap)
        assertEquals(Assess.NO_TRADE, r.state)
        assertFalse(r.actionable)
        assertTrue(r.reasons.first().contains("INVALIDATED"))
    }

    private fun newsFixture(): String {
        val f = listOf("../../contracts/fixtures/pc-news-lockout.txt", "../contracts/fixtures/pc-news-lockout.txt",
            "contracts/fixtures/pc-news-lockout.txt").map { java.io.File(it) }.first { it.exists() }
        return f.readText()
    }

    @Test
    fun parsesPythonNewsNoticeAndItIsNeverATradeSignal() {
        val msg = newsFixture()
        val body = Signer.verify(code, msg)
        assertNotNull("Python-signed news notice must verify in Kotlin", body)
        val n = News.parse(body!!, 1792064710000L + 5_000)!!
        assertEquals("4d591d3541bb", n.eventId)
        assertEquals("USD", n.currency)
        assertEquals("TOP_DATA", n.tier)
        assertEquals("PRE_EVENT_LOCKOUT", n.phase)
        assertEquals(News.PROTECTION, n.category)
        assertEquals(listOf("EURUSD", "USDJPY"), n.pairs)
        assertEquals(1792064700000L, n.windowStartMs)
        assertEquals(1792069200000L, n.windowEndMs)
        assertEquals("CPI m/m", n.title)
        assertTrue(n.scenario.contains("Not a prediction"))
        assertEquals("NA", n.settled)
        // never a trade instruction
        for (bad in listOf("BUY NOW", "SELL NOW", "BUY ", "SELL ")) assertFalse(bad, body.contains(bad))
        // a news notice is not an alert: the alert parser ignores it
        assertNull(AlertParser.parse(body, 1792064710000L))
        // malformed / future notices are dropped
        assertNull(News.parse(body.replace("PH=PRE_EVENT_LOCKOUT", "PH=BUY"), 1792064710000L))
        assertNull(News.parse(body.replace("WS=1792064700000", "WS=1792069300000"), 1792064710000L)) // start after end
        assertNull(News.parse(body, 1792064710000L - 3_600_000L)) // sent "in the future" for this phone
        assertNull(News.parse(body.replace("PAIRS=EURUSD,USDJPY", "PAIRS=x"), 1792064710000L))
        assertEquals(News.ALERT, News.category("UPCOMING"))
        assertEquals(News.REACTION, News.category("WINDOW_END"))
    }

    @Test
    fun pcNewsWindowBlocksTvCandidatesAndPcReady() {
        val n = News.parse(Signer.verify(code, newsFixture())!!, 1792064710000L + 5_000)!!
        val ws = n.windowStartMs
        val we = n.windowEndMs
        // inside the window, for a listed pair
        assertEquals(n, News.block(listOf(n), "EURUSD", ws + 60_000))
        assertNull(News.block(listOf(n), "GBPJPY", ws + 60_000))
        // a setup valid into the window is blocked before the window starts (NEWS_LOCKOUT_BEFORE_EXPIRY)
        assertEquals(n, News.block(listOf(n), "USDJPY", ws - 30 * 60_000L, ws + 60_000))
        assertNull(News.block(listOf(n), "USDJPY", ws - 3 * 3_600_000L, ws - 2 * 3_600_000L))
        assertTrue(News.blockReason(n, ws - 60_000).startsWith("NEWS_LOCKOUT_BEFORE_EXPIRY"))
        assertTrue(News.blockReason(n, ws + 60_000).startsWith("NEWS_LOCKOUT"))
        // after the window: still blocked for 30 min unless the PC said the market settled
        assertEquals(n, News.block(listOf(n), "EURUSD", we + 10 * 60_000L))
        assertTrue(News.blockReason(n, we + 60_000).startsWith("POST_NEWS_NOT_CONFIRMED"))
        assertNull(News.block(listOf(n), "EURUSD", we + News.POST_WINDOW_MS))
        val settled = n.copy(phase = "WINDOW_END", settled = "Y", sentMs = we + 11 * 60_000L)
        assertNull(News.block(listOf(n, settled), "EURUSD", we + 12 * 60_000L))
        // the assessment turns a chart candidate (and a PC READY) into NO_TRADE with the reason
        val tvA = AlertParser.parse(tv().raw.replace("BAR=${t0 - 60_000}", "BAR=${ws - 60_000}"), ws)!!
        val r = Assess.assess(tvA, ws + 60_000, okLot, watch, newsBlock = News.block(listOf(n), "EURUSD", ws + 60_000))
        assertEquals(Assess.NO_TRADE, r.state)
        assertTrue(r.reasons.any { it.startsWith("NEWS_LOCKOUT") })
        val pcR = Assess.assess(pcAlert("READY"), t0, okLot, watch, phoneCapital = phoneCap, newsBlock = n)
        assertEquals(Assess.NO_TRADE, pcR.state)
        // only stale notices are stored silently (no late notification)
        assertTrue(News.worthNotifying(n, ws))
        assertFalse(News.worthNotifying(n, we + News.POST_WINDOW_MS + 1))
        assertEquals(listOf(n), News.current(listOf(n), ws - 3_600_000L))
        assertTrue(News.current(listOf(n), we + 3 * 3_600_000L).isEmpty())
    }

    @Test
    fun newsTextIsInformationOnly() {
        val n = News.parse(Signer.verify(code, newsFixture())!!, 1792064710000L + 5_000)!!
        val hhmm = { ms: Long -> (ms / 60_000L % 1440).let { String.format(java.util.Locale.US, "%02d:%02d", it / 60, it % 60) } }
        val texts = listOf(News.title(n, n.windowStartMs), News.title(n.copy(phase = "UPCOMING"), 0L),
            News.title(n.copy(phase = "RELEASED"), n.eventMs), News.title(n.copy(phase = "WINDOW_END", settled = "N"), 0L)) +
            News.lines(n, hhmm) + News.lines(n.copy(phase = "WINDOW_END", reactionState = "WHIPSAW"), hhmm)
        for (t in texts) {
            for (bad in listOf("BUY", "SELL", "এখনই কিনুন", "এখনই বেচুন")) assertFalse("$bad in $t", t.contains(bad))
        }
        assertTrue(News.title(n, n.windowStartMs).contains("45 মিনিট পরে"))
        assertTrue(News.lines(n, hhmm).any { it.contains("ট্রেড সিগন্যাল নয়") })
        assertTrue(News.lines(n, hhmm).any { it.contains("ভবিষ্যদ্বাণী নয়") })
        assertTrue(News.lines(n, hhmm).first().contains("11:45–13:00")) // UTC formatter in this test
    }

    @Test
    fun pcLotIsNeverExceededOnThePhone() {
        val own = LotCalc.calc("EURUSD", 1.08120, 1.07940, 5000.0, 0.5, "Standard", 0.8, 0.3) // 0.13 lot
        val capped = LotCalc.capToPc(own, 0.05) // PC: less left in today's budget
        assertEquals(0.05, capped.lot, 1e-9)
        assertEquals(own.maxLossUsd * 0.05 / own.lot, capped.maxLossUsd, 1e-9)
        assertEquals(own, LotCalc.capToPc(own, 0.20))  // never raised above the phone's own sizing
        assertEquals(own, LotCalc.capToPc(own, 0.0))   // no PC lot: keep the phone's
        val blocked = LotCalc.blocked("CAPITAL_STALE: x")
        assertFalse(blocked.ok)
        assertEquals(0.0, blocked.lot, 0.0)
        assertEquals(blocked, LotCalc.capToPc(blocked, 0.05))
    }

    @Test
    fun heartbeatCarriesPcCapitalStatus() {
        val hb = Heartbeat.parse("AYESHA HB T=1760000000000 STATE=OK PAIRS=6 V=abc123def456 CAP=STALE")!!
        assertEquals("STALE", hb.capital)
        assertEquals(6, hb.pairs)
        assertEquals("", Heartbeat.parse("AYESHA HB T=1760000000000 STATE=OK PAIRS=5 V=abc123def456")!!.capital)
    }

    @Test
    fun phoneEquityMustBeConfirmedWithinADay() {
        val now = t0
        assertTrue(Capital.isStale(0L, now))                          // never confirmed (fresh install or restored backup)
        assertFalse(Capital.isStale(now - 3_600_000L, now))
        assertTrue(Capital.isStale(now - 25 * 3_600_000L, now))
        assertTrue(Capital.isStale(now + 3_600_000L, now))            // clock problem
        assertNotNull(Capital.lotBlock(0L, now, pcDigestMatches = false))
        assertNull(Capital.lotBlock(0L, now, pcDigestMatches = true))  // equals the PC's fresh snapshot
        assertNull(Capital.lotBlock(now - 60_000, now, pcDigestMatches = false))
        // equity is typed like the PC accepts it: at most 2 decimals
        assertTrue(SettingsCheck.problems(25.555, 0.5, 0.8, 0.3).isNotEmpty())
        assertTrue(SettingsCheck.problems(25.4, 0.5, 0.8, 0.3).isEmpty())
        assertTrue(SettingsCheck.problems(1234.56, 0.5, 0.8, 0.3).isEmpty())
    }

    @Test
    fun sameCodeLotFollowsEquityUpAndDown() {
        // capital is a variable: the same 18-pip EURUSD setup at $25, $500 and $5,000, risk 0.5 %
        val at25 = LotCalc.calc("EURUSD", 1.08120, 1.07940, 25.0, 0.5, "Standard", 0.8, 0.3)
        val at500 = LotCalc.calc("EURUSD", 1.08120, 1.07940, 500.0, 0.5, "Standard", 0.8, 0.3)
        val at5000 = LotCalc.calc("EURUSD", 1.08120, 1.07940, 5000.0, 0.5, "Standard", 0.8, 0.3)
        assertEquals(LotCalc.NO_TRADE_MIN_LOT, at25.status)
        assertTrue(at500.ok && at5000.ok)
        assertEquals(0.01, at500.lot, 1e-9)
        assertEquals(0.13, at5000.lot, 1e-9)
        assertEquals(2.5, at500.budgetUsd, 1e-9)
        assertEquals(25.0, at5000.budgetUsd, 1e-9)
        assertTrue(at5000.maxLossUsd <= at5000.budgetUsd + 1e-9)
        // falling back to $25 makes the same setup NO TRADE again; the percentage never changed
        assertEquals(at25.status, LotCalc.calc("EURUSD", 1.08120, 1.07940, 25.0, 0.5, "Standard", 0.8, 0.3).status)
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
