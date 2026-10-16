"""Research strategies (plan §6, v1.0.0 Strategy Lab): built-in, allow-listed, research-only plugins.

A: `baseline-sweep-mss-fvg`, the frozen live rule set, wrapped unchanged.
B: `control-london-orb`, a pre-registered London opening-range breakout control.
C: `experimental-h1h4-trend`, the one experimental strategy (H4/H1 trend continuation after an H1 pullback).

None of them can produce a live signal: every output is a research candidate with `executable: false`.
"""
