"""Static isolation check (plan T05/T07, AI-006): the live path cannot reach research code, and research code cannot
reach the live path's side effects. Used by `ayesha research doctor` and `scripts/check_research_isolation.py` (CI).

Rules:
1. No legacy module imports `ayesha.research`. The only bridge is the lazy import inside `ayesha.cli.cmd_research`,
   which runs only when the owner types `ayesha research ...`.
2. Research modules do not import the phone/Telegram delivery, the live signal registry, the signing keys, the
   scanner, the capital file, the token store or the legacy doctor (all would be side effects on the live path).
3. Research modules use no eval/exec/compile/pickle/marshal/shelve/os.system and no shell=True; subprocess and
   ctypes only in the worker, network requests (urllib.request) only in the ingest adapter, the HTTP server only
   in the dashboard.
4. No research module contains the value "READY": a research decision can never be a READY signal.
5. The live Windows scripts never mention research, so installing, starting or restarting the scanner cannot
   start research.
"""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN = ("ayesha.delivery", "ayesha.storage", "ayesha.signing", "ayesha.scanner", "ayesha.capital",
             "ayesha.credentials", "ayesha.doctor", "MetaTrader5", "pickle", "marshal", "shelve")
ONLY_IN = {"subprocess": ("worker.py",), "ctypes": ("worker.py",), "urllib.request": ("datasets/ingest.py",),
           "urllib.error": ("datasets/ingest.py", "worker.py"),
           "http": ("dashboard/server.py",), "socketserver": ("dashboard/server.py",),
           "socket": ("dashboard/server.py",), "webbrowser": ("dashboard/server.py",)}
BAD_CALLS = {"eval", "exec", "compile", "__import__"}  # builtins
BAD_OS_CALLS = {"system", "popen", "startfile", "execl", "execle", "execlp", "execv", "execve", "execvp", "spawnl",
                "spawnle", "spawnv", "spawnve"}
LIVE_SCRIPTS = ("install.bat", "start-ayesha.bat", "run-scanner.bat", "backtest-local.bat", "make-signing-key.bat")
BRIDGE = ("cli.py", "cmd_research")


def _matches(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def _imports(tree: ast.AST, module: str) -> list[tuple[str, int, list[str]]]:
    """(imported module, line, enclosing function names) for every import, relative ones resolved."""
    out: list[tuple[str, int, list[str]]] = []

    def visit(node: ast.AST, funcs: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            f = funcs + [child.name] if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else funcs
            if isinstance(child, ast.Import):
                out.extend((a.name, child.lineno, f) for a in child.names)
            elif isinstance(child, ast.ImportFrom):
                base = child.module or ""
                if child.level:
                    parts = module.split(".")[:-child.level]
                    base = ".".join(parts + ([base] if base else []))
                out.append((base, child.lineno, f))
                out.extend((f"{base}.{a.name}", child.lineno, f) for a in child.names)
            visit(child, f)
    visit(tree, [])
    return out


def _module_name(pkg_root: Path, f: Path) -> str:
    rel = f.relative_to(pkg_root.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def check(pkg_root: Path, windows_dir: Path | None = None) -> list[str]:
    """`pkg_root` is the `ayesha` package folder. Returns violations (empty list = isolated)."""
    pkg_root = Path(pkg_root)
    research = pkg_root / "research"
    problems: list[str] = []
    for f in sorted(pkg_root.rglob("*.py")):
        rel = f.relative_to(pkg_root).as_posix()
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        mod = _module_name(pkg_root, f)
        imps = _imports(tree, mod)
        if research not in f.parents:
            for name, line, funcs in imps:
                if _matches(name, "ayesha.research") and not (rel == BRIDGE[0] and BRIDGE[1] in funcs):
                    problems.append(f"ayesha/{rel}:{line}: legacy code imports {name}")
            continue
        rrel = f.relative_to(research).as_posix()
        for name, line, _ in imps:
            for bad in FORBIDDEN:
                if _matches(name, bad):
                    problems.append(f"ayesha/{rel}:{line}: research imports {name}")
            for lib, allowed in ONLY_IN.items():
                if _matches(name, lib) and rrel not in allowed:
                    problems.append(f"ayesha/{rel}:{line}: {name} is only allowed in {', '.join(allowed)}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id in BAD_CALLS:
                    problems.append(f"ayesha/{rel}:{node.lineno}: call to {fn.id}()")
                if (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "os"
                        and fn.attr in BAD_OS_CALLS):
                    problems.append(f"ayesha/{rel}:{node.lineno}: call to os.{fn.attr}()")
                for kw in node.keywords:
                    if kw.arg == "shell" and not (isinstance(kw.value, ast.Constant) and kw.value.value is False):
                        problems.append(f"ayesha/{rel}:{node.lineno}: shell=True")
            if isinstance(node, ast.Constant) and node.value == "READY" and rrel != "isolation.py":  # (the rule itself)
                problems.append(f"ayesha/{rel}:{node.lineno}: research code contains the value 'READY'")
    if windows_dir is not None:
        for name in LIVE_SCRIPTS:
            p = Path(windows_dir) / name
            if p.exists() and "research" in p.read_text(encoding="utf-8", errors="replace").lower():
                problems.append(f"desktop/windows/{name}: a live script mentions research")
    return problems
