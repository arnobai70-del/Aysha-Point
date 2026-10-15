package com.ayesha.fx

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import com.ayesha.fx.core.Heartbeat
import com.ayesha.fx.core.LinkHealth
import com.ayesha.fx.core.Signer
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL

/**
 * Opt-in PC link: keeps one HTTPS connection to the owner's ntfy.sh topic and receives signals and
 * heartbeats from the AYESHA PC scanner. Every message must carry a valid signature for this phone's
 * pairing code; anything else is dropped and counted. Nothing is ever sent from the phone.
 */
class LinkService : Service() {
    companion object {
        private const val CHANNEL = "ayesha_link"
        private const val NOTE_ID = 7001
        const val SERVER = "https://ntfy.sh"

        fun start(context: Context) {
            val p = Prefs(context)
            if (!p.linkEnabled || Signer.normalize(p.pairingCode) == null) return
            val i = Intent(context, LinkService::class.java)
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(i) else context.startService(i)
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, LinkService::class.java))
            Prefs(context).linkState = "OFF"
        }

        /** Handle one relay message body (shared by the stream and tests on device). */
        fun deliver(context: Context, message: String, receivedAtMs: Long) {
            val prefs = Prefs(context)
            val body = Signer.verify(prefs.pairingCode, message)
            if (body == null) {
                prefs.reject("PC বার্তার সই মেলেনি (অন্য pairing code বা নকল বার্তা)")
                return
            }
            val hb = Heartbeat.parse(body)
            if (hb != null) {
                // Catch-up replays old heartbeats; only a newer one may refresh the PC status.
                if (!LinkHealth.accept(hb, prefs.hbPcMs, receivedAtMs)) return
                prefs.hbPcMs = hb.pcTimeMs
                prefs.hbRecvMs = receivedAtMs
                prefs.hbState = hb.state
                prefs.hbVersion = hb.version
                return
            }
            AlertListener.handle(context, body, receivedAtMs, signatureOk = true)
        }
    }

    @Volatile private var running = false
    private var worker: Thread? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startAsForeground("সংযোগ হচ্ছে…")
        if (worker?.isAlive != true) {
            running = true
            worker = Thread({ loop() }, "ayesha-link").also { it.start() }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        worker?.interrupt()
        super.onDestroy()
    }

    private fun startAsForeground(text: String) {
        val nm = getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "PC link", NotificationManager.IMPORTANCE_MIN))
        }
        val pi = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("AYESHA PC link")
            .setContentText(text)
            .setContentIntent(pi)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTE_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(NOTE_ID, n)
        }
    }

    private fun setState(s: String) {
        val p = Prefs(this)
        p.linkState = s
        p.linkStateMs = System.currentTimeMillis()
    }

    private fun loop() {
        var backoff = 5_000L
        while (running) {
            val prefs = Prefs(this)
            val topic = Signer.topic(prefs.pairingCode)
            if (topic == null || !prefs.linkEnabled) {
                setState("OFF")
                stopSelf()
                return
            }
            // Catch up on anything missed since the last message (ntfy.sh keeps messages for hours).
            val since = prefs.linkLastId.ifBlank { "2h" }
            var conn: HttpURLConnection? = null
            try {
                conn = URL("$SERVER/$topic/json?since=$since").openConnection() as HttpURLConnection
                conn.connectTimeout = 15_000
                conn.readTimeout = 120_000 // ntfy sends a keepalive about every 45 s
                conn.setRequestProperty("User-Agent", "AYESHA-FX-Android")
                if (conn.responseCode != 200) throw IllegalStateException("HTTP ${conn.responseCode}")
                setState("CONNECTED")
                backoff = 5_000L
                BufferedReader(InputStreamReader(conn.inputStream, Charsets.UTF_8)).use { r ->
                    while (running) {
                        val line = r.readLine() ?: break
                        val o = try { JSONObject(line) } catch (e: Exception) { continue }
                        if (o.optString("event") != "message") continue
                        val id = o.optString("id")
                        deliver(this, o.optString("message"), System.currentTimeMillis())
                        if (id.isNotBlank()) Prefs(this).linkLastId = id
                    }
                }
            } catch (e: Exception) {
                setState("RECONNECTING: ${e.javaClass.simpleName}")
            } finally {
                conn?.disconnect()
            }
            if (!running) break
            try {
                Thread.sleep(backoff)
            } catch (e: InterruptedException) {
                break
            }
            backoff = (backoff * 2).coerceAtMost(60_000L)
        }
    }
}

/** Restarts the PC link after a phone reboot, if the owner turned it on. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED || intent.action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            LinkService.start(context)
        }
    }
}
