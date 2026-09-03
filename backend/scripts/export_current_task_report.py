from __future__ import annotations

import argparse
from pathlib import Path
import sys
from uuid import uuid4

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings
from app.main import create_app
from app.worker import run_worker


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the current PDF report for one task.")
    parser.add_argument("--task-code", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    settings = Settings()
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/tasks", params={"q": args.task_code, "limit": 100})
        response.raise_for_status()
        task = next((item for item in response.json()["items"] if item["code"] == args.task_code), None)
        if task is None:
            raise SystemExit(f"Task not found: {args.task_code}")

        risk_response = client.get(f"/api/v1/tasks/{task['id']}/results")
        risk_response.raise_for_status()
        risk = risk_response.json()
        if not risk.get("run_id"):
            raise SystemExit(f"Task has no current risk result: {args.task_code}")

        decisions_response = client.get(f"/api/v1/tasks/{task['id']}/decisions")
        decisions_response.raise_for_status()
        decision = next(
            (
                item
                for item in decisions_response.json()["items"]
                if item["status"] == "current" and item["risk_run_id"] == risk["run_id"]
            ),
            None,
        )
        queued = client.post(
            f"/api/v1/tasks/{task['id']}/exports",
            headers={"Idempotency-Key": f"manual-report-{uuid4()}"},
            json={
                "format": "pdf",
                "risk_run_id": risk["run_id"],
                "decision_version_id": decision["id"] if decision else None,
                "include_detection_details": True,
            },
        )
        queued.raise_for_status()
        job_id = queued.json()["job"]["id"]

        for _ in range(20):
            if run_worker(once=True, settings=settings) != 0:
                raise SystemExit("Worker failed while exporting the report")
            job_response = client.get(f"/api/v1/jobs/{job_id}")
            job_response.raise_for_status()
            job = job_response.json()["job"]
            if job["status"] == "succeeded":
                content_response = client.get(job["result"]["download_url"])
                content_response.raise_for_status()
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_bytes(content_response.content)
                print(args.output.resolve())
                return 0
            if job["status"] == "failed":
                raise SystemExit(f"Export failed: {job.get('error')}")
        raise SystemExit("Export job did not finish after 20 worker iterations")


if __name__ == "__main__":
    raise SystemExit(main())
