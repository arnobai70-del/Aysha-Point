package com.ayesha.fx

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.text.format.DateFormat
import android.widget.LinearLayout
import android.widget.Toast
import com.ayesha.fx.core.Assess
import com.ayesha.fx.core.LotCalc
import com.ayesha.fx.core.StrategyInfo
import java.util.Date
import java.util.Locale

/** Full signal details: levels, reasons, lot from the owner's settings, open TradingView. */
class DetailActivity : Activity() {
    companion object {
        const val EXTRA_ID = "id"
    }

    private lateinit var col: LinearLayout

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val (sv, c) = Ui.screen(this)
        col = c
        setContentView(sv)
    }

    override fun onResume() {
        super.onResume()
        render()
    }

    private fun f2(v: Double) = String.format(Locale.US, "%.2f", v)

    private fun render() {
        col.removeAllViews()
        val id = intent.getStringExtra(EXTRA_ID)
        val e = id?.let { AlertStore(this).get(it) }
        if (e == null) {
            col.addView(Ui.text(this, "সিগন্যাল পাওয়া যায়নি", 16f))
            return
        }
        val a = e.alert
        title = "${a.direction} ${a.ticker}"
        val now = System.currentTimeMillis()
        val expired = a.isExpired(now)
        val prefs = Prefs(this)

        val head = Ui.card(this, if (expired) Ui.OFF else if (a.isBuy) Ui.BULL else Ui.BEAR)
        head.addView(Ui.text(this, (if (a.isBuy) "🟢 " else "🔴 ") + "${a.direction} ${a.ticker}" + (if (a.isTest) " · TEST" else ""), 22f, bold = true))
        val sig = DateFormat.format("dd MMM yyyy HH:mm", Date(a.signalTimeMs))
        val exp = DateFormat.format("HH:mm", Date(a.expiresAtMs))
        head.addView(Ui.text(this, "চার্টে সিগন্যাল $sig · ${a.timeframe}m চার্ট", 13f, Ui.MUTED))
        if (a.isDelayed) {
            head.addView(Ui.text(this, "⚠️ ফোনে এসেছে ${(a.deliveryDelayMs ?: 0) / 60_000} মিনিট দেরিতে। দাম মিলিয়ে নিন।", 13f, Ui.WATCH))
        }
        head.addView(Ui.text(this,
            if (expired) "⌛ মেয়াদ শেষ ($exp)। এখন আর এই entry নেবেন না।" else "⏳ $exp পর্যন্ত বৈধ। দাম entry থেকে অনেক দূরে চলে গেলে পিছনে দৌড়াবেন না।",
            14f, if (expired) Ui.WATCH else Ui.TEXT))
        col.addView(head)

        // What was and was not checked, with the reasons. Never implies execution approval.
        val v = Notifier.assess(this, a, now)
        val gates = Ui.card(this, when (v.state) {
            Assess.READY -> Ui.BULL
            Assess.CHART_CANDIDATE -> Ui.WATCH
            else -> Ui.BEAR
        })
        gates.addView(Ui.text(this, "অবস্থা: ${Notifier.stateLabel(v.state)} · উৎস ${if (a.isPc) "PC scanner" + (if (a.signatureOk) " (সই ঠিক)" else " (সই নেই!)") else "TradingView চার্ট"}", 15f, bold = true))
        for (r in v.reasons) gates.addView(Ui.text(this, "• $r", 13f))
        if (v.state == Assess.CHART_CANDIDATE) {
            gates.addView(Ui.text(this,
                "✅ চার্টের নিয়ম: sweep → MSS → FVG, RR ≥ ${StrategyInfo.MIN_NET_RR} (আন্দাজি spread সহ)\n" +
                    "❌ বড় নিউজ যাচাই হয়নি — ForexFactory/Investing calendar দেখুন\n" +
                    "❌ Exness-এর আসল spread যাচাই হয়নি — অ্যাপে spread দেখুন\n" +
                    "❌ Exness-এর contract/লট নিয়ম যাচাই হয়নি — অ্যাপে লট মিলিয়ে নিন", 13f))
        }
        if (a.isPc && a.chartLot > 0) {
            gates.addView(Ui.text(this, "PC-র হিসাবে লট ${f2(a.chartLot)} (PC-র equity দিয়ে)। নিচের লট এই ফোনের settings দিয়ে; দুটো আলাদা হলে settings মিলিয়ে নিন।", 12f, Ui.MUTED))
        }
        if (a.isPc) {
            gates.addView(Ui.text(this, "PC-র দাম OANDA/MT5 feed থেকে; Exness-এর দাম সামান্য আলাদা হতে পারে।", 12f, Ui.MUTED))
        }
        gates.addView(Ui.text(this, "এটা ট্রেডের অনুমতি নয়। সিদ্ধান্ত আপনার, অর্ডার আপনি নিজে Exness অ্যাপে দেবেন।", 12f, Ui.MUTED))
        col.addView(gates)

        val lv = Ui.card(this, Ui.SKY)
        lv.addView(Ui.text(this, "লেভেল (TradingView চার্টের দাম)", 13f, Ui.MUTED))
        lv.addView(Ui.text(this, "Entry  ${a.fmt(a.entry)}", 18f, Ui.SKY, bold = true))
        lv.addView(Ui.text(this, "SL       ${a.fmt(a.stop)}", 18f, Ui.BEAR, bold = true))
        lv.addView(Ui.text(this, "TP       ${a.fmt(a.target)}  (${a.targetName})", 18f, Ui.BULL, bold = true))
        lv.addView(Ui.text(this, "RR ${f2(a.rr)} (আন্দাজি spread সহ)", 14f))
        col.addView(lv)

        val risk = Ui.card(this, Ui.WATCH)
        risk.addView(Ui.text(this, "লট (আপনার settings থেকে)", 13f, Ui.MUTED))
        val r = Notifier.lotFor(this, a)
        if (r.ok) {
            risk.addView(Ui.text(this, "Lot ${f2(r.lot)}  ·  সর্বোচ্চ লস \$${f2(r.maxLossUsd)}", 18f, bold = true))
            risk.addView(Ui.text(this, "Budget \$${f2(r.budgetUsd)} (${prefs.riskPercent}% of \$${prefs.equityUsd}) · SL ${String.format(Locale.US, "%.1f", r.stopPips)} pips", 13f, Ui.MUTED))
            if (r.rateSource == "CHART") {
                risk.addView(Ui.text(this, "এই পেয়ারের USD রেট TradingView চার্ট থেকে নেওয়া।", 12f, Ui.MUTED))
            }
        } else if (r.status == LotCalc.NO_TRADE_MIN_LOT) {
            risk.addView(Ui.text(this, "⛔ NO TRADE", 20f, Ui.BEAR, bold = true))
            risk.addView(Ui.text(this, "সবচেয়ে ছোট লট 0.01 নিলেও ঝুঁকি \$${f2(r.minLotLossUsd)} (equity-র ${String.format(Locale.US, "%.1f", r.minLotLossPercent)}%), " +
                "অথচ আপনার সীমা \$${String.format(Locale.US, "%.3f", r.budgetUsd)}।", 14f))
        } else {
            // Fail closed: no lot is shown when it cannot be verified (the chart's own estimate is not used).
            risk.addView(Ui.text(this, "⛔ " + Notifier.statusText(r), 18f, Ui.BEAR, bold = true))
            risk.addView(Ui.text(this, r.note + "। এই সিগন্যালে ট্রেড নেবেন না, অথবা Exness অ্যাপে নিজে হিসাব করুন।", 14f))
        }
        risk.addView(Ui.text(this, "Exness অ্যাপে আসল spread আর lot মিলিয়ে নিন। বড় নিউজের ৩০ মিনিট আগে-পরে ট্রেড নেবেন না।", 12f, Ui.MUTED))
        col.addView(risk)

        val why = Ui.card(this, Ui.OFF)
        why.addView(Ui.text(this, "কেন এই সিগন্যাল", 13f, Ui.MUTED))
        why.addView(Ui.text(this, "① ${a.source} liquidity sweep হয়েছে\n② উল্টো দিকে MSS (displacement সহ)\n③ FVG-তে entry zone\n④ Target: ${a.targetName}", 15f))
        if (a.why.isNotBlank()) why.addView(Ui.text(this, a.why, 12f, Ui.MUTED))
        why.addView(Ui.text(this,
            if (a.isPc) "TradingView-এর AYESHA indicator নিজে আলাদা হিসাব করে; PC-র লেভেলের সাথে চার্টের ①–④ হুবহু মিলবে এমন নিশ্চয়তা নেই (feed আলাদা হতে পারে)।"
            else "চার্টে ①–④ চিহ্নগুলো দেখতে নিচের বাটন চাপুন।", 12f, Ui.MUTED))
        col.addView(why)

        col.addView(Ui.button(this, "📈 TradingView-এ ${a.ticker} খুলুন", Ui.SKY) { openTradingView(a.tradingViewUrl()) })
        col.addView(Ui.button(this, "📋 লেভেল কপি করুন", Ui.OFF) {
            val cm = getSystemService(ClipboardManager::class.java)
            cm.setPrimaryClip(ClipData.newPlainText("AYESHA levels", a.levelsText()))
            Toast.makeText(this, "কপি হয়েছে", Toast.LENGTH_SHORT).show()
        })
        col.addView(Ui.row(this,
            Ui.button(this, "✅ ট্রেড নিয়েছি", Ui.BULL) { AlertStore(this).mark(a.id, "TAKEN"); render() },
            Ui.button(this, "✖ বাদ", Ui.OFF) { AlertStore(this).mark(a.id, "SKIPPED"); render() },
        ))
        col.addView(Ui.text(this, "এই অ্যাপ কখনো অর্ডার দেয় না। সিদ্ধান্ত আপনার।", 12f, Ui.MUTED))
    }

    private fun openTradingView(url: String) {
        val uri = Uri.parse(url)
        val app = Intent(Intent.ACTION_VIEW, uri).setPackage("com.tradingview.tradingviewapp")
        try {
            startActivity(app)
        } catch (ex: Exception) {
            try {
                startActivity(Intent(Intent.ACTION_VIEW, uri))
            } catch (ex2: Exception) {
                Toast.makeText(this, "TradingView খোলা গেল না", Toast.LENGTH_SHORT).show()
            }
        }
    }
}
