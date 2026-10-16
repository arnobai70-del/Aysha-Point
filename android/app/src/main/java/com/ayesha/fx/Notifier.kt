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
import android.text.format.DateFormat
import com.ayesha.fx.core.Assess
import com.ayesha.fx.core.Assessment
import com.ayesha.fx.core.AyeshaAlert
import com.ayesha.fx.core.Capital
import com.ayesha.fx.core.LotCalc
import com.ayesha.fx.core.LotResult
import com.ayesha.fx.core.Mtf
import com.ayesha.fx.core.News
import com.ayesha.fx.core.NewsNotice
import java.util.Date
import java.util.Locale

object Notifier {
    private const val CHANNEL = "ayesha_setups"
    private const val NEWS_CHANNEL = "ayesha_news"

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
        if (nm.getNotificationChannel(NEWS_CHANNEL) == null) {
            val ch = NotificationChannel(NEWS_CHANNEL, "News watch", NotificationManager.IMPORTANCE_DEFAULT)
            ch.description = "Economic news alerts and protection status from the AYESHA PC scanner (never trade signals)"
            nm.createNotificationChannel(ch)
        }
    }

    fun canPost(context: Context): Boolean =
        Build.VERSION.SDK_INT < 33 ||
            context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    /**
     * Lot for this alert from the owner's settings. Never falls back to the chart's own lot estimate.
     * No lot when the phone's equity is not confirmed within a day (unless it equals the PC's fresh snapshot),
     * and never more than the PC's own lot for a PC alert (the PC also counts today's and open risk).
     */
    fun lotFor(context: Context, a: AyeshaAlert, nowMs: Long = System.currentTimeMillis()): LotResult {
        val prefs = Prefs(context)
        val pcMatch = a.isPc && Capital.compare(a.capitalDigest, prefs.capitalDigest()) == Capital.OK
        Capital.lotBlock(prefs.equitySetMs, nowMs, pcMatch)?.let { return LotCalc.blocked(it) }
        if (a.isPc && a.capitalDigest.isNotBlank() && !pcMatch) {
            return LotCalc.blocked("${Capital.MISMATCH}: ফোন আর PC-র equity মেলে না, তাই কোনো লট দেখানো হবে না")
        }
        val own = LotCalc.calc(a.ticker, a.entry, a.stop, prefs.equityUsd, prefs.riskPercent, prefs.accountType,
            prefs.spreadPips, prefs.slippagePips, chartQuoteUsd = a.quoteUsd)
        return if (a.isPc) LotCalc.capToPc(own, a.chartLot) else own
    }

    /** Short Bangla reason for a non-OK lot status. */
    fun statusText(r: LotResult): String = when (r.status) {
        LotCalc.OK -> "Lot ঠিক আছে"
        LotCalc.NO_TRADE_MIN_LOT -> "NO TRADE: 0.01 লটেও ঝুঁকি বেশি"
        LotCalc.RISK_UNVERIFIED -> "RISK UNVERIFIED: লট যাচাই করা যায়নি"
        LotCalc.INVALID_SETTINGS -> "Settings ঠিক নেই"
        else -> "লেভেল ঠিক নেই"
    }

    /** Assessment with this phone's capital digest and the PC's stored news windows. */
    fun assess(context: Context, a: AyeshaAlert, nowMs: Long = System.currentTimeMillis(),
               notices: List<NewsNotice> = NewsStore(context).all()): Assessment {
        val prefs = Prefs(context)
        return Assess.assess(a, nowMs, lotFor(context, a, nowMs), prefs.watchlist,
            phoneCapital = prefs.capitalDigest(),
            newsBlock = News.block(notices, a.ticker, nowMs, a.expiresAtMs))
    }

    fun stateLabel(state: String): String = when (state) {
        Assess.READY -> "READY (PC যাচাই করেছে)"
        Assess.CHART_CANDIDATE -> "চার্ট ক্যান্ডিডেট"
        Assess.NO_TRADE -> "NO TRADE"
        Assess.WATCH -> "WATCH (এখনো entry নয়)"
        Assess.EXPIRED -> "মেয়াদ শেষ"
        else -> "UNVERIFIED"
    }

    /** One-line meaning of each state, shown in the app's help card and in notifications. */
    fun stateMeaning(state: String): String = when (state) {
        Assess.READY -> "PC সব নিয়ম, নিউজ, capital, spread, লট যাচাই করেছে। Exness-এ দাম মিলিয়ে নিজে সিদ্ধান্ত নিন।"
        Assess.CHART_CANDIDATE -> "শুধু TradingView চার্টের নিয়ম মিলেছে; নিউজ/spread/Exness যাচাই হয়নি।"
        Assess.WATCH -> "setup তৈরি হচ্ছে বা A+ নয়; এখন entry নেবেন না।"
        Assess.NO_TRADE -> "নিয়ম, নিউজ বা ঝুঁকির কারণে এই ট্রেড নেওয়া যাবে না; কারণ লেখা থাকে।"
        Assess.EXPIRED -> "সময় পেরিয়ে গেছে; আর নেবেন না।"
        else -> "কোনো তথ্য যাচাই করা যায়নি (সই, version, সময়, capital বা লট); নেবেন না।"
    }

    private fun openIntent(context: Context, a: AyeshaAlert): PendingIntent {
        val open = Intent(context, DetailActivity::class.java)
            .putExtra(DetailActivity.EXTRA_ID, a.id)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        return PendingIntent.getActivity(context, a.id.hashCode(), open,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    fun show(context: Context, a: AyeshaAlert, update: Boolean = false) {
        val prefs = Prefs(context)
        val now = System.currentTimeMillis()
        if (now < prefs.pausedUntilMs && !a.isTest) return
        val lot = lotFor(context, a, now)
        val verdict = assess(context, a, now)
        // Entry notifications only for READY / CHART_CANDIDATE. NO_TRADE only if the owner asked for it.
        // UNVERIFIED and EXPIRED alerts are archived silently, with their reasons, in the inbox.
        val show = verdict.actionable || (verdict.state == Assess.NO_TRADE && prefs.alertNoTrade)
        if (!show && !a.isTest) return
        if (!canPost(context)) return
        ensureChannel(context)

        val icon = if (a.isBuy) "🟢" else "🔴"
        val title = "$icon ${a.direction} ${a.ticker} · " + stateLabel(verdict.state) +
            (if (update && verdict.state == Assess.READY) " · M5 নিশ্চিত" else "") + (if (a.isTest) " · TEST" else "")
        val lotLine = if (lot.ok) {
            "Lot ${"%.2f".format(Locale.US, lot.lot)} · max loss \$${"%.2f".format(Locale.US, lot.maxLossUsd)}"
        } else {
            statusText(lot) + " — " + lot.note
        }
        val check = if (verdict.state == Assess.READY) "Exness অ্যাপে দাম আর spread মিলিয়ে নিন।"
            else "News আর Exness spread যাচাই হয়নি, নিজে দেখে নিন।"
        val mtf = Mtf.summary(a.mtf, a.isBuy)
        val body = "Entry ${a.fmt(a.entry)} · SL ${a.fmt(a.stop)} · TP ${a.fmt(a.target)} · RR ${"%.2f".format(Locale.US, a.rr)}\n" +
            "$lotLine\n" + (if (mtf.isNotEmpty()) "MTF: $mtf\n" else "") +
            (if (verdict.actionable) check else verdict.reasons.joinToString("; ")) + "\n" + stateMeaning(verdict.state)

        val n = Notification.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(title)
            .setContentText(body.lineSequence().first())
            .setStyle(Notification.BigTextStyle().bigText(body))
            .setColor(if (a.isBuy) Color.parseColor("#16A34A") else Color.parseColor("#DC2626"))
            .setContentIntent(openIntent(context, a))
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_MESSAGE)
            .setWhen(a.signalTimeMs)
            .setShowWhen(true)
            .build()
        context.getSystemService(NotificationManager::class.java).notify(a.id.hashCode(), n)
    }

    /**
     * The PC cancelled a READY before entry (signed NO_TRADE with INVALIDATED). Always shown, even when
     * alerts are paused or NO_TRADE notifications are off, and it replaces the READY notification.
     */
    fun showCancelled(context: Context, a: AyeshaAlert) {
        if (!canPost(context)) return
        ensureChannel(context)
        val why = a.blockers.filter { it != "INVALIDATED" }.joinToString(", ").ifBlank { "INVALIDATED" }
        val title = "⛔ বাতিল: ${a.direction} ${a.ticker} — এই setup আর নেবেন না"
        val body = "PC আগের READY বাতিল করেছে ($why)। অর্ডার না দিয়ে থাকলে দেবেন না। দিয়ে থাকলে stop-loss, " +
            "ঝুঁকি আর সম্ভাব্য gap/slippage নিজে দেখে নিন। AYESHA কখনো অর্ডার বন্ধ বা বদল করে না।"
        val n = Notification.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(title)
            .setContentText(body.lineSequence().first())
            .setStyle(Notification.BigTextStyle().bigText(body))
            .setColor(Color.parseColor("#DC2626"))
            .setContentIntent(openIntent(context, a))
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_MESSAGE)
            .setShowWhen(true)
            .build()
        context.getSystemService(NotificationManager::class.java).notify(a.id.hashCode(), n)
    }

    /** News Watch notice: one notification per event, updated as its phase changes. Never a trade signal. */
    fun showNews(context: Context, notice: NewsNotice) {
        if (!canPost(context)) return
        ensureChannel(context)
        val now = System.currentTimeMillis()
        val hhmm = { ms: Long -> DateFormat.format("HH:mm", Date(ms)).toString() }
        val body = News.lines(notice, hhmm).joinToString("\n")
        val pi = PendingIntent.getActivity(context, ("news|" + notice.eventId).hashCode(),
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(context, NEWS_CHANNEL)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle(News.title(notice, now))
            .setContentText(body.lineSequence().first())
            .setStyle(Notification.BigTextStyle().bigText(body))
            .setColor(if (notice.category == News.REACTION) Color.parseColor("#38BDF8") else Color.parseColor("#EAB308"))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_EVENT)
            .setWhen(notice.eventMs)
            .setShowWhen(true)
            .build()
        context.getSystemService(NotificationManager::class.java).notify(("news|" + notice.eventId).hashCode(), n)
    }
}
