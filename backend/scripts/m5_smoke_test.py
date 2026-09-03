from __future__ import annotations
import argparse, io, zipfile
from datetime import UTC, datetime
from pathlib import Path
from pypdf import PdfReader
import httpx
from m3_smoke_test import check, completed_job, image_bytes, run_one_worker

HEAD="20260813_0006"

def main():
    p=argparse.ArgumentParser();p.add_argument("--base-url",default="http://127.0.0.1:8000");p.add_argument("--output-dir",type=Path);args=p.parse_args();task_id=None
    with httpx.Client(base_url=args.base_url,timeout=60) as c:
        if check(c.get("/api/v1/version"),200)["schema_revision"]!=HEAD:raise RuntimeError("database is not at M5 head")
        stamp=datetime.now(UTC).strftime("%H%M%S%f")
        task=check(c.post("/api/v1/tasks",json={"name":f"M5 smoke {stamp}","area":"M5 validation area","survey_date":datetime.now(UTC).date().isoformat(),"task_type":"例行巡查"}),201);task_id=task["id"]
        try:
            check(c.post(f"/api/v1/tasks/{task_id}/images",files=[("files",("source.png",image_bytes(),"image/png"))]),201)
            q=check(c.post(f"/api/v1/tasks/{task_id}/mosaic-jobs",json={"provider":"fake"}),202);run_one_worker();m=completed_job(c,q["job"]["id"],"mosaic")["result"]
            roi=check(c.put(f"/api/v1/tasks/{task_id}/rois",json={"expected_version":0,"source_artifact_id":m["mosaic_artifact_id"],"items":[{"code":"ROI-01","polygon":[[0,0],[m["width"],0],[m["width"],m["height"]],[0,m["height"]]]}]}),200)
            preview=check(c.post(f"/api/v1/tasks/{task_id}/grid-plans/preview",json={"roi_version":roi["version"]}),200)
            q=check(c.put(f"/api/v1/tasks/{task_id}/grid-plan",json={"roi_version":roi["version"],"fingerprint":preview["fingerprint"]}),202);run_one_worker();completed_job(c,q["job"]["id"],"grid")
            plan=check(c.get(f"/api/v1/tasks/{task_id}/grid-plan"),200)
            q=check(c.post(f"/api/v1/tasks/{task_id}/inference-jobs",json={"grid_plan_id":plan["id"],"provider":"fake"}),202);run_one_worker();completed_job(c,q["job"]["id"],"inference")
            reviews=check(c.get(f"/api/v1/tasks/{task_id}/reviews",params={"status":"pending"}),200)
            for item in reviews["items"]:check(c.patch(f"/api/v1/tasks/{task_id}/reviews/{item['id']}",json={"action":"accept","expected_version":item["version"]}),200)
            det=check(c.get(f"/api/v1/tasks/{task_id}/detections"),200)
            q=check(c.post(f"/api/v1/tasks/{task_id}/risk-runs",json={"inference_run_id":det["run_id"],"review_snapshot_version":det["review_snapshot_version"]}),202);run_one_worker();risk=completed_job(c,q["job"]["id"],"risk")["result"]
            q=check(c.post(f"/api/v1/tasks/{task_id}/decisions",json={"risk_run_id":risk["risk_run_id"],"context":"近期连续降雨","provider":"rules"}),202);run_one_worker();decision=completed_job(c,q["job"]["id"],"decision")["result"]
            files={}
            for fmt in ("csv","xlsx","pdf"):
                q=check(c.post(f"/api/v1/tasks/{task_id}/exports",headers={"Idempotency-Key":f"m5-{fmt}-{stamp}"},json={"format":fmt,"risk_run_id":risk["risk_run_id"],"decision_version_id":decision["decision_version_id"],"include_detection_details":True}),202);run_one_worker();job=completed_job(c,q["job"]["id"],fmt);files[fmt]=c.get(job["result"]["download_url"]).content
            if not files["csv"].startswith(b"\xef\xbb\xbf"):raise RuntimeError("CSV has no UTF-8 BOM")
            with zipfile.ZipFile(io.BytesIO(files["xlsx"])) as z:
                if "xl/workbook.xml" not in z.namelist():raise RuntimeError("XLSX is invalid")
            if len(PdfReader(io.BytesIO(files["pdf"])).pages)<1:raise RuntimeError("PDF is invalid")
            if args.output_dir:
                args.output_dir.mkdir(parents=True,exist_ok=True)
                for fmt,content in files.items():(args.output_dir/f"m5-validation.{fmt}").write_bytes(content)
            task_after=check(c.get(f"/api/v1/tasks/{task_id}"),200)
            if task_after["progress"]!=100:raise RuntimeError(f"task progress is not 100: {task_after}")
            exports=check(c.get(f"/api/v1/tasks/{task_id}/exports"),200)
            if len(exports["items"])!=3:raise RuntimeError("export history is incomplete")
        finally:
            if task_id:
                response=c.delete(f"/api/v1/tasks/{task_id}")
                if response.status_code not in {204,404}:raise RuntimeError(response.text)
    print("M5 smoke test passed: risk, hotspots, rules decision, CSV/XLSX/PDF, 100% progress, cleanup")
    return 0

if __name__=="__main__":raise SystemExit(main())
