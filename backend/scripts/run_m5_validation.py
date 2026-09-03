from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18768)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    base_url = f"http://127.0.0.1:{args.port}"
    server_env = os.environ.copy()
    server_env["LOG_LEVEL"] = "WARNING"
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
            "--log-level",
            "warning",
        ],
        cwd=BACKEND_ROOT,
        env=server_env,
    )
    try:
        for _ in range(80):
            if server.poll() is not None:
                raise RuntimeError(f"validation server exited with {server.returncode}")
            try:
                if httpx.get(f"{base_url}/api/v1/health/live", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError("validation server did not become ready")
        smoke_args = [
            sys.executable,
            str(BACKEND_ROOT / "scripts" / "m5_smoke_test.py"),
            "--base-url",
            base_url,
        ]
        if args.output_dir:
            smoke_args.extend(["--output-dir", str(args.output_dir)])
        return subprocess.call(smoke_args, cwd=BACKEND_ROOT)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
