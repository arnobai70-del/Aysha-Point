package com.ayesha.fx

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import com.ayesha.fx.core.AyeshaAlert
import com.ayesha.fx.core.LotCalc
import com.ayesha.fx.core.LotResult
import java.util.Locale

object Notifier {
    private const val CHANNEL = "ayesha_setups"

    fun ensureChannel(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL) == null) {
            val ch = NotificationChannel(CHANNEL, "Trade setups", NotificationManager.IMPORTANCE_HIGH)
            ch.description = "AYESHA setup alerts from your TradingView indicator"
            ch.enableVibration(true)
            ch.enableLights(true)
            ch.lightColor = Color.CYAN
            nm.createNotificationChannel(ch)
        }
    }

    fun canPost(context: Context): Boolean =
        Build.VERSION.SDK_INT < 33 ||
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    /** Lot for this alert from the owner's settings. Never falls back to the chart's own lot estimate. */
    fun lotFor(context: Context, a: AyeshaAlert): LotResult {
        val prefs = Prefs(context)
        return LotCalc.calc(a.ticker, a.entry, a.stop, prefs.equityUsd, prefs.riskPercent, prefs.accountType,
            prefs.spreadPips, prefs.slippagePips, chartQuoteUsd = a.quoteUsd)
    }

    /** Short Bangla reason for a non-OK lot status. */
    fun statusText(r: LotResult): String = when (r.status) {
        LotCalc.OK -> "Lot ঠিক আছে"
        LotCalc.NO_TRADE_MIN_LOT -> "NO TRADE: 0.01 লটেও ঝুঁকি বেশি"
        LotCalc.RISK_UNVERIFIED -> "RISK UNVERIFIED: লট যাচাই করা যায়নি"
        LotCalc.INVALID_SETTINGS -> "Settings ঠিক নেই"
        else -> "লেভেল ঠিক নেই"
    }

    fun show(context: Context, a: AyeshaAlert) {
        val prefs = Prefs(context)
        val now = System.currentTimeMillis()
        if (now < prefs.pausedUntilMs && !a.isTest) return
        // A push that reaches the phone after the setup expired is stored for the record but never alerted.
        if (a.isExpired(now) && !a.isTest) return
        val lot = lotFor(context, a)
        val tradeable = lot.ok
        if (!tradeable && !prefs.alertNoTrade && !a.isTest) return
        if (!canPost(context)) return
        ensureChannel(context)

        val icon = if (a.isBuy) "🟢" else "🔴"
        val title = "$icon ${a.direction} ${a.ticker} · " + (if (tradeable) "চার্ট ক্যান্ডিডেট" else lot.status.replace('_', ' ')) +
            (if (a.isTest) " · TEST" else "")
        val lotLine = if (lot.ok) {
            "Lot ${"%.2f".format(Locale.US, lot.lot)} · max loss \$${"%.2f".format(Locale.US, lot.maxLossUsd)}"
        } else {
            statusText(lot) + " — " + lot.note
        }
        val late = if (a.isDelayed) "\n⚠️ নোটিফিকেশন দেরিতে এসেছে (${(a.deliveryDelayMs ?: 0) / 60_000} মিনিট)" else ""
        val body = "Entry ${a.fmt(a.entry)} · SL ${a.fmt(a.stop)} · TP ${a.fmt(a.target)} · RR ${"%.2f".format(Locale.US, a.rr)}\n" +
            "$lotLine\nNews আর Exness spread যাচাই হয়নি, নিজে দেখে নিন।$late"

        val open = Intent(context, DetailActivity::class.java)
            .putExtra(DetailActivity.EXTRA_ID, a.id)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val pi = PendingIntent.getActivity(context, a.id.hashCode(), open,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

        val n = Notification.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(title)
            .setContentText(body.lineSequence().first())
            .setStyle(Notification.BigTextStyle().bigText(body))
            .setColor(if (a.isBuy) Color.parseColor("#16A34A") else Color.parseColor("#DC2626"))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_MESSAGE)
            .setWhen(a.signalTimeMs)
            .setShowWhen(true)
            .build()
        context.getSystemService(NotificationManager::class.java).notify(a.id.hashCode(), n)
    }
}
