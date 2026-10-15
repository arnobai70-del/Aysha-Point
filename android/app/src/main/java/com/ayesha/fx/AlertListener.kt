package com.ayesha.fx

import android.app.Notification
import android.content.ComponentName
import android.content.Context
import android.provider.Settings
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import com.ayesha.fx.core.AlertParser

/**
 * Reads notifications posted by the TradingView app and keeps only AYESHA indicator alerts.
 * Everything else is ignored and never stored. Nothing is sent anywhere.
 */
class AlertListener : NotificationListenerService() {

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.packageName == packageName) return
        if (sbn.packageName !in SOURCES) return
        val text = textOf(sbn.notification) ?: return
        if (!text.contains("AYESHA")) return
        Prefs(applicationContext).lastTvSeenMs = System.currentTimeMillis()
        handle(applicationContext, text, sbn.postTime)
    }

    companion object {
        val SOURCES = setOf("com.tradingview.tradingviewapp")

        /** TradingView text is never signed, so it can never be READY (signatureOk = false). */
        fun handle(context: Context, text: String, postTimeMs: Long, isTest: Boolean = false, signatureOk: Boolean = false) {
            val alert = AlertParser.parse(text, postTimeMs, isTest, signatureOk)
            if (alert == null) {
                Prefs(context).reject("পড়া যায়নি বা লেভেল ভুল: " + text.lineSequence().firstOrNull().orEmpty().take(60))
                return
            }
            when (AlertStore(context).upsert(alert)) {
                AlertStore.Upsert.NEW -> Notifier.show(context, alert)
                AlertStore.Upsert.UPDATED -> Notifier.show(context, alert, update = true)
                AlertStore.Upsert.DUPLICATE -> {}
            }
        }

        fun textOf(n: Notification): String? {
            val e = n.extras ?: return null
            val parts = mutableListOf<String>()
            e.getCharSequence(Notification.EXTRA_TITLE)?.let { parts.add(it.toString()) }
            val big = e.getCharSequence(Notification.EXTRA_BIG_TEXT)?.toString()
            val txt = e.getCharSequence(Notification.EXTRA_TEXT)?.toString()
            // The big text is the full alert message; the short text may be cut off.
            if (!big.isNullOrBlank()) parts.add(big) else if (!txt.isNullOrBlank()) parts.add(txt)
            e.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)?.forEach { parts.add(it.toString()) }
            return if (parts.isEmpty()) null else parts.joinToString("\n")
        }

        fun isEnabled(context: Context): Boolean {
            val flat = Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners") ?: return false
            val me = ComponentName(context, AlertListener::class.java)
            return flat.split(":").any { ComponentName.unflattenFromString(it) == me }
        }
    }
}
