"""Research worker: every heavy research job runs in its own child process, never inside the live scanner.

    python -m ayesha.research.worker --job-file <research>/jobs/<job_id>.json

The supervisor (`run_job`, used by `ayesha research ...`) writes the job file, starts the child at low priority and
watches it. The child takes the single research lock, applies its limits, runs one job and writes a result file.
Isolation and fail-safe rules (plan AI-006, T07):

* A separate process: a crash, a hang or a memory blow-up in research cannot stop or slow the scanner process,
  which never imports research code and never reads research files.
* Priority: Windows BELOW_NORMAL priority class, POSIX nice +10, so the scanner gets the CPU first.
* Windows Job Object: hard CPU cap (`cpu_limit_percent` of the whole PC), per-process memory cap
  (`memory_limit_mb`) and kill-on-close, so a worker never outlives its supervisor. POSIX: RLIMIT_AS memory cap and
  a parent watchdog (no hard CPU percentage cap there; priority only).
* Timeout: the supervisor kills a job that runs longer than `job_timeout_seconds` (status TIMEOUT).
* One writer: the lock is held by the worker that writes; when it dies the OS releases the lock, and the next
  command marks whatever it left RUNNING as FAILED_INCOMPLETE / CRASHED (nothing partial is ever committed).
* Logs go through the redaction filter; the job file never holds a token (OANDA reads it from the owner's
  credential store inside the worker, exactly like the scanner does).

Exit codes: 0 OK, 2 REFUSED (bad input, research off, data rejected), 3 RESOURCE_LIMIT, 70 FAILED (unexpected
error), 75 BUSY (another research job holds the lock), 130 CANCELLED; anything else is CRASHED.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

EXIT_OK, EXIT_REFUSED, EXIT_RESOURCE, EXIT_FAILED, EXIT_BUSY, EXIT_CANCELLED = 0, 2, 3, 70, 75, 130
STATUS_BY_EXIT = {EXIT_OK: "OK", EXIT_REFUSED: "REFUSED", EXIT_RESOURCE: "RESOURCE_LIMIT", EXIT_FAILED: "FAILED",
                  EXIT_CANCELLED: "CANCELLED"}
KINDS = ("ingest_csv", "ingest_oanda", "baseline", "parity", "strategy", "lab", "compare", "news_ingest",
         "feed_audit", "selftest")
SELFTESTS = ("ok", "crash", "hang", "memory")
LOCK_OFFSET = 1 << 20  # Windows: lock a byte far past the PID text so other processes can still read the PID


class WorkerBusy(RuntimeError):
    """Another research job is running (one research writer at a time)."""


# --- the single-writer lock ---------------------------------------------------------------------

class JobLock:
    """OS file lock (released by the OS when the holder dies, even on a crash or a kill)."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.fd: int | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self.fd = fd
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, f"{os.getpid():<12}\n".encode())
        except OSError:
            pass
        return True

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(self.fd, LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(self.fd)
            self.fd = None

    def held_by_other(self) -> bool:
        if self.acquire():
            self.release()
            return False
        return True


def lock_for(root: Path) -> JobLock:
    return JobLock(Path(root) / "jobs" / "worker.lock")


# --- limits -----------------------------------------------------------------------------------

def _posix_limits(limits: dict[str, Any]) -> list[str]:
    applied = []
    try:
        os.nice(10)
        applied.append("nice+10")
    except (AttributeError, OSError):
        pass
    try:
        import resource

        cap = int(limits["memory_limit_mb"]) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        applied.append(f"RLIMIT_AS={limits['memory_limit_mb']}MB")
    except (ImportError, ValueError, OSError):
        pass
    return applied


def _parent_watchdog(ppid: int) -> None:
    """POSIX: if the supervisor dies, stop at once instead of running on unsupervised."""
    def watch() -> None:
        while True:
            time.sleep(1.0)
            if os.getppid() != ppid:
                os._exit(71)
    threading.Thread(target=watch, daemon=True, name="parent-watchdog").start()


class _WindowsJob:
    """CPU hard cap + memory cap + kill-on-close for one child, through a Windows Job Object (ctypes, stdlib)."""

    def __init__(self, pid: int, memory_mb: int, cpu_percent: int) -> None:
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount",
                                                          "OtherOperationCount", "ReadTransferCount",
                                                          "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        class CPU_RATE(ctypes.Structure):
            _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]

        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.restype = wintypes.BOOL
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.AssignProcessToJobObject.restype = wintypes.BOOL
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.k32, self.applied = k32, []
        self.handle = k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        info = EXTENDED()
        info.BasicLimitInformation.LimitFlags = 0x0100 | 0x0400 | 0x2000  # PROCESS_MEMORY | DIE_ON_UNHANDLED | KILL_ON_CLOSE
        info.ProcessMemoryLimit = int(memory_mb) * 1024 * 1024
        if k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.applied += [f"job-memory={memory_mb}MB", "kill-on-close"]
        cpu = CPU_RATE(0x1 | 0x4, int(cpu_percent) * 100)  # ENABLE | HARD_CAP; rate per 10,000 cycles
        if k32.SetInformationJobObject(self.handle, 15, ctypes.byref(cpu), ctypes.sizeof(cpu)):
            self.applied.append(f"job-cpu-cap={cpu_percent}%")
        ph = k32.OpenProcess(0x0100 | 0x0001, False, pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        try:
            if not ph or not k32.AssignProcessToJobObject(self.handle, ph):
                self.applied = []
                raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
        finally:
            if ph:
                k32.CloseHandle(ph)

    def close(self) -> None:
        if self.handle:
            self.k32.CloseHandle(self.handle)
            self.handle = None


# --- child side -----------------------------------------------------------------------------------

def _write_result(path: Path, data: dict[str, Any]) -> None:
    from ayesha.research.datasets.store import atomic_write

    atomic_write(path, json.dumps(data, indent=1, default=str, ensure_ascii=False).encode("utf-8"))


def _selftest(mode: str, limits: dict[str, Any]) -> dict[str, Any]:
    if mode == "ok":
        return {"selftest": "ok", "pid": os.getpid()}
    if mode == "crash":
        print("selftest: simulating a hard crash", flush=True)
        os._exit(13)
    if mode == "hang":
        print("selftest: simulating a hang", flush=True)
        while True:
            time.sleep(0.2)
    if mode == "memory":
        print("selftest: allocating memory until the limit stops it", flush=True)
        hold, cap = [], int(limits["memory_limit_mb"]) * 2
        for _ in range(cap // 16):
            hold.append(bytearray(16 * 1024 * 1024))
        return {"selftest": "memory", "limited": False, "allocated_mb": 16 * len(hold)}
    raise ValueError(f"unknown selftest {mode!r}")


def _dispatch(job: dict[str, Any]) -> dict[str, Any]:
    from ayesha.config import load_spec
    from ayesha.research.config import load, require_enabled
    from ayesha.research.workspace import Workspace

    kind, a, root = job["kind"], job["args"], Path(job["root"])
    if kind == "selftest":
        return _selftest(a["mode"], job["limits"])
    cfg = load(root / "config.yaml")
    require_enabled(cfg)
    ws = Workspace(cfg, root)
    try:
        ws.db.reconcile()
        spec = load_spec(a.get("spec"))
        if kind == "ingest_csv":
            from ayesha.research.datasets.ingest import ingest_csv_dir

            return ingest_csv_dir(ws, a["folder"], spec, provider=a.get("provider") or "CSV_IMPORT",
                                  label=a.get("label") or "", pairs=a.get("pairs"))
        if kind == "ingest_oanda":
            from ayesha.research.datasets.ingest import ingest_oanda

            return ingest_oanda(ws, spec, a["pairs"], int(a["days"]), timeframes=tuple(a["timeframes"]),
                                environment=a.get("environment") or "practice", label=a.get("label") or "")
        if kind == "baseline":
            from ayesha.research.simulation.baseline import run_baseline

            return run_baseline(ws, spec, a["dataset_id"], a["symbol"], mode=a.get("mode") or "m15",
                                split=a.get("split"), folds=int(a.get("folds") or 4),
                                account_type=a.get("account_type") or "Standard",
                                allow_degraded=bool(a.get("allow_degraded")), verify=bool(a.get("verify")))
        if kind == "parity":
            from ayesha.research.evaluation.parity import parity

            return parity(ws, spec, a["dataset_id"], a["symbol"], mode=a.get("mode") or "m15",
                          legacy_csv=a.get("legacy_csv"), account_type=a.get("account_type") or "Standard")
        if kind == "strategy":
            from ayesha.research.simulation.lab import run_strategy

            return run_strategy(ws, spec, a["strategy_id"], a["dataset_id"], a["symbols"], **_lab_args(a),
                                verify=bool(a.get("verify")))
        if kind == "lab":
            from ayesha.research.evaluation.comparison import run_lab

            return run_lab(ws, spec, a["dataset_id"], a["symbols"], **_lab_args(a))
        if kind == "compare":
            from ayesha.research.evaluation.comparison import compare

            d = compare(ws, list(a["run_ids"]))
            return {"comparison_id": d["comparison_id"], "ranking": d["ranking"]["state"],
                    "benchmark_parity": d["benchmark_parity"].get("status")}
        if kind == "news_ingest":
            from ayesha.research.datasets.news_snapshot import ingest

            return ingest(ws, a["file"], a.get("provider") or "", a.get("license") or "", label=a.get("label") or "")
        if kind == "feed_audit":
            from ayesha.research.datasets.feed_audit import audit

            d = audit(ws, a["dataset_a"], a["dataset_b"], a["symbol"], a.get("timeframe") or "M15")
            return {"feed_audit_id": d["feed_audit_id"], "status": d["status"],
                    "common_bars": d["overlap"]["common_bars"], "close_p95_pips": d["differences"]["close"]["p95"]}
        raise ValueError(f"unknown job kind {kind!r}")
    finally:
        ws.close()


def _lab_args(a: dict[str, Any]) -> dict[str, Any]:
    return {"folds": int(a.get("folds") or 4), "split": a.get("split"), "holdout": a.get("holdout"),
            "reveal_holdout": bool(a.get("reveal_holdout")), "account_type": a.get("account_type") or "Standard",
            "allow_degraded": bool(a.get("allow_degraded")), "robustness": not a.get("quick"),
            "news_snapshot_id": a.get("news") or None, "news_mode": a.get("news_mode") or "upgraded"}


def _refusals() -> tuple[type[BaseException], ...]:
    from ayesha.feed.oanda_feed import AuthRejected, MissingToken
    from ayesha.research.config import ResearchConfigError, ResearchDisabled
    from ayesha.research.contracts import ContractError
    from ayesha.research.datasets.ingest import IngestError
    from ayesha.research.datasets.news_snapshot import NewsSnapshotError
    from ayesha.research.datasets.store import IntegrityError
    from ayesha.research.simulation.baseline import RunRefused
    from ayesha.research.storage.db import ResearchDBError
    from ayesha.research.strategies.loader import StrategyError

    return (ResearchDisabled, ResearchConfigError, ContractError, IngestError, IntegrityError, RunRefused,
            ResearchDBError, StrategyError, NewsSnapshotError, AuthRejected, MissingToken, FileNotFoundError,
            NotADirectoryError, KeyError)


def child_main(argv: list[str] | None = None) -> int:
    from ayesha.research.redact import RedactingWriter, redact

    ap = argparse.ArgumentParser(prog="python -m ayesha.research.worker")
    ap.add_argument("--job-file", required=True)
    a = ap.parse_args(argv)
    job_file = Path(a.job_file)
    job = json.loads(job_file.read_text(encoding="utf-8"))
    sys.stdout, sys.stderr = RedactingWriter(sys.stdout), RedactingWriter(sys.stderr)
    applied: list[str] = []
    if os.name != "nt":
        applied += _posix_limits(job["limits"])
        _parent_watchdog(int(job["supervisor_pid"]))
    own = ",".join(applied) or ("set by the launcher" if os.name == "nt" else "none")  # Windows: job object
    print(f"worker {job['job_id']} kind={job['kind']} pid={os.getpid()} limits={own}", flush=True)
    result_file = job_file.with_suffix(".result.json")
    lock = lock_for(Path(job["root"]))
    if not lock.acquire():
        _write_result(result_file, {"status": "BUSY", "error": "another research job is running"})
        return EXIT_BUSY
    code, out = EXIT_FAILED, {}
    try:
        out = {"status": "OK", "result": _dispatch(job)}
        code = EXIT_OK
    except MemoryError:
        out, code = {"status": "RESOURCE_LIMIT", "error": f"memory limit ({job['limits']['memory_limit_mb']} MB) "
                                                         "reached; the job stopped and nothing partial was kept"}, \
            EXIT_RESOURCE
    except KeyboardInterrupt:
        out, code = {"status": "CANCELLED", "error": "cancelled"}, EXIT_CANCELLED
    except Exception as e:  # noqa: BLE001 - every failure must end as a recorded status, never a silent exit
        if isinstance(e, _refusals()):
            out, code = {"status": "REFUSED", "error": redact(f"{type(e).__name__}: {e}")}, EXIT_REFUSED
        else:
            traceback.print_exc()
            out, code = {"status": "FAILED", "error": redact(f"{type(e).__name__}: {e}")}, EXIT_FAILED
    finally:
        try:
            out["limits_applied"] = applied
            _write_result(result_file, out)
        except Exception:  # noqa: BLE001 - e.g. no memory left to write; the exit code still says what happened
            pass
        lock.release()
    print(f"worker {job['job_id']} finished: {out.get('status')}", flush=True)
    return code


# --- supervisor side ----------------------------------------------------------------------------

def _new_job_id() -> str:
    return "job_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "_" + secrets.token_hex(4)


def run_job(ws, kind: str, args: dict[str, Any], timeout: float | None = None,
            echo: Callable[[str], None] | None = None, stop: threading.Event | None = None) -> dict[str, Any]:
    """Run one research job in a child process and record it in research_jobs. Returns the job record.
    `stop` (optional) cancels the job from another thread: the child is killed and the job ends CANCELLED."""
    from ayesha.research.datasets.store import atomic_write
    from ayesha.research.redact import redact_obj

    if kind not in KINDS:
        raise ValueError(f"unknown job kind {kind!r}")
    if kind == "selftest" and args.get("mode") not in SELFTESTS:
        raise ValueError(f"selftest mode must be one of {SELFTESTS}")
    r = ws.cfg.r
    limits = {"memory_limit_mb": r["memory_limit_mb"], "cpu_limit_percent": r["cpu_limit_percent"],
              "job_timeout_seconds": r["job_timeout_seconds"]}
    timeout = float(timeout if timeout is not None else limits["job_timeout_seconds"])
    lock = lock_for(ws.root)
    if not lock.acquire():
        raise WorkerBusy("another research job is running; wait for it to finish (see: ayesha research status)")
    try:
        ws.db.reconcile()  # nobody holds the lock, so anything still RUNNING was left by a dead worker
    finally:
        lock.release()
    job_id = _new_job_id()
    job_file = ws.jobs / f"{job_id}.json"
    log_rel = f"logs/{job_id}.log"
    log_path = ws.root / log_rel
    ws.logs  # creates the folder
    job = {"job_id": job_id, "kind": kind, "args": args, "root": str(ws.root), "limits": limits,
           "supervisor_pid": os.getpid()}
    atomic_write(job_file, json.dumps(job, indent=1, ensure_ascii=False).encode("utf-8"))
    ws.db.job_start(job_id, kind, redact_obj(args))
    env = dict(os.environ)
    pkg_root = str(Path(__file__).resolve().parents[2])  # import the same ayesha code as this process
    env["PYTHONPATH"] = pkg_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [sys.executable, "-m", "ayesha.research.worker", "--job-file", str(job_file)]
    flags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) if os.name == "nt" else 0
    started = time.monotonic()
    winjob = None
    status, code = "CRASHED", None
    with open(log_path, "wb") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                                creationflags=flags)
        applied = ["below-normal-priority"] if os.name == "nt" else []
        if os.name == "nt":
            try:
                winjob = _WindowsJob(proc.pid, limits["memory_limit_mb"], limits["cpu_limit_percent"])
                applied += winjob.applied
            except OSError as e:
                applied.append(f"job-object-unavailable({e.args[0] if e.args else '?'})")
            if echo:
                echo(f"launcher limits: {', '.join(applied)}")
        pos = 0
        try:
            while True:
                try:
                    code = proc.wait(timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if echo:
                    pos = _tail(log_path, pos, echo)
                if time.monotonic() - started > timeout:
                    proc.kill()
                    proc.wait()
                    status, code = "TIMEOUT", None
                    break
                if stop is not None and stop.is_set():
                    proc.kill()
                    proc.wait()
                    status, code = "CANCELLED", None
                    break
        except KeyboardInterrupt:
            proc.kill()
            proc.wait()
            status, code = "CANCELLED", None
        finally:
            if winjob is not None:
                winjob.close()
    if echo:
        _tail(log_path, pos, echo)
    result_file = job_file.with_suffix(".result.json")
    result: dict[str, Any] = {}
    if result_file.exists():
        try:
            result = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result = {}
    if code is not None:
        status = "BUSY" if code == EXIT_BUSY else STATUS_BY_EXIT.get(code, "CRASHED")
    if status == "BUSY":
        ws.db.job_finish(job_id, "REFUSED", code, {"error": "another research job is running"}, log_rel)
        raise WorkerBusy("another research job started first; try again when it has finished")
    if status in ("CRASHED", "TIMEOUT", "CANCELLED"):
        result.setdefault("error", {"CRASHED": f"worker stopped unexpectedly (exit code {code})",
                                    "TIMEOUT": f"stopped after the {int(timeout)} s job timeout",
                                    "CANCELLED": "cancelled"}[status])
    result["limits_applied"] = applied + [x for x in result.get("limits_applied", []) if x not in applied]
    result["elapsed_seconds"] = round(time.monotonic() - started, 2)
    ws.db.job_finish(job_id, status, code, redact_obj(json.loads(json.dumps(result, default=str))), log_rel)
    if status != "OK":
        ws.db.reconcile()  # the worker is gone: a run it left RUNNING becomes FAILED_INCOMPLETE
    return {"job_id": job_id, "status": status, "exit_code": code, "log": log_rel, **result}


def _tail(path: Path, pos: int, echo: Callable[[str], None]) -> int:
    try:
        with open(path, "rb") as f:
            f.seek(pos)
            data = f.read()
    except OSError:
        return pos
    if not data:
        return pos
    nl = data.rfind(b"\n")
    if nl < 0:
        return pos
    for line in data[:nl].decode("utf-8", "replace").splitlines():
        echo(line)
    return pos + nl + 1


if __name__ == "__main__":
    sys.exit(child_main())
