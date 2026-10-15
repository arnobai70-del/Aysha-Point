package com.ayesha.fx

import android.app.Activity
import android.os.Bundle
import android.text.InputType
import android.widget.CheckBox
import android.widget.EditText
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.Toast
import com.ayesha.fx.core.SettingsCheck
import com.ayesha.fx.core.Signer
import com.ayesha.fx.core.StrategyInfo

/** Capital & risk settings (spec O6). Risk is capped at 1% per trade. */
class SettingsActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        title = "Settings"
        val p = Prefs(this)
        val (sv, col) = Ui.screen(this)

        fun num(label: String, value: Double): EditText {
            col.addView(Ui.text(this, label, 13f, Ui.MUTED))
            val e = EditText(this)
            e.inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
            e.setText(value.toString())
            e.setTextColor(Ui.TEXT)
            col.addView(e)
            return e
        }

        val equity = num("Exness equity (USD) — Cent অ্যাকাউন্টে USC ÷ 100", p.equityUsd)
        val risk = num("প্রতি ট্রেডে risk % (০.১ থেকে ১)", p.riskPercent)
        val spread = num("আন্দাজি spread (pips)", p.spreadPips)
        val slip = num("Slippage buffer (pips)", p.slippagePips)

        col.addView(Ui.text(this, "Exness account type", 13f, Ui.MUTED))
        val group = RadioGroup(this)
        val std = RadioButton(this).apply { text = "Exness Standard, USD (1 lot = 100,000)"; setTextColor(Ui.TEXT); id = 101 }
        val cent = RadioButton(this).apply { text = "Exness Standard Cent, USC (1 lot = 1,000)"; setTextColor(Ui.TEXT); id = 102 }
        group.addView(std)
        group.addView(cent)
        group.check(if (p.accountType == "StandardCent") 102 else 101)
        col.addView(group)

        val noTrade = CheckBox(this).apply {
            text = "লট বড় হলেও (NO TRADE) নোটিফিকেশন দেখাও"
            setTextColor(Ui.TEXT)
            isChecked = p.alertNoTrade
        }
        col.addView(noTrade)

        col.addView(Ui.text(this, "Watchlist (এর বাইরের পেয়ারের অ্যালার্ট শুধু আর্কাইভে যাবে)", 13f, Ui.MUTED))
        val watchBoxes = StrategyInfo.PAIRS.map { pair ->
            CheckBox(this).apply {
                text = pair
                setTextColor(Ui.TEXT)
                isChecked = pair in p.watchlist
            }.also { col.addView(it) }
        }

        col.addView(Ui.text(this, "PC link (ঐচ্ছিক): PC-তে `ayesha pair` চালিয়ে যে কোড দেখায় সেটা লিখুন", 13f, Ui.MUTED))
        val code = EditText(this).apply {
            setText(p.pairingCode)
            hint = "ABCD-EFGH-JKMN-PQRS"
            setTextColor(Ui.TEXT)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS
        }
        col.addView(code)
        val link = CheckBox(this).apply {
            text = "PC scanner থেকে সিগন্যাল নাও (ntfy.sh relay দিয়ে)"
            setTextColor(Ui.TEXT)
            isChecked = p.linkEnabled
        }
        col.addView(link)
        col.addView(Ui.text(this,
            "চালু করলে ফোন ntfy.sh নামের একটা ফ্রি পাবলিক relay সার্ভারের সাথে যুক্ত থাকে। সেখানে শুধু সিগন্যাল যায় (পেয়ার, লেভেল, অবস্থা), " +
                "কোনো লগইন, ব্যালান্স বা পাসওয়ার্ড না। প্রতিটা বার্তা আপনার কোড দিয়ে সই করা; ভুল সই হলে বাদ। ফোন কিছু পাঠায় না।", 12f, Ui.MUTED))

        col.addView(Ui.button(this, "💾 Save", Ui.BULL) {
            val eq = equity.text.toString().trim().toDoubleOrNull() ?: Double.NaN
            val rk = risk.text.toString().trim().toDoubleOrNull() ?: Double.NaN
            val sp = spread.text.toString().trim().toDoubleOrNull() ?: Double.NaN
            val sl = slip.text.toString().trim().toDoubleOrNull() ?: Double.NaN
            val bad = SettingsCheck.problems(eq, rk, sp, sl)
            if (bad.isNotEmpty()) {
                Toast.makeText(this, bad.joinToString("\n"), Toast.LENGTH_LONG).show()
                return@button
            }
            p.equityUsd = eq
            p.riskPercent = rk
            p.spreadPips = sp
            p.slippagePips = sl
            val wantLink = link.isChecked
            val norm = Signer.normalize(code.text.toString())
            if (wantLink && norm == null) {
                Toast.makeText(this, "Pairing code ১৬ অক্ষরের হতে হবে (যেমন ABCD-EFGH-JKMN-PQRS)", Toast.LENGTH_LONG).show()
                return@button
            }
            val chosen = watchBoxes.filter { it.isChecked }.map { it.text.toString() }.toSet()
            if (chosen.isEmpty()) {
                Toast.makeText(this, "অন্তত একটা পেয়ার বাছুন", Toast.LENGTH_LONG).show()
                return@button
            }
            p.watchlist = chosen
            p.accountType = if (group.checkedRadioButtonId == 102) "StandardCent" else "Standard"
            p.alertNoTrade = noTrade.isChecked
            if (norm != null && norm != Signer.normalize(p.pairingCode)) p.linkLastId = ""
            p.pairingCode = norm ?: code.text.toString().trim()
            p.linkEnabled = wantLink
            if (wantLink) LinkService.start(this) else LinkService.stop(this)
            Toast.makeText(this, "Saved", Toast.LENGTH_SHORT).show()
            finish()
        })

        val paused = System.currentTimeMillis() < p.pausedUntilMs
        col.addView(Ui.button(this, if (paused) "▶ অ্যালার্ট আবার চালু করুন" else "⏸ আজকের জন্য অ্যালার্ট বন্ধ (১২ ঘণ্টা)", Ui.WATCH) {
            p.pausedUntilMs = if (paused) 0L else System.currentTimeMillis() + 12 * 3_600_000L
            Toast.makeText(this, if (paused) "চালু হয়েছে" else "১২ ঘণ্টা বন্ধ", Toast.LENGTH_SHORT).show()
            finish()
        })

        col.addView(Ui.text(this, "এখানে কোনো Exness লগইন বা পাসওয়ার্ড লাগে না, চাইবেও না।", 12f, Ui.MUTED))
        setContentView(sv)
    }
}
