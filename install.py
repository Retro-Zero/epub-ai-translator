#!/usr/bin/env python3
"""epub-ai-translator installer.

A single-file setup script. From a clean clone it:

1. Verifies Python 3.10+ and Node.js 18+ are on PATH
2. Creates a .venv (using uv if available, else python -m venv)
3. Installs backend dependencies (FastAPI, ebooklib, ...)
4. Installs frontend dependencies and runs `npm run build`
5. Copies .env.example to .env
6. Creates a runnable `translator.bat` launcher
7. Performs a smoke test of the server

Re-run safely: it skips steps whose artifacts already exist.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


# ---------- minimal ANSI colour helper ----------------------------------------

class Col:
    RESET = "\033[0m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"


def cprint(text: str, colour: str = ""):
    if sys.stdout.isatty():
        print(f"{colour}{text}{Col.RESET}")
    else:
        print(text)


# ---------- command helpers ---------------------------------------------------

def run(cmd, cwd=None, env=None, check=True, capture=False, timeout=None):
    """Run a command. Returns CompletedProcess. Raises on failure if check=True.

    On Windows, we always go through cmd.exe (shell=True) so .cmd/.bat shims
    like `npm`, `npx` on PATH are found reliably.
    """
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)

    use_shell = sys.platform == "win32" or isinstance(cmd, str)

    result = subprocess.run(
        cmd,
        cwd=cwd,
        env=merged_env,
        capture_output=capture,
        text=capture,
        shell=use_shell,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        msg = f"Command failed ({result.returncode}): {cmd}"
        if capture:
            msg += f"\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        raise RuntimeError(msg)
    return result


def cmd_output(cmd, cwd=None, timeout=30):
    """Return stripped stdout of a command or None on failure."""
    try:
        r = run(cmd, cwd=cwd, check=False, capture=True, timeout=timeout)
        return r.stdout.strip() if r.stdout else None
    except Exception:
        return None


def parse_version(out):
    """Extract a (major, minor, patch) tuple from a version string.

    Handles prefixes like 'v' and dot-separated numbers, e.g.
    "v24.11.1" -> (24, 11, 1), "Node.js v18.0.0" -> (18, 0, 0),
    "Python 3.13.2" -> (3, 13, 2), "2.4" -> (2, 4).
    """
    if not out:
        return None
    # pick the last token that contains a digit — robust to "Node.js v18.0.0"
    candidates = [t for t in out.replace("(", " ").replace(")", " ").split() if any(c.isdigit() for c in t)]
    if not candidates:
        return None
    token = candidates[-1]
    if token and token[0] in "vV":
        token = token[1:]
    nums = []
    for part in token.split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits:
            nums.append(int(digits))
        else:
            break
    if not nums:
        return None
    return tuple(nums[:3])


def which(name):
    """Locate an executable on PATH (Windows + Unix)."""
    suffix = ".exe" if sys.platform == "win32" else ""
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        p = Path(path_dir) / (name + suffix)
        if p.is_file():
            return p
    return None


# ---------- printer -----------------------------------------------------------

def banner(text):
    cprint(f"\n{'=' * 60}", Col.BLUE)
    cprint(f"  {text}", Col.BLUE)
    cprint(f"{'=' * 60}\n", Col.BLUE)


def step_ok(text):
    cprint(f"  [OK] {text}", Col.GREEN)


def step_info(text):
    cprint(f"  [..] {text}", Col.CYAN)


def step_warn(text):
    cprint(f"  [!!] {text}", Col.YELLOW)


def step_fail(text):
    cprint(f"  [FAIL] {text}", Col.RED)


# ---------- main --------------------------------------------------------------

def main():
    banner(" EPUB AI Translator - automated installer ")

    repo_root = Path(__file__).resolve().parent
    backend_dir = repo_root / "backend"
    frontend_dir = repo_root / "frontend"
    venv_dir = repo_root / ".venv"
    env_file = backend_dir / ".env"
    env_example = backend_dir / ".env.example"
    req_file = backend_dir / "requirements.txt"
    pkg_file = repo_root / "pyproject.toml"
    run_bat = repo_root / ("translator.bat" if sys.platform == "win32" else "translator.sh")

    # 1) Python
    step_info("Checking Python version ...")
    if sys.version_info < (3, 10):
        step_fail(f"Python {sys.version_info[0]}.{sys.version_info[1]} found - 3.10+ required")
        sys.exit(1)
    step_ok(f"Python {sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}")

    # 2) Node
    step_info("Checking Node.js ...")
    node_ver = parse_version(cmd_output(["node", "--version"]))
    if node_ver is None:
        step_fail("Node.js not found - install from https://nodejs.org (18+ required)")
        sys.exit(1)
    if node_ver < (18,):
        step_fail(f"Node.js {'.'.join(map(str, node_ver))} found - 18+ required")
        sys.exit(1)
    step_ok(f"Node.js {'.'.join(map(str, node_ver))}")

    npm_ver = parse_version(cmd_output(["npm", "--version"]))
    if npm_ver:
        step_ok(f"npm {'.'.join(map(str, npm_ver))}")

    # 3) Package manager
    step_info("Selecting package manager ...")
    has_uv = which("uv") is not None
    if has_uv:
        step_ok("uv detected (fast path)")
    else:
        step_warn("uv not found - falling back to pip (install from https://github.com/astral-sh/uv)")

    # 4) venv
    step_info("Creating Python virtual environment ...")
    if venv_dir.exists():
        step_warn(".venv already exists - skipping")
    else:
        if has_uv:
            run(["uv", "venv", "--python", sys.executable, str(venv_dir)], cwd=repo_root)
        else:
            run([sys.executable, "-m", "venv", str(venv_dir)], cwd=repo_root)
        step_ok(f".venv created at {venv_dir}")

    if sys.platform == "win32":
        python_venv = venv_dir / "Scripts" / "python.exe"
    else:
        python_venv = venv_dir / "bin" / "python"
    if not python_venv.exists():
        step_fail(f"venv python not found at {python_venv}")
        sys.exit(1)

    # 5) Backend deps
    step_info("Installing backend dependencies ...")
    if has_uv:
        install_cmd = ["uv", "pip", "install", "--python", str(python_venv)]
    else:
        install_cmd = [str(python_venv), "-m", "pip", "install"]

    if req_file.exists():
        run(install_cmd + ["-r", str(req_file)], cwd=repo_root)
    elif pkg_file.exists():
        run(install_cmd + ["-e", str(repo_root)], cwd=repo_root)
    else:
        step_warn("No requirements.txt or pyproject.toml - skipping backend install")
    step_ok("Backend dependencies installed")

    # 6) Frontend
    step_info("Installing and building frontend ...")
    if not frontend_dir.exists():
        step_warn("frontend/ not found - skipping frontend build")
    else:
        node_modules = frontend_dir / "node_modules"
        vite_bin = frontend_dir / "node_modules" / ".bin" / ("vite.cmd" if sys.platform == "win32" else "vite")
        if node_modules.exists() and vite_bin.exists():
            step_warn("node_modules + vite already present - skipping npm install")
        else:
            r = run(["npm", "install"], cwd=frontend_dir, check=False, timeout=600)
            if r.returncode != 0:
                step_fail("npm install failed - check your internet connection")
                sys.exit(1)
            step_ok("npm packages installed")

        r = run(["npm", "run", "build"], cwd=frontend_dir, check=False, timeout=300)
        if r.returncode != 0:
            step_fail("npm run build failed - try deleting frontend/node_modules and re-running")
            sys.exit(1)
        step_ok("Frontend built -> backend/static/")

    # 7) .env
    step_info("Setting up .env ...")
    if env_file.exists():
        step_warn(".env already exists - skipping")
    elif env_example.exists():
        shutil.copy2(env_example, env_file)
        step_ok(".env.example -> .env copied")
    else:
        env_file.write_text("", encoding="utf-8")
        step_warn("Empty .env created (no .env.example template found)")

    # 8) launcher
    step_info(f"Creating {run_bat.name} ...")
    if sys.platform == "win32":
        python_quoted = str(python_venv).replace("/", "\\")
        script = (
            "@echo off\r\n"
            "title EPUB AI Translator\r\n"
            f'cd /d "{backend_dir}"\r\n'
            f'start "" http://127.0.0.1:8000\r\n'
            f'"{python_quoted}" -m uvicorn app.main:app --port 8000 --host 127.0.0.1\r\n'
            "pause\r\n"
        )
    else:
        script = (
            "#!/bin/bash\n"
            f'cd "{backend_dir}"\n'
            f'"{python_venv}" -m uvicorn app.main:app --port 8000 --host 127.0.0.1\n'
        )
    run_bat.write_text(script, encoding="utf-8")
    if sys.platform != "win32":
        os.chmod(run_bat, 0o755)
    step_ok(f"{run_bat.name} created")

    # 9) smoke test
    banner(" smoke test ")
    step_info("Starting server in background for health check ...")
    srv = subprocess.Popen(
        [str(python_venv), "-m", "uvicorn", "app.main:app",
         "--port", "8000", "--host", "127.0.0.1"],
        cwd=str(backend_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=sys.platform == "win32",
    )
    try:
        deadline = time.time() + 20
        healthy = False
        while time.time() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as resp:
                    if resp.status == 200:
                        healthy = True
                        break
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(1)
        if healthy:
            step_ok("Server responded OK on http://127.0.0.1:8000")
        else:
            step_warn("Server did not respond in 20s - port 8000 may be in use")
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except subprocess.TimeoutExpired:
            srv.kill()

    # 10) final
    banner(" installation complete ")
    print()
    print("  How to run the app:")
    print()
    if sys.platform == "win32":
        print(f"    1. Double-click:  {run_bat}")
        print(f"    2. Or in terminal: .venv\\Scripts\\python.exe main.py")
    else:
        print(f"    1. Run:           bash {run_bat}")
        print(f"    2. Or in terminal: .venv/bin/python main.py")
    print()
    print("  Then open:  http://127.0.0.1:8000")
    print()
    print("  Tip: open Settings in the web UI to enter your API key,")
    print("       or enable Mock mode to test the whole pipeline for free.")
    print()
    print("  To stop the server: Ctrl+C in the terminal window.")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInstallation cancelled by user.")
        sys.exit(0)
    except Exception as e:
        step_fail(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
