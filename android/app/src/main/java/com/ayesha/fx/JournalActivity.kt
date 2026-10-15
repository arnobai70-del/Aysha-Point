package com.ayesha.fx

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.text.format.DateFormat
import com.ayesha.fx.core.Journal
import java.util.Date
import java.util.Locale

/** The owner's REAL trades and their statistics. Signals, tests and backtests never appear here. */
class JournalActivity : Activity() {
    override fun onResume() {
        super.onResume()
        title = "জার্নাল"
        val (sv, col) = Ui.screen(this)
        setContentView(sv)
        val store = AlertStore(this)
        val trades = store.journal()
        val s = Journal.stats(trades)
        fun usd(v: Double) = String.format(Locale.US, "%+.2f", v)

        val card = Ui.card(this, if (s.netUsd >= 0) Ui.BULL else Ui.BEAR)
        card.addView(Ui.text(this, "আপনার আসল ট্রেড (নিজে লেখা ফলাফল)", 13f, Ui.MUTED))
        card.addView(Ui.text(this, "মোট ${s.trades} · জয় ${s.wins} · হার ${s.losses} · সমান ${s.breakeven}", 16f, bold = true))
        card.addView(Ui.text(this, "নিট ফল \$${usd(s.netUsd)} · সর্বোচ্চ drawdown \$${String.format(Locale.US, "%.2f", s.maxDrawdownUsd)}", 15f))
        s.winRate?.let { card.addView(Ui.text(this, "Win rate ${String.format(Locale.US, "%.0f", it * 100)}%", 14f)) }
        if (s.avgWinUsd != null || s.avgLossUsd != null) {
            card.addView(Ui.text(this, "গড় জয় \$${s.avgWinUsd?.let { usd(it) } ?: "-"} · গড় হার \$${s.avgLossUsd?.let { usd(it) } ?: "-"}", 13f))
        }
        s.profitFactor?.let { card.addView(Ui.text(this, "Profit factor ${String.format(Locale.US, "%.2f", it)}", 13f)) }
        s.avgR?.let { card.addView(Ui.text(this, "গড় R ${String.format(Locale.US, "%+.2f", it)} (ফলাফল ÷ পরিকল্পিত সর্বোচ্চ লস)", 13f)) }
        if (s.smallSample) {
            card.addView(Ui.text(this, "⚠️ ${Journal.SMALL_SAMPLE}টার কম ট্রেড: এই সংখ্যা থেকে কোনো সিদ্ধান্ত টানবেন না।", 13f, Ui.WATCH))
        }
        card.addView(Ui.text(this, "এখানে শুধু আপনি যে ট্রেড নিয়েছেন আর ফলাফল লিখেছেন সেগুলো। সিগন্যাল, টেস্ট বা ব্যাকটেস্টের ফল এখানে নেই।", 12f, Ui.MUTED))
        col.addView(card)

        val pending = store.all().filter { it.userStatus == "TAKEN" && it.resultUsd == null && !it.alert.isTest }
        if (pending.isNotEmpty()) {
            col.addView(Ui.text(this, "ফলাফল লেখা বাকি (${pending.size})", 14f, Ui.WATCH, bold = true))
            for (e in pending) {
                val b = Ui.button(this, "${e.alert.direction} ${e.alert.ticker} · ${DateFormat.format("dd MMM HH:mm", Date(e.alert.signalTimeMs))}", Ui.OFF) {
                    startActivity(Intent(this, DetailActivity::class.java).putExtra(DetailActivity.EXTRA_ID, e.alert.id))
                }
                col.addView(b)
            }
        }

        col.addView(Ui.text(this, "ইতিহাস", 14f, Ui.MUTED, bold = true))
        if (trades.isEmpty()) col.addView(Ui.text(this, "এখনো কোনো ফলাফল লেখা হয়নি।", 13f, Ui.MUTED))
        for (t in trades.sortedByDescending { it.closedAtMs }) {
            val row = Ui.card(this, if (t.resultUsd >= 0) Ui.BULL else Ui.BEAR)
            row.addView(Ui.text(this, "${t.pair} · \$${usd(t.resultUsd)} · ${if (t.origin == "PC") "PC" else "TV"}", 15f, bold = true))
            row.addView(Ui.text(this, DateFormat.format("dd MMM yyyy HH:mm", Date(t.closedAtMs)).toString(), 12f, Ui.MUTED))
            row.setOnClickListener {
                startActivity(Intent(this, DetailActivity::class.java).putExtra(DetailActivity.EXTRA_ID, t.id))
            }
            col.addView(row)
        }
    }
}
