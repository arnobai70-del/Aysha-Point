package com.ayesha.fx

import android.app.Activity
import android.os.Bundle
import android.text.InputType
import android.widget.CheckBox
import android.widget.EditText
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.Toast

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
        val std = RadioButton(this).apply { text = "Standard (1 lot = 100,000)"; setTextColor(Ui.TEXT); id = 101 }
        val cent = RadioButton(this).apply { text = "Standard Cent (1 lot = 1,000)"; setTextColor(Ui.TEXT); id = 102 }
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

        col.addView(Ui.button(this, "💾 Save", Ui.BULL) {
            p.equityUsd = equity.text.toString().toDoubleOrNull() ?: p.equityUsd
            p.riskPercent = risk.text.toString().toDoubleOrNull() ?: p.riskPercent
            p.spreadPips = spread.text.toString().toDoubleOrNull() ?: p.spreadPips
            p.slippagePips = slip.text.toString().toDoubleOrNull() ?: p.slippagePips
            p.accountType = if (group.checkedRadioButtonId == 102) "StandardCent" else "Standard"
            p.alertNoTrade = noTrade.isChecked
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
