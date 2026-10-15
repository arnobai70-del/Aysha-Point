package com.ayesha.fx.core

/**
 * Rules for restoring a journal backup (pure, unit-tested). A backup file is the owner's own copy of
 * the signal inbox and journal; restoring merges it and never throws away a typed trade result.
 */
object Backup {
    const val FORMAT = "ayesha-fx-backup"
    const val VERSION = 1

    data class Mark(val userStatus: String, val resultUsd: Double?, val closedAtMs: Long?)

    private fun rank(s: String) = when (s) {
        "TAKEN" -> 2
        "SKIPPED" -> 1
        else -> 0
    }

    /** True when the backup's copy of an entry carries more (or newer) owner information than the current one. */
    fun preferIncoming(cur: Mark, inc: Mark): Boolean = when {
        inc.resultUsd != null && cur.resultUsd == null -> true
        inc.resultUsd == null && cur.resultUsd != null -> false
        inc.resultUsd != null && cur.resultUsd != null -> (inc.closedAtMs ?: 0L) > (cur.closedAtMs ?: 0L)
        else -> rank(inc.userStatus) > rank(cur.userStatus)
    }

    /**
     * Which entries survive the inbox size limit: every trade the owner marked TAKEN (the journal) is
     * always kept; other alerts are kept newest first up to `limit`. Input is newest first.
     */
    fun <T> retain(list: List<T>, isJournal: (T) -> Boolean, limit: Int): List<T> {
        var others = 0
        return list.filter { e ->
            if (isJournal(e)) true else (others++ < limit)
        }
    }
}
