package com.ayesha.fx

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.text.format.DateFormat
import android.widget.Toast
import com.ayesha.fx.core.Journal
import java.util.Date
import java.util.Locale

/** The owner's REAL trades and their statistics. Signals, tests and backtests never appear here. */
class JournalActivity : Activity() {
    companion object {
        private const val REQ_EXPORT = 41
        private const val REQ_IMPORT = 42
    }

    @Deprecated("Activity result API without AndroidX")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        val uri = data?.data
        if (resultCode != RESULT_OK || uri == null) return
        val prefs = Prefs(this)
        try {
            when (requestCode) {
                REQ_EXPORT -> {
                    val text = AlertStore(this).exportJson(prefs, BuildConfigInfo.versionName(this))
                    contentResolver.openOutputStream(uri, "wt")!!.use { it.write(text.toByteArray(Charsets.UTF_8)) }
                    prefs.lastBackupMs = System.currentTimeMillis()
                    Toast.makeText(this, "ব্যাকআপ সেভ হয়েছে", Toast.LENGTH_LONG).show()
                }
                REQ_IMPORT -> {
                    val text = contentResolver.openInputStream(uri)!!.use { it.readBytes().toString(Charsets.UTF_8) }
                    val r = AlertStore(this).importJson(text, prefs)
                    Toast.makeText(this, "ফেরত এসেছে: নতুন ${r.added}, আপডেট ${r.updated}, আগে থেকেই ছিল ${r.unchanged}", Toast.LENGTH_LONG).show()
                }
            }
        } catch (e: Exception) {
            Toast.makeText(this, "হয়নি: ${e.message ?: e.javaClass.simpleName}", Toast.LENGTH_LONG).show()
        }
    }

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

        val bk = Ui.card(this, Ui.SKY)
        bk.addView(Ui.text(this, "ব্যাকআপ", 13f, Ui.MUTED))
        val last = Prefs(this).lastBackupMs
        bk.addView(Ui.text(this, if (last > 0) "শেষ ব্যাকআপ: ${DateFormat.format("dd MMM yyyy HH:mm", Date(last))}" else "এখনো ব্যাকআপ নেওয়া হয়নি", 14f))
        bk.addView(Ui.text(this, "অ্যাপ uninstall করার আগে বা ফোন বদলানোর আগে ব্যাকআপ ফাইল বানান (যেমন Downloads বা Google Drive-এ)। " +
            "ফাইলে সিগন্যাল, জার্নাল আর settings থাকে; pairing code থাকে না, সেটা আবার লিখতে হবে।", 12f, Ui.MUTED))
        bk.addView(Ui.row(this,
            Ui.button(this, "💾 ব্যাকআপ ফাইল", Ui.SKY) {
                val name = "ayesha-backup-" + DateFormat.format("yyyyMMdd-HHmm", Date()) + ".json"
                @Suppress("DEPRECATION")
                startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("application/json").putExtra(Intent.EXTRA_TITLE, name), REQ_EXPORT)
            },
            Ui.button(this, "📂 ফেরত আনুন", Ui.OFF) {
                @Suppress("DEPRECATION")
                startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType("*/*"), REQ_IMPORT)
            },
        ))
        col.addView(bk)

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
