package com.ayesha.fx

import android.content.Context
import com.ayesha.fx.core.AyeshaAlert
import com.ayesha.fx.core.Backup
import com.ayesha.fx.core.JournalTrade
import com.ayesha.fx.core.Mtf
import com.ayesha.fx.core.StrategyInfo
import com.ayesha.fx.core.Transitions
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Settings typed by the owner. Nothing here is a broker login. */
class Prefs(context: Context) {
    private val p = context.getSharedPreferences("ayesha", Context.MODE_PRIVATE)

    var equityUsd: Double
        get() = p.getString("equity", "20")!!.toDoubleOrNull() ?: 20.0
        set(v) = p.edit().putString("equity", v.toString()).apply()
    var riskPercent: Double
        get() = p.getString("risk", "0.5")!!.toDoubleOrNull() ?: 0.5
        set(v) = p.edit().putString("risk", v.toString()).apply()
    var accountType: String
        get() = p.getString("account", "Standard")!!
        set(v) = p.edit().putString("account", v).apply()
    var spreadPips: Double
        get() = p.getString("spread", "0.8")!!.toDoubleOrNull() ?: 0.8
        set(v) = p.edit().putString("spread", v.toString()).apply()
    var slippagePips: Double
        get() = p.getString("slip", "0.3")!!.toDoubleOrNull() ?: 0.3
        set(v) = p.edit().putString("slip", v.toString()).apply()
    var alertNoTrade: Boolean
        get() = p.getBoolean("alertNoTrade", false)
        set(v) = p.edit().putBoolean("alertNoTrade", v).apply()
    var pausedUntilMs: Long
        get() = p.getLong("pausedUntil", 0L)
        set(v) = p.edit().putLong("pausedUntil", v).apply()

    /** Pairs the owner wants alerts for; anything else is archived. */
    var watchlist: Set<String>
        get() = p.getStringSet("watchlist", null)?.toSet() ?: StrategyInfo.PAIRS.toSet()
        set(v) = p.edit().putStringSet("watchlist", v).apply()

    // --- PC link (opt-in) -------------------------------------------------------------------
    var pairingCode: String
        get() = p.getString("pairingCode", "")!!
        set(v) = p.edit().putString("pairingCode", v).apply()
    var linkEnabled: Boolean
        get() = p.getBoolean("linkEnabled", false)
        set(v) = p.edit().putBoolean("linkEnabled", v).apply()
    var linkLastId: String
        get() = p.getString("linkLastId", "")!!
        set(v) = p.edit().putString("linkLastId", v).apply()
    var linkState: String
        get() = p.getString("linkState", "OFF")!!
        set(v) = p.edit().putString("linkState", v).apply()
    var linkStateMs: Long
        get() = p.getLong("linkStateMs", 0L)
        set(v) = p.edit().putLong("linkStateMs", v).apply()
    var hbPcMs: Long
        get() = p.getLong("hbPcMs", 0L)
        set(v) = p.edit().putLong("hbPcMs", v).apply()
    var hbRecvMs: Long
        get() = p.getLong("hbRecvMs", 0L)
        set(v) = p.edit().putLong("hbRecvMs", v).apply()
    var hbState: String
        get() = p.getString("hbState", "")!!
        set(v) = p.edit().putString("hbState", v).apply()
    var hbVersion: String
        get() = p.getString("hbVersion", "")!!
        set(v) = p.edit().putString("hbVersion", v).apply()

    // --- diagnostics ------------------------------------------------------------------------
    var lastTvSeenMs: Long
        get() = p.getLong("lastTvSeen", 0L)
        set(v) = p.edit().putLong("lastTvSeen", v).apply()
    var rejectedCount: Int
        get() = p.getInt("rejected", 0)
        set(v) = p.edit().putInt("rejected", v).apply()
    var lastRejectReason: String
        get() = p.getString("lastReject", "")!!
        set(v) = p.edit().putString("lastReject", v).apply()

    var lastBackupMs: Long
        get() = p.getLong("lastBackupMs", 0L)
        set(v) = p.edit().putLong("lastBackupMs", v).apply()

    /** Settings that go into a backup file. The pairing code is deliberately NOT included. */
    fun settingsJson(): JSONObject = JSONObject()
        .put("equity", equityUsd).put("risk", riskPercent).put("account", accountType)
        .put("spread", spreadPips).put("slip", slippagePips).put("watchlist", JSONArray(watchlist.sorted()))

    fun restoreSettings(o: JSONObject) {
        o.optDouble("equity").takeIf { it.isFinite() && it > 0 }?.let { equityUsd = it }
        o.optDouble("risk").takeIf { it.isFinite() && it > 0 && it <= 1.0 }?.let { riskPercent = it }
        o.optString("account").takeIf { it == "Standard" || it == "StandardCent" }?.let { accountType = it }
        o.optDouble("spread").takeIf { it.isFinite() && it >= 0 }?.let { spreadPips = it }
        o.optDouble("slip").takeIf { it.isFinite() && it >= 0 }?.let { slippagePips = it }
        o.optJSONArray("watchlist")?.let { arr ->
            val w = (0 until arr.length()).map { arr.getString(it) }.filter { it in StrategyInfo.PAIRS }.toSet()
            if (w.isNotEmpty()) watchlist = w
        }
    }

    fun reject(reason: String) {
        rejectedCount = rejectedCount + 1
        lastRejectReason = reason
    }
}

/** A stored alert plus what the owner did with it. resultUsd/riskUsd/closedAtMs are the owner's REAL trade. */
data class Entry(
    val alert: AyeshaAlert,
    var userStatus: String = "NEW",
    var resultUsd: Double? = null,
    var riskUsd: Double? = null,
    var closedAtMs: Long? = null,
)

/**
 * Inbox stored as a small JSON file (last 300 alerts). History is never rewritten except user marks.
 * One process-wide lock covers every AlertStore instance (listener, link service and screens run on
 * different threads). A file that cannot be read is moved aside, never silently overwritten.
 */
class AlertStore(context: Context) {
    private val file = File(context.filesDir, "alerts.json")

    companion object {
        private val LOCK = Any()
    }

    fun all(): List<Entry> = synchronized(LOCK) { readLocked() }

    private fun readLocked(): List<Entry> {
        if (!file.exists()) return emptyList()
        return try {
            val arr = JSONArray(file.readText())
            (0 until arr.length()).mapNotNull { fromJson(arr.getJSONObject(it)) }
        } catch (e: Exception) {
            file.renameTo(File(file.parentFile, "alerts.corrupt-${System.currentTimeMillis()}.json"))
            emptyList()
        }
    }

    fun get(id: String): Entry? = all().firstOrNull { it.alert.id == id }

    /** Returns false if this alert id is already stored (so it is never notified twice). */
    fun add(a: AyeshaAlert): Boolean = upsert(a) == Upsert.NEW

    enum class Upsert { NEW, UPDATED, DUPLICATE }

    /**
     * NEW: first time this id is seen. UPDATED: a signed PC status change for the same id (WATCH -> READY
     * after M5 confirmation, or WATCH -> NO_TRADE); the owner's own marks are kept. DUPLICATE: a replay.
     */
    fun upsert(a: AyeshaAlert): Upsert = synchronized(LOCK) {
        val list = readLocked().toMutableList()
        val i = list.indexOfFirst { it.alert.id == a.id }
        if (i < 0) {
            list.add(0, Entry(a))
            save(trim(list))
            return Upsert.NEW
        }
        val old = list[i]
        if (!(a.isPc && a.signatureOk && old.alert.isPc && Transitions.allowed(old.alert.status, a.status))) {
            return Upsert.DUPLICATE
        }
        list[i] = old.copy(alert = a)
        save(list)
        Upsert.UPDATED
    }

    fun mark(id: String, status: String, resultUsd: Double? = null, riskUsd: Double? = null) = synchronized(LOCK) {
        val list = readLocked()
        list.firstOrNull { it.alert.id == id }?.let {
            it.userStatus = status
            if (riskUsd != null && it.riskUsd == null) it.riskUsd = riskUsd
            if (resultUsd != null) {
                it.resultUsd = resultUsd
                it.closedAtMs = System.currentTimeMillis()
            }
        }
        save(list)
    }

    /** The owner's real, closed trades (never tests, never signals without a typed result). */
    fun journal(): List<JournalTrade> = all().filter { !it.alert.isTest && it.userStatus == "TAKEN" && it.resultUsd != null }
        .map { JournalTrade(it.alert.id, it.alert.ticker, it.alert.origin, it.closedAtMs ?: it.alert.receivedAtMs, it.resultUsd!!, it.riskUsd) }

    fun clearTests() = synchronized(LOCK) { save(readLocked().filter { !it.alert.isTest }) }

    /** Journal entries (trades the owner took) are never dropped by the 300-alert limit. */
    private fun trim(list: List<Entry>): List<Entry> = Backup.retain(list, { it.userStatus == "TAKEN" && !it.alert.isTest }, 300)

    /** The whole inbox + journal + settings as one JSON document for a backup file. */
    fun exportJson(prefs: Prefs, appVersion: String): String = synchronized(LOCK) {
        val arr = JSONArray()
        readLocked().forEach { arr.put(toJson(it)) }
        JSONObject().put("format", Backup.FORMAT).put("version", Backup.VERSION)
            .put("exportedAtMs", System.currentTimeMillis()).put("appVersion", appVersion)
            .put("settings", prefs.settingsJson()).put("entries", arr).toString(1)
    }

    data class ImportResult(val added: Int, val updated: Int, val unchanged: Int)

    /** Merge a backup into the store. Throws IllegalArgumentException for a file that is not an AYESHA backup. */
    fun importJson(text: String, prefs: Prefs): ImportResult = synchronized(LOCK) {
        val o = try { JSONObject(text) } catch (e: Exception) { throw IllegalArgumentException("not a JSON file") }
        require(o.optString("format") == Backup.FORMAT) { "not an AYESHA backup file" }
        require(o.optInt("version", 0) in 1..Backup.VERSION) { "backup from a newer app version; update the app first" }
        val incoming = o.optJSONArray("entries") ?: JSONArray()
        val list = readLocked().toMutableList()
        var added = 0
        var updated = 0
        var same = 0
        for (i in 0 until incoming.length()) {
            val e = fromJson(incoming.getJSONObject(i)) ?: continue
            val at = list.indexOfFirst { it.alert.id == e.alert.id }
            if (at < 0) {
                list.add(e); added++
            } else {
                val cur = list[at]
                if (Backup.preferIncoming(Backup.Mark(cur.userStatus, cur.resultUsd, cur.closedAtMs),
                        Backup.Mark(e.userStatus, e.resultUsd, e.closedAtMs))) {
                    list[at] = cur.copy(userStatus = e.userStatus, resultUsd = e.resultUsd,
                        riskUsd = e.riskUsd ?: cur.riskUsd, closedAtMs = e.closedAtMs); updated++
                } else same++
            }
        }
        list.sortByDescending { it.alert.receivedAtMs }
        save(trim(list))
        o.optJSONObject("settings")?.let { prefs.restoreSettings(it) }
        ImportResult(added, updated, same)
    }

    private fun save(list: List<Entry>) {
        val arr = JSONArray()
        list.forEach { arr.put(toJson(it)) }
        val tmp = File(file.parentFile, "alerts.json.tmp")
        tmp.writeText(arr.toString())
        tmp.renameTo(file)
    }

    private fun toJson(e: Entry): JSONObject {
        val a = e.alert
        return JSONObject()
            .put("id", a.id).put("direction", a.direction).put("symbol", a.symbol).put("ticker", a.ticker)
            .put("timeframe", a.timeframe).put("entry", a.entry).put("stop", a.stop).put("target", a.target)
            .put("rr", a.rr).put("chartLot", a.chartLot).put("expiryBars", a.expiryBars).put("source", a.source)
            .put("targetName", a.targetName).put("version", a.version).put("why", a.why)
            .put("receivedAtMs", a.receivedAtMs).put("raw", a.raw).put("isTest", a.isTest)
            .put("barCloseMs", a.barCloseMs ?: JSONObject.NULL).put("quoteUsd", a.quoteUsd ?: JSONObject.NULL)
            .put("status", a.status).put("origin", a.origin).put("signalId", a.signalId)
            .put("expiresUtcMs", a.expiresUtcMs ?: JSONObject.NULL).put("blockers", JSONArray(a.blockers))
            .put("signatureOk", a.signatureOk).put("mtf", Mtf.encode(a.mtf))
            .put("userStatus", e.userStatus).put("resultUsd", e.resultUsd ?: JSONObject.NULL)
            .put("riskUsd", e.riskUsd ?: JSONObject.NULL).put("closedAtMs", e.closedAtMs ?: JSONObject.NULL)
    }

    private fun fromJson(o: JSONObject): Entry? = try {
        Entry(
            AyeshaAlert(
                id = o.getString("id"), direction = o.getString("direction"), symbol = o.getString("symbol"),
                ticker = o.getString("ticker"), timeframe = o.getString("timeframe"), entry = o.getDouble("entry"),
                stop = o.getDouble("stop"), target = o.getDouble("target"), rr = o.optDouble("rr", 0.0),
                chartLot = o.optDouble("chartLot", 0.0), expiryBars = o.optInt("expiryBars", 8),
                source = o.optString("source"), targetName = o.optString("targetName"),
                version = o.optString("version"), why = o.optString("why"),
                receivedAtMs = o.getLong("receivedAtMs"), raw = o.optString("raw"), isTest = o.optBoolean("isTest"),
                barCloseMs = if (o.isNull("barCloseMs")) null else o.optLong("barCloseMs"),
                quoteUsd = if (o.isNull("quoteUsd")) null else o.optDouble("quoteUsd").takeIf { it.isFinite() && it > 0 },
                status = o.optString("status", ""),
                origin = o.optString("origin", "TV"),
                signalId = o.optString("signalId", ""),
                expiresUtcMs = if (o.isNull("expiresUtcMs") || !o.has("expiresUtcMs")) null else o.optLong("expiresUtcMs"),
                blockers = o.optJSONArray("blockers")?.let { arr -> (0 until arr.length()).map { arr.getString(it) } } ?: emptyList(),
                signatureOk = o.optBoolean("signatureOk", false),
                mtf = Mtf.parse(o.optString("mtf", "")),
            ),
            userStatus = o.optString("userStatus", "NEW"),
            resultUsd = if (o.isNull("resultUsd")) null else o.optDouble("resultUsd").takeIf { it.isFinite() },
            riskUsd = if (!o.has("riskUsd") || o.isNull("riskUsd")) null else o.optDouble("riskUsd").takeIf { it.isFinite() },
            closedAtMs = if (!o.has("closedAtMs") || o.isNull("closedAtMs")) null else o.optLong("closedAtMs"),
        )
    } catch (e: Exception) {
        null
    }
}
