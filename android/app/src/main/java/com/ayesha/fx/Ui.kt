package com.ayesha.fx

import android.content.Context
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** Tiny programmatic UI kit (no extra libraries). Dark theme colours from the spec palette. */
object Ui {
    val BG = Color.parseColor("#0F172A")
    val CARD = Color.parseColor("#1E293B")
    val TEXT = Color.parseColor("#E2E8F0")
    val MUTED = Color.parseColor("#94A3B8")
    val BULL = Color.parseColor("#16A34A")
    val BEAR = Color.parseColor("#DC2626")
    val WATCH = Color.parseColor("#EAB308")
    val SKY = Color.parseColor("#38BDF8")
    val OFF = Color.parseColor("#64748B")

    fun dp(c: Context, v: Int): Int = (v * c.resources.displayMetrics.density).toInt()

    fun screen(c: Context): Pair<ScrollView, LinearLayout> {
        val col = LinearLayout(c)
        col.orientation = LinearLayout.VERTICAL
        col.setPadding(dp(c, 16), dp(c, 16), dp(c, 16), dp(c, 24))
        val sv = ScrollView(c)
        sv.setBackgroundColor(BG)
        sv.addView(col, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        return sv to col
    }

    fun text(c: Context, s: CharSequence, size: Float = 15f, color: Int = TEXT, bold: Boolean = false): TextView {
        val t = TextView(c)
        t.text = s
        t.textSize = size
        t.setTextColor(color)
        t.setLineSpacing(0f, 1.15f)
        if (bold) t.setTypeface(t.typeface, Typeface.BOLD)
        t.setPadding(0, dp(c, 2), 0, dp(c, 2))
        return t
    }

    fun card(c: Context, accent: Int = SKY): LinearLayout {
        val l = LinearLayout(c)
        l.orientation = LinearLayout.VERTICAL
        l.setPadding(dp(c, 14), dp(c, 12), dp(c, 14), dp(c, 12))
        val bg = GradientDrawable()
        bg.setColor(CARD)
        bg.cornerRadius = dp(c, 12).toFloat()
        bg.setStroke(dp(c, 1), accent)
        l.background = bg
        val lp = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        lp.setMargins(0, dp(c, 6), 0, dp(c, 6))
        l.layoutParams = lp
        return l
    }

    fun button(c: Context, label: String, color: Int = SKY, onClick: (View) -> Unit): Button {
        val b = Button(c)
        b.text = label
        b.isAllCaps = false
        b.setTextColor(Color.WHITE)
        val bg = GradientDrawable()
        bg.setColor(color)
        bg.cornerRadius = dp(c, 10).toFloat()
        b.background = bg
        b.setPadding(dp(c, 12), dp(c, 8), dp(c, 12), dp(c, 8))
        b.setOnClickListener(onClick)
        val lp = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        lp.setMargins(0, dp(c, 6), 0, dp(c, 6))
        b.layoutParams = lp
        b.gravity = Gravity.CENTER
        return b
    }

    fun row(c: Context, vararg views: View): LinearLayout {
        val l = LinearLayout(c)
        l.orientation = LinearLayout.HORIZONTAL
        for (v in views) {
            val lp = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            lp.setMargins(dp(c, 3), 0, dp(c, 3), 0)
            l.addView(v, lp)
        }
        return l
    }
}
