from __future__ import annotations

import subprocess
import sys
import time
import os
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def find_bundled_node() -> Path | None:
    configured = os.environ.get("CODEX_NODE_PATH")
    if configured and Path(configured).is_file():
        return Path(configured)
    cache_root = Path.home() / ".cache" / "codex-runtimes"
    matches = list(cache_root.glob("*/dependencies/node/bin/node.exe"))
    return matches[0] if matches else None


def run(*args: str) -> None:
    completed = subprocess.run([sys.executable, *args], cwd=BACKEND_ROOT, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def main() -> int:
    run("-m", "alembic", "upgrade", "head")
    run("-m", "pytest", "-q")
    run(str(BACKEND_ROOT / "scripts" / "run_m5_validation.py"), "--port", "18772")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "18773", "--log-level", "warning"],
        cwd=BACKEND_ROOT,
    )
    try:
        time.sleep(1.5)
        node = find_bundled_node()
        playwright = node.parents[1] / "node_modules" / "playwright" / "index.mjs" if node else None
        if node and playwright and playwright.is_file():
            browser_env = os.environ.copy()
            browser_env["CODEX_PLAYWRIGHT_PATH"] = str(playwright)
            browser_root = Path.home() / "AppData" / "Local" / "ms-playwright"
            browser_candidates = list(browser_root.glob("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"))
            if browser_candidates:
                browser_env["CODEX_CHROMIUM_PATH"] = str(browser_candidates[0])
            completed = subprocess.run(
                [str(node), str(BACKEND_ROOT / "scripts" / "m6_browser_check.mjs"), "http://127.0.0.1:18773"],
                cwd=BACKEND_ROOT,
                env=browser_env,
                check=False,
            )
            if completed.returncode:
                raise SystemExit(completed.returncode)
        else:
            print("Browser check skipped: bundled Node.js is unavailable")
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
    print("M6 validation passed: frontend API mode, contracts, security, M1-M5 E2E, deployment scripts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
