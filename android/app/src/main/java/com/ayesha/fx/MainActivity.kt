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
import com.ayesha.fx.core.SettingsCheck
import java.util.Date

/** Home: setup status + alert inbox. */
class MainActivity : Activity() {
    private lateinit var col: LinearLayout

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
    }

    override fun onResume() {
        super.onResume()
        render()
    }

    private fun render() {
        col.removeAllViews()
        val prefs = Prefs(this)
        val listener = AlertListener.isEnabled(this)
        val notif = Notifier.canPost(this)

        val status = Ui.card(this, if (listener && notif) Ui.BULL else Ui.WATCH)
        status.addView(Ui.text(this, "অবস্থা", 13f, Ui.MUTED))
        status.addView(Ui.text(this, (if (listener) "✅" else "⚠️") + " TradingView নোটিফিকেশন পড়ার অনুমতি", 15f))
        status.addView(Ui.text(this, (if (notif) "✅" else "⚠️") + " AYESHA নোটিফিকেশন দেখানোর অনুমতি", 15f))
        status.addView(Ui.text(this, "Equity \$${prefs.equityUsd} · risk ${prefs.riskPercent}% · ${prefs.accountType}", 13f, Ui.MUTED))
        val bad = SettingsCheck.problems(prefs.equityUsd, prefs.riskPercent, prefs.spreadPips, prefs.slippagePips)
        if (bad.isNotEmpty()) {
            status.addView(Ui.text(this, "⚠️ Settings ঠিক নেই, তাই কোনো লট দেখানো হবে না: " + bad.joinToString("; "), 14f, Ui.WATCH, bold = true))
        }
        if (System.currentTimeMillis() < prefs.pausedUntilMs) {
            status.addView(Ui.text(this, "⏸ অ্যালার্ট বন্ধ আছে", 14f, Ui.WATCH, bold = true))
        }
        if (!listener) {
            status.addView(Ui.button(this, "অনুমতি দিন (Notification access)", Ui.WATCH) {
                startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
            })
            status.addView(Ui.text(this,
                "যদি \"Restricted setting\" দেখায়: Settings → Apps → AYESHA FX → ⋮ (উপরে ডানে) → Allow restricted settings, তারপর আবার চেষ্টা করুন।",
                12f, Ui.MUTED))
        }
        if (!notif && Build.VERSION.SDK_INT >= 33) {
            status.addView(Ui.button(this, "নোটিফিকেশন চালু করুন", Ui.WATCH) {
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
            })
        }
        col.addView(status)

        col.addView(Ui.row(this,
            Ui.button(this, "⚙️ Settings") { startActivity(Intent(this, SettingsActivity::class.java)) },
            Ui.button(this, "🧪 Test alert", Ui.OFF) {
                val now = System.currentTimeMillis()
                AlertListener.handle(this, AlertParser.sample(now), now, isTest = true)
                Toast.makeText(this, "Test alert পাঠানো হয়েছে", Toast.LENGTH_SHORT).show()
                render()
            },
        ))

        val entries = AlertStore(this).all()
        col.addView(Ui.text(this, "সিগন্যাল (${entries.size})", 18f, bold = true))
        if (entries.isEmpty()) {
            col.addView(Ui.text(this,
                "এখনো কোনো সিগন্যাল নেই। PC-তে TradingView-এ AYESHA indicator আর alert চালু থাকলে, সেটআপ পেলে এখানে আসবে। " +
                    "কোনো দিন সিগন্যাল না আসাও স্বাভাবিক।", 14f, Ui.MUTED))
        }
        val now = System.currentTimeMillis()
        for (e in entries) {
            val a = e.alert
            val expired = a.isExpired(now)
            val accent = when {
                expired -> Ui.OFF
                a.isBuy -> Ui.BULL
                else -> Ui.BEAR
            }
            val card = Ui.card(this, accent)
            val icon = if (a.isBuy) "🟢" else "🔴"
            card.addView(Ui.text(this, "$icon ${a.direction} ${a.ticker}" + (if (a.isTest) "  · TEST" else ""), 17f, bold = true))
            card.addView(Ui.text(this, "Entry ${a.fmt(a.entry)} · SL ${a.fmt(a.stop)} · TP ${a.fmt(a.target)}", 14f))
            val lot = Notifier.lotFor(this, a)
            card.addView(Ui.text(this, if (lot.ok) "চার্ট ক্যান্ডিডেট · Lot ${String.format(java.util.Locale.US, "%.2f", lot.lot)}" else Notifier.statusText(lot),
                13f, if (lot.ok) Ui.SKY else Ui.WATCH))
            val time = DateFormat.format("dd MMM HH:mm", Date(a.signalTimeMs))
            val state = when {
                e.userStatus == "TAKEN" -> "ট্রেড নিয়েছি"
                e.userStatus == "SKIPPED" -> "বাদ দিয়েছি"
                expired -> "মেয়াদ শেষ"
                else -> "সক্রিয়"
            }
            card.addView(Ui.text(this, "$time · ${a.source} sweep → MSS → FVG · $state", 12f, Ui.MUTED))
            card.setOnClickListener {
                startActivity(Intent(this, DetailActivity::class.java).putExtra(DetailActivity.EXTRA_ID, a.id))
            }
            col.addView(card)
        }
        if (entries.any { it.alert.isTest }) {
            col.addView(Ui.button(this, "Test alert গুলো মুছুন", Ui.OFF) {
                AlertStore(this).clearTests()
                render()
            })
        }
    }
}
