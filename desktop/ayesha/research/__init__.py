"""AYESHA research plane (Hybrid AI master plan: v0.9.0 "research foundation", v1.0.0 "Strategy Lab").

What it is: frozen, content-hashed market-data snapshots with quality reports, a separate research registry
(`%AYESHA_HOME%/research/research.db`), a replay of the frozen legacy setup on those snapshots, an isolated worker
process and a local read-only dashboard; since v1.0.0 a Strategy Lab that replays the baseline, one control and one
experimental strategy through one common runner and compares them on the same data, split, costs and accounts.

What it is not: a signal source. Research is OFF by default, never produces READY, never sends anything to the
phone, never writes the live signal registry (`ayesha.db`) and never places, modifies or closes an order. The live
scanner, risk engine, news guard and capital code do not import this package; `scripts/check_research_isolation.py`
fails CI if they ever do. Results are historical simulations, not forecasts.
"""

RESEARCH_VERSION = "1.0.0"
