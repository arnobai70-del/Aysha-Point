package com.ayesha.fx

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.format.DateFormat
import android.widget.LinearLayout
import android.widget.Toast
import com.ayesha.fx.core.AlertParser
import com.ayesha.fx.core.Assess
import com.ayesha.fx.core.Capital
import com.ayesha.fx.core.LinkHealth
import com.ayesha.fx.core.LotCalc
import com.ayesha.fx.core.News
import com.ayesha.fx.core.SettingsCheck
import com.ayesha.fx.core.StrategyInfo
import java.util.Date
import java.util.Locale

/** Home: setup status, capital, news watch, PC link health, diagnostics and the alert inbox (active / archive). */
class MainActivity : Activity() {
    private lateinit var col: LinearLayout
    private var showArchive = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = "AYESHA FX"
        val (sv, c) = Ui.screen(this)
        col = c
        setContentView(sv)
        Notifier.ensureChannel(this)
        if (Build.VERSION.SDK_INT >= 33 && !Notifier.canPost(this)) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        LinkService.start(this)
    }

    override fun onResume() {
        super.onResume()
        render()
    }

    private fun ago(ms: Long): String {
        if (ms <= 0) return "কখনো না"
        val m = (System.currentTimeMillis() - ms) / 60_000
        return when {
            m < 1 -> "এইমাত্র"
            m < 120 -> "$m মিনিট আগে"
            else -> "${m / 60} ঘণ্টা আগে"
        }
    }

    private fun hhmm(ms: Long): String = DateFormat.format("HH:mm", Date(ms)).toString()

    private fun render() {
        col.removeAllViews()
        val prefs = Prefs(this)
        val listener = AlertListener.isEnabled(this)
        val notif = Notifier.canPost(this)
        val now = System.currentTimeMillis()
        val entries = AlertStore(this).all()
        val notices = NewsStore(this).all()

        val status = Ui.card(this, if (listener && notif) Ui.BULL else Ui.WATCH)
        status.addView(Ui.text(this, "অবস্থা", 13f, Ui.MUTED))
        status.addView(Ui.text(this, (if (listener) "✅" else "⚠️") + " TradingView নোটিফিকেশন পড়ার অনুমতি", 15f))
        status.addView(Ui.text(this, (if (notif) "✅" else "⚠️") + " AYESHA নোটিফিকেশন দেখানোর অনুমতি", 15f))
        val bad = SettingsCheck.problems(prefs.equityUsd, prefs.riskPercent, prefs.spreadPips, prefs.slippagePips)
        if (bad.isNotEmpty()) {
            status.addView(Ui.text(this, "⚠️ Settings ঠিক নেই, তাই কোনো লট দেখানো হবে না: " + bad.joinToString("; "), 14f, Ui.WATCH, bold = true))
        }
        if (now < prefs.pausedUntilMs) {
            status.addView(Ui.text(this, "⏸ অ্যালার্ট বন্ধ আছে", 14f, Ui.WATCH, bold = true))
        }
        if (!listener) {
            status.addView(Ui.button(this, "অনুমতি দিন (Notification access)", Ui.WATCH) {
                startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
            })
            status.addView(Ui.text(this,
                "এই অনুমতিতে অ্যাপ ফোনের নোটিফিকেশন দেখতে পায়, কিন্তু শুধু TradingView-এর AYESHA অ্যালার্ট রাখে; বাকি সব সাথে সাথে বাদ দেয়, কোথাও পাঠায় না। " +
                    "\"Restricted setting\" দেখালে: Settings → Apps → AYESHA FX → ⋮ → Allow restricted settings।",
                12f, Ui.MUTED))
        }
        if (!notif && Build.VERSION.SDK_INT >= 33) {
            status.addView(Ui.button(this, "নোটিফিকেশন চালু করুন", Ui.WATCH) {
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
            })
        }
        col.addView(status)

        // Capital: the owner's Exness equity sizes every lot. It is a variable (it grows or falls), so it must be
        // confirmed at least once a day, here and on the PC (`ayesha capital`). It never leaves the phone.
        val capStale = Capital.isStale(prefs.equitySetMs, now)
        val cap = Ui.card(this, if (capStale) Ui.WATCH else Ui.BULL)
        cap.addView(Ui.text(this, "💰 Capital (আপনার Exness equity)", 13f, Ui.MUTED))
        val budget = prefs.equityUsd * prefs.riskPercent / 100.0
        cap.addView(Ui.text(this, String.format(Locale.US, "Equity \$%.2f · risk %.2f%% → প্রতি ট্রেডে সর্বোচ্চ ঝুঁকি \$%.2f",
            prefs.equityUsd, prefs.riskPercent, budget), 15f, bold = true))
        cap.addView(Ui.text(this, "Exness ${prefs.accountType} · শেষ নিশ্চিত: ${ago(prefs.equitySetMs)}", 12f, Ui.MUTED))
        if (capStale) {
            cap.addView(Ui.text(this, "⚠️ ২৪ ঘণ্টার মধ্যে নিশ্চিত করা হয়নি: Exness অ্যাপ → Accounts দেখে Update capital করুন। " +
                "ততক্ষণ ফোন কোনো লট দেখাবে না।", 13f, Ui.WATCH))
        }
        // what the 0.01 minimum lot means at this equity (why a small Standard account often gets NO TRADE)
        val probe = LotCalc.calc("EURUSD", 1.10000, 1.09850, prefs.equityUsd, prefs.riskPercent, prefs.accountType,
            prefs.spreadPips, prefs.slippagePips)
        if (probe.status == LotCalc.NO_TRADE_MIN_LOT) {
            cap.addView(Ui.text(this, String.format(Locale.US,
                "এই equity-তে EURUSD-এ 15 pip SL হলে 0.01 লটের ঝুঁকি \$%.2f (equity-র %.1f%%), সীমা \$%.2f। তাই বেশিরভাগ " +
                    "সিগন্যাল NO TRADE হবে; এটা সুরক্ষা। equity বাড়লে একই নিয়মে লট নিজে থেকেই হিসাব হবে।",
                probe.minLotLossUsd, probe.minLotLossPercent, probe.budgetUsd), 12f, Ui.MUTED))
        } else if (probe.ok) {
            cap.addView(Ui.text(this, String.format(Locale.US, "উদাহরণ: EURUSD-এ 15 pip SL হলে লট %.2f (সর্বোচ্চ লস \$%.2f)।",
                probe.lot, probe.maxLossUsd), 12f, Ui.MUTED))
        }
        if (prefs.linkEnabled) {
            val lastPc = entries.firstOrNull { it.alert.isPc && it.alert.wireFormat >= Assess.MIN_WIRE_FORMAT && it.alert.capitalDigest.isNotBlank() }?.alert
            val cmp = lastPc?.let { Capital.compare(it.capitalDigest, prefs.capitalDigest()) }
            cap.addView(Ui.text(this, when (cmp) {
                null -> "PC-র সাথে এখনো মিলানো যায়নি (PC 0.8.0 থেকে সিগন্যাল এলে দেখাবে)।"
                Capital.OK -> "✅ শেষ PC সিগন্যালের equity-র সাথে মিল আছে।"
                Capital.MISMATCH -> "⚠️ CAPITAL_MISMATCH: শেষ PC সিগন্যাল অন্য equity দিয়ে হিসাব করা। PC-তে `ayesha capital` আর এখানে " +
                    "একই সংখ্যা লিখুন; ততক্ষণ PC READY যাচাইহীন থাকবে।"
                else -> "⚠️ PC বা ফোনের equity যাচাই করা যায়নি।"
            }, 12f, if (cmp == Capital.OK) Ui.MUTED else Ui.WATCH))
            if (prefs.hbCapital.isNotBlank() && prefs.hbCapital != "OK") {
                cap.addView(Ui.text(this, "⚠️ PC-র capital অবস্থা: ${prefs.hbCapital}। PC-তে `ayesha capital` চালিয়ে Exness equity আর খোলা ট্রেড লিখুন।", 12f, Ui.WATCH))
            }
        }
        cap.addView(Ui.row(this,
            Ui.button(this, "✏️ Update capital", Ui.SKY) { startActivity(Intent(this, SettingsActivity::class.java)) },
            Ui.button(this, "✅ একই আছে", Ui.OFF) {
                prefs.equitySetMs = System.currentTimeMillis()
                Toast.makeText(this, "Equity নিশ্চিত করা হলো", Toast.LENGTH_SHORT).show()
                render()
            },
        ))
        cap.addView(Ui.text(this, "\"একই আছে\" চাপুন শুধু Exness অ্যাপে equity দেখে নেওয়ার পরে। ডিপোজিট বা উইথড্র লাভ-ক্ষতি নয়; " +
            "সংখ্যা বদলালে Update capital করুন। equity ফোন থেকে কোথাও যায় না।", 11f, Ui.MUTED))
        col.addView(cap)

        // News watch from the PC: information and protection status, never trade signals.
        val current = News.current(notices, now)
        val newsActive = current.any { now >= it.windowStartMs && now < it.windowEndMs }
        val nc = Ui.card(this, if (newsActive) Ui.BEAR else Ui.OFF)
        nc.addView(Ui.text(this, "📰 নিউজ (PC থেকে · ট্রেড সিগন্যাল নয়)", 13f, Ui.MUTED))
        if (!prefs.linkEnabled) {
            nc.addView(Ui.text(this, "PC link বন্ধ, তাই নিউজের খবর আসবে না। TradingView ক্যান্ডিডেট নেওয়ার আগে ForexFactory calendar নিজে দেখুন।", 13f))
        } else if (current.isEmpty()) {
            nc.addView(Ui.text(this, "সামনে বড় নিউজের কোনো খবর PC পাঠায়নি। PC চালু থাকলে লকআউটের প্রায় ১ ঘণ্টা আগে জানায়।", 13f))
        }
        for (n in current) {
            val phaseText = when {
                now < n.windowStartMs -> "আসছে · লকআউট ${hhmm(n.windowStartMs)} থেকে"
                now < n.windowEndMs -> "⛔ লকআউট চলছে (${hhmm(n.windowEndMs)} পর্যন্ত), নতুন ট্রেড বন্ধ"
                n.settled == "Y" -> "✅ উইন্ডো শেষ, PC বলছে বাজার শান্ত"
                else -> "⏳ উইন্ডো শেষ; বাজার শান্ত হওয়ার অপেক্ষা"
            }
            nc.addView(Ui.text(this, "${hhmm(n.eventMs)} ${n.currency} ${n.title} · ${n.impact}/${n.tier}", 14f, bold = true))
            nc.addView(Ui.text(this, "$phaseText · ${n.pairs.joinToString(" ")}" +
                (if (n.eventState != "SCHEDULED") " · ${n.eventState}" else ""), 12f,
                if (now >= n.windowStartMs && now < n.windowEndMs) Ui.WATCH else Ui.MUTED))
            if (n.category == News.REACTION) {
                nc.addView(Ui.text(this, "প্রতিক্রিয়া: ${News.reactionLabel(n.reactionState)}", 12f, Ui.MUTED))
            } else if (n.scenario.isNotBlank()) {
                nc.addView(Ui.text(this, "শর্তসাপেক্ষ, ভবিষ্যদ্বাণী নয়: ${n.scenario}", 11f, Ui.MUTED))
            }
        }
        col.addView(nc)

        // PC link health: the owner must be able to see when the PC scanner is off or its data is stale.
        val link = Ui.card(this, if (!prefs.linkEnabled) Ui.OFF else Ui.SKY)
        link.addView(Ui.text(this, "PC scanner লিংক", 13f, Ui.MUTED))
        if (!prefs.linkEnabled) {
            link.addView(Ui.text(this, "বন্ধ। চালু করতে Settings → PC link (ঐচ্ছিক)।", 14f))
        } else {
            // Judged by the PC's own heartbeat time: a replayed old heartbeat cannot make the PC look online.
            val pcText = when (LinkHealth.status(prefs.hbPcMs, prefs.hbState, now)) {
                LinkHealth.NONE -> "⚠️ PC থেকে এখনো কিছু আসেনি"
                LinkHealth.STOPPED -> "⏹ PC scanner বন্ধ করা হয়েছে (${ago(prefs.hbPcMs)})"
                LinkHealth.OFFLINE -> "⚠️ PC অফলাইন: শেষ খবর ${ago(prefs.hbPcMs)}। এই সময়ে PC সিগন্যাল আসবে না।"
                LinkHealth.ONLINE -> "✅ PC চলছে, ডেটা ঠিক আছে (${ago(prefs.hbPcMs)})"
                LinkHealth.TEST -> "✅ PC test পাওয়া গেছে (${ago(prefs.hbPcMs)})"
                else -> "⚠️ PC চলছে কিন্তু ডেটা সমস্যা: ${prefs.hbState} (${ago(prefs.hbPcMs)})। এখন READY আসবে না।"
            }
            link.addView(Ui.text(this, pcText, 15f))
            if (prefs.hbRecvMs > 0 && kotlin.math.abs(prefs.hbRecvMs - prefs.hbPcMs) > 5 * 60_000L &&
                now - prefs.hbRecvMs < LinkHealth.OFFLINE_AFTER_MS) {
                link.addView(Ui.text(this, "⚠️ PC আর ফোনের ঘড়িতে ৫ মিনিটের বেশি পার্থক্য। দুটোতেই \"automatic time\" চালু করুন।", 12f, Ui.WATCH))
            }
            link.addView(Ui.text(this, "ফোনের সংযোগ: ${prefs.linkState} · ${ago(prefs.linkStateMs)}", 12f, Ui.MUTED))
            if (prefs.hbVersion.isNotBlank() && prefs.hbVersion != StrategyInfo.HASH) {
                link.addView(Ui.text(this, "⚠️ PC আর অ্যাপের strategy version আলাদা (${prefs.hbVersion} ≠ ${StrategyInfo.HASH})। দুটোই আপডেট করুন; ততক্ষণ PC সিগন্যাল UNVERIFIED।", 13f, Ui.WATCH))
            }
        }
        col.addView(link)

        val diag = Ui.card(this, Ui.OFF)
        diag.addView(Ui.text(this, "Diagnostics", 13f, Ui.MUTED))
        diag.addView(Ui.text(this, "শেষ TradingView AYESHA নোটিফিকেশন: ${ago(prefs.lastTvSeenMs)}", 13f))
        diag.addView(Ui.text(this, "বাতিল বার্তা: ${prefs.rejectedCount}" + (if (prefs.lastRejectReason.isNotBlank()) " (শেষ: ${prefs.lastRejectReason})" else ""), 13f))
        diag.addView(Ui.text(this, "Strategy ${StrategyInfo.VERSION} #${StrategyInfo.HASH} · ${StrategyInfo.SETUP_TF}m · watchlist ${prefs.watchlist.sorted().joinToString(" ")}", 12f, Ui.MUTED))
        col.addView(diag)

        col.addView(Ui.row(this,
            Ui.button(this, "⚙️ Settings") { startActivity(Intent(this, SettingsActivity::class.java)) },
            Ui.button(this, "📒 জার্নাল", Ui.SKY) { startActivity(Intent(this, JournalActivity::class.java)) },
            Ui.button(this, "🧪 Test", Ui.OFF) {
                val t = System.currentTimeMillis()
                AlertListener.handle(this, AlertParser.sample(t), t, isTest = true)
                Toast.makeText(this, "Test alert পাঠানো হয়েছে", Toast.LENGTH_SHORT).show()
                render()
            },
        ))

        val judged = entries.map { it to Notifier.assess(this, it.alert, now, notices) }
        val active = judged.filter { it.second.active }
        val archive = judged.filter { !it.second.active }
        col.addView(Ui.row(this,
            Ui.button(this, "সক্রিয় (${active.size})", if (!showArchive) Ui.SKY else Ui.OFF) { showArchive = false; render() },
            Ui.button(this, "আর্কাইভ (${archive.size})", if (showArchive) Ui.SKY else Ui.OFF) { showArchive = true; render() },
        ))
        val list = if (showArchive) archive else active
        if (list.isEmpty()) {
            col.addView(Ui.text(this,
                if (showArchive) "আর্কাইভ খালি। মেয়াদ শেষ, NO TRADE বা যাচাই না হওয়া সিগন্যাল এখানে কারণসহ থাকে।"
                else "এখন কোনো সক্রিয় সিগন্যাল নেই। কোনো দিন সিগন্যাল না আসাও স্বাভাবিক।", 14f, Ui.MUTED))
        }
        for ((e, v) in list) {
            val a = e.alert
            val accent = when (v.state) {
                Assess.READY -> Ui.BULL
                Assess.CHART_CANDIDATE -> if (a.isBuy) Ui.SKY else Ui.BEAR
                Assess.NO_TRADE -> Ui.BEAR
                Assess.WATCH -> Ui.WATCH
                else -> Ui.OFF
            }
            val card = Ui.card(this, accent)
            val icon = if (a.isBuy) "🟢" else "🔴"
            card.addView(Ui.text(this, "$icon ${a.direction} ${a.ticker} · ${Notifier.stateLabel(v.state)}" +
                (if (a.isPc) " · PC" else " · TV") + (if (a.isTest) " · TEST" else ""), 16f, bold = true))
            card.addView(Ui.text(this, "Entry ${a.fmt(a.entry)} · SL ${a.fmt(a.stop)} · TP ${a.fmt(a.target)}", 14f))
            if (!v.actionable) card.addView(Ui.text(this, v.reasons.joinToString("; "), 12f, Ui.WATCH))
            val mtf = com.ayesha.fx.core.Mtf.summary(a.mtf, a.isBuy)
            if (mtf.isNotEmpty()) card.addView(Ui.text(this, "MTF: $mtf", 12f, Ui.MUTED))
            val time = DateFormat.format("dd MMM HH:mm", Date(a.signalTimeMs))
            val user = when (e.userStatus) {
                "TAKEN" -> " · ট্রেড নিয়েছি"
                "SKIPPED" -> " · বাদ দিয়েছি"
                else -> ""
            }
            card.addView(Ui.text(this, "$time · ${a.source} sweep → MSS → FVG$user", 12f, Ui.MUTED))
            card.setOnClickListener {
                startActivity(Intent(this, DetailActivity::class.java).putExtra(DetailActivity.EXTRA_ID, a.id))
            }
            col.addView(card)
        }
        val help = Ui.card(this, Ui.OFF)
        help.addView(Ui.text(this, "অবস্থাগুলোর মানে", 13f, Ui.MUTED))
        for (s in listOf(Assess.READY, Assess.WATCH, Assess.CHART_CANDIDATE, Assess.NO_TRADE, Assess.UNVERIFIED, Assess.EXPIRED)) {
            help.addView(Ui.text(this, "${Notifier.stateLabel(s)}: ${Notifier.stateMeaning(s)}", 12f))
        }
        help.addView(Ui.text(this, "নোটিফিকেশন আসে শুধু READY আর চার্ট ক্যান্ডিডেটের জন্য। WATCH থেকে READY হলে আবার জানাবে; " +
            "PC কোনো READY বাতিল করলে (যেমন নতুন নিউজ লকআউট) \"⛔ বাতিল\" নোটিফিকেশন আসবে।", 12f, Ui.MUTED))
        help.addView(Ui.text(this, "নিউজ নোটিফিকেশন আলাদা: 📰 আসছে (তথ্য), ⛔ প্রোটেকশন (নতুন ট্রেড বন্ধ), 📊 নিউজের পরে (বাজারের প্রতিক্রিয়া)। " +
            "কোনোটাই কেনা-বেচার নির্দেশ নয়।", 12f, Ui.MUTED))
        col.addView(help)

        if (entries.any { it.alert.isTest }) {
            col.addView(Ui.button(this, "Test alert গুলো মুছুন", Ui.OFF) {
                AlertStore(this).clearTests()
                render()
            })
        }
        col.addView(Ui.text(this, String.format(Locale.US, "AYESHA FX %s · কখনো অর্ডার দেয় না", BuildConfigInfo.versionName(this)), 11f, Ui.MUTED))
    }
}

object BuildConfigInfo {
    fun versionName(a: Activity): String = try {
        a.packageManager.getPackageInfo(a.packageName, 0).versionName ?: "?"
    } catch (e: Exception) {
        "?"
    }
}
