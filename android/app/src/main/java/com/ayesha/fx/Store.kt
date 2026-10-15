package com.ayesha.fx

import android.content.Context
import com.ayesha.fx.core.AyeshaAlert
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
        set(v) = p.edit().putString("risk", v.coerceIn(0.1, 1.0).toString()).apply()
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
}

/** A stored alert plus what the owner did with it. */
data class Entry(val alert: AyeshaAlert, var userStatus: String = "NEW", var resultUsd: Double? = null)

/** Inbox stored as a small JSON file (last 300 alerts). History is never rewritten except user marks. */
class AlertStore(context: Context) {
    private val file = File(context.filesDir, "alerts.json")

    @Synchronized
    fun all(): List<Entry> {
        if (!file.exists()) return emptyList()
        return try {
            val arr = JSONArray(file.readText())
            (0 until arr.length()).mapNotNull { fromJson(arr.getJSONObject(it)) }
        } catch (e: Exception) {
            emptyList()
        }
    }

    fun get(id: String): Entry? = all().firstOrNull { it.alert.id == id }

    /** Returns false if this alert id is already stored (so it is never notified twice). */
    @Synchronized
    fun add(a: AyeshaAlert): Boolean {
        val list = all().toMutableList()
        if (list.any { it.alert.id == a.id }) return false
        list.add(0, Entry(a))
        save(list.take(300))
        return true
    }

    @Synchronized
    fun mark(id: String, status: String, resultUsd: Double? = null) {
        val list = all()
        list.firstOrNull { it.alert.id == id }?.let {
            it.userStatus = status
            if (resultUsd != null) it.resultUsd = resultUsd
        }
        save(list)
    }

    @Synchronized
    fun clearTests() = save(all().filter { !it.alert.isTest })

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
            .put("userStatus", e.userStatus).put("resultUsd", e.resultUsd ?: JSONObject.NULL)
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
            ),
            userStatus = o.optString("userStatus", "NEW"),
            resultUsd = if (o.isNull("resultUsd")) null else o.optDouble("resultUsd"),
        )
    } catch (e: Exception) {
        null
    }
}
