"""`ayesha research doctor`: health of the research plane, and proof that it is isolated from the live path.

Read-only: it never repairs, deletes or re-runs anything (a stale RUNNING job is only reported; the next research
command marks it). Only `--selftest` writes: it records one selftest job. Works with research turned off, and
without a research folder.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ayesha.research.config import ResearchConfigError, load, research_home
from ayesha.research.provenance import digest

OK, WARN, FAIL, INFO = "OK", "WARN", "FAIL", "INFO"


@dataclass
class Check:
    state: str
    name: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"state": self.state, "name": self.name, "detail": self.detail}


def run_doctor(root: Path | None = None, deep: bool = False, selftest: bool = False,
               now: datetime | None = None) -> list[Check]:
    from ayesha import __version__
    from ayesha.config import load_spec
    from ayesha.research import RESEARCH_VERSION
    from ayesha.research.isolation import check as isolation_check
    from ayesha.research.readonly import legacy_summary
    from ayesha.research.worker import lock_for

    root = Path(root) if root else research_home()
    now = now or datetime.now(timezone.utc)
    out: list[Check] = []
    spec = load_spec()
    out.append(Check(INFO, "versions", f"desktop {__version__}, research {RESEARCH_VERSION}, strategy "
                                       f"{spec['strategy_version']} hash {spec['strategy_hash']} (unchanged by research)"))
    cfg = None
    try:
        cfg = load(root / "config.yaml")
        out.append(Check(OK, "config", ("research ON (research-only)" if cfg.enabled else "research OFF (legacy_only)")
                         + ("" if cfg.file_exists else "; no config file yet, safe defaults")))
    except ResearchConfigError as e:
        out.append(Check(FAIL, "config", f"{e}. Research stays off; fix the file or run: ayesha research disable"))

    pkg = Path(__file__).resolve().parents[1]
    bad = isolation_check(pkg, pkg.parent / "windows")
    out.append(Check(OK if not bad else FAIL, "isolation",
                     "the scanner cannot import research; research cannot reach phone, signing, token or the live "
                     "registry" if not bad else "; ".join(bad[:5])))

    leg = legacy_summary(now=now)
    if not leg["present"]:
        out.append(Check(INFO, "live registry", "ayesha.db not found (the scanner has not run on this PC yet)"))
    elif not leg.get("readable"):
        out.append(Check(WARN, "live registry", f"ayesha.db could not be read read-only ({leg.get('error')})"))
    else:
        last = leg.get("health", [{}])[0] if leg.get("health") else {}
        out.append(Check(OK, "live registry", "read-only access works; last scanner health: "
                         + (f"{last.get('state')} at {last.get('at_utc')}" if last else "none recorded")))

    dbp = root / "research.db"
    if not dbp.exists():
        out.append(Check(INFO, "research registry", "not created yet (no research data on this PC)"))
        if selftest:
            out.append(_selftest(cfg, root))
        return out

    from ayesha.research.readonly import open_ro

    con = open_ro(dbp)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        ver = con.execute("SELECT v FROM research_schema_version").fetchone()
        out.append(Check(OK if integrity == "ok" else FAIL, "research registry",
                         f"integrity {integrity}, schema v{ver[0] if ver else '?'}"))
        out.append(_chain(con))
        lock_busy = lock_for(root).held_by_other()
        stale_jobs = con.execute("SELECT COUNT(*) FROM research_jobs WHERE status='RUNNING'").fetchone()[0]
        stale_runs = con.execute("SELECT COUNT(*) FROM research_runs WHERE status='RUNNING'").fetchone()[0]
        if lock_busy:
            out.append(Check(INFO, "worker", "a research job is running now"))
        elif stale_jobs or stale_runs:
            out.append(Check(WARN, "worker", f"{stale_jobs} job(s) / {stale_runs} run(s) were left RUNNING by a "
                                             "stopped worker; the next research command marks them CRASHED / "
                                             "FAILED_INCOMPLETE (nothing partial was kept)"))
        else:
            out.append(Check(OK, "worker", "idle, nothing left running"))
        out.append(_artifacts(con, root, deep))
        out.append(_manifests(con, root))
        out.append(_backups(root, con, now))
    finally:
        con.close()
    try:
        free = shutil.disk_usage(root).free
        out.append(Check(OK if free > 1 << 30 else WARN, "disk", f"{free / (1 << 30):.1f} GB free"
                         + ("" if free > 1 << 30 else ": below 1 GB, downloads may fail")))
    except OSError:
        pass
    if selftest:
        out.append(_selftest(cfg, root))
    return out


def _chain(con) -> Check:
    from ayesha.research.storage.db import GENESIS, _event_hash

    prior, n = GENESIS, 0
    for r in con.execute("SELECT * FROM research_events ORDER BY id"):
        n += 1
        if r["prior_hash"] != prior or _event_hash(prior, r["at_utc"], r["actor"], r["operation"], r["target"],
                                                   r["detail_json"]) != r["resulting_hash"]:
            return Check(FAIL, "audit trail", f"event {r['id']} was changed or removed after it was written")
        prior = r["resulting_hash"]
    return Check(OK, "audit trail", f"{n} events, hash chain intact")


def _artifacts(con, root: Path, deep: bool) -> Check:
    from ayesha.research.datasets.store import ArtifactStore, IntegrityError

    store = ArtifactStore(root)
    missing, corrupt, n = [], [], 0
    for r in con.execute("SELECT sha256, kind, relpath, bytes FROM artifacts"):
        n += 1
        p = root / r["relpath"]
        if not p.exists():
            missing.append(r["relpath"])
            continue
        if deep:
            name = Path(r["relpath"]).name
            compressed = name.endswith(".gz")
            ext = "".join(Path(name[:-3] if compressed else name).suffixes)
            try:
                if r["kind"] in ("normalized", "candidates") and compressed:
                    for _ in store.iter_lines(r["kind"], r["sha256"], ext):
                        pass
                else:
                    store.get(r["kind"], r["sha256"], ext, compressed)
            except IntegrityError:
                corrupt.append(r["relpath"])
        elif p.stat().st_size != r["bytes"]:
            corrupt.append(r["relpath"])
    if missing or corrupt:
        return Check(FAIL, "artifacts", f"{len(missing)} missing, {len(corrupt)} changed of {n}: "
                                        + ", ".join((missing + corrupt)[:3]) + "; runs using them are refused")
    return Check(OK, "artifacts", f"{n} files present" + (", every hash verified" if deep else
                                                          " (sizes checked; --deep verifies every hash)"))


def _manifests(con, root: Path) -> Check:
    bad, n = [], 0
    for r in con.execute("SELECT dataset_id, manifest_hash, manifest_json FROM datasets"):
        n += 1
        m = json.loads(r["manifest_json"])
        if digest(m) != r["manifest_hash"]:
            bad.append(f"{r['dataset_id']} (registry copy)")
        f = root / "manifests" / f"{r['dataset_id']}.json"
        if f.exists() and digest(json.loads(f.read_text(encoding="utf-8"))) != r["manifest_hash"]:
            bad.append(f"{r['dataset_id']} (file)")
    return Check(OK if not bad else FAIL, "datasets", f"{n} frozen dataset(s), manifests match their hashes"
                 if not bad else "manifest changed after freezing: " + ", ".join(bad[:3]))


def _backups(root: Path, con, now: datetime) -> Check:
    files = sorted((root / "backups").glob("research-*.db")) if (root / "backups").exists() else []
    has_data = con.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] > 0
    if not files:
        return Check(WARN if has_data else INFO, "backups", "no registry backup yet: run ayesha research backup")
    last = files[-1]
    sidecar = last.with_suffix(".db.sha256")
    try:
        stamp = datetime.strptime(last.stem.split("-", 1)[1][:15], "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
        age = (now - stamp).days
    except ValueError:
        age = None
    state = OK if sidecar.exists() and (age is None or age <= 7) else WARN
    return Check(state, "backups", f"{len(files)} backup(s), newest {last.name}"
                 + (f" ({age} day(s) old)" if age is not None else "")
                 + ("" if sidecar.exists() else "; its .sha256 file is missing"))


def _selftest(cfg, root: Path) -> Check:
    from ayesha.research.config import DEFAULTS, ResearchConfig
    from ayesha.research.worker import WorkerBusy, run_job
    from ayesha.research.workspace import Workspace

    ws = Workspace(cfg or ResearchConfig(DEFAULTS, root / "config.yaml", False), root)
    try:
        r = run_job(ws, "selftest", {"mode": "ok"}, timeout=60)
    except WorkerBusy as e:
        return Check(INFO, "worker selftest", str(e))
    finally:
        ws.close()
    return Check(OK if r["status"] == "OK" else FAIL, "worker selftest",
                 f"{r['status']} in a separate process ({', '.join(r.get('limits_applied') or []) or 'no limits'})")


def as_json(checks: list[Check]) -> str:
    return json.dumps([c.as_dict() for c in checks], indent=2, ensure_ascii=False)

