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

    fun show(context: Context, a: AyeshaAlert) {
        val prefs = Prefs(context)
        if (System.currentTimeMillis() < prefs.pausedUntilMs) return
        val lot = LotCalc.calc(a.ticker, a.entry, a.stop, prefs.equityUsd, prefs.riskPercent, prefs.accountType,
            prefs.spreadPips, prefs.slippagePips)
        val tradeable = lot?.ok ?: (a.chartLot >= LotCalc.MIN_LOT)
        if (!tradeable && !prefs.alertNoTrade && !a.isTest) return
        if (!canPost(context)) return
        ensureChannel(context)

        val icon = if (a.isBuy) "🟢" else "🔴"
        val title = "$icon ${a.direction} ${a.ticker}" + (if (tradeable) "" else " · NO TRADE") + (if (a.isTest) " · TEST" else "")
        val lotLine = when {
            lot == null -> "Lot (chart): ${a.chartLot}"
            lot.ok -> "Lot ${"%.2f".format(java.util.Locale.US, lot.lot)} · max loss \$${"%.2f".format(java.util.Locale.US, lot.maxLossUsd)}"
            else -> lot.note
        }
        val body = "Entry ${a.fmt(a.entry)} · SL ${a.fmt(a.stop)} · TP ${a.fmt(a.target)} · RR ${"%.2f".format(java.util.Locale.US, a.rr)}\n" +
            "$lotLine\nWhy: ${a.source} sweep → MSS → FVG"

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
            .setWhen(a.receivedAtMs)
            .setShowWhen(true)
            .build()
        context.getSystemService(NotificationManager::class.java).notify(a.id.hashCode(), n)
    }
}
