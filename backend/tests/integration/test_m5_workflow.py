from __future__ import annotations
import io, zipfile
from pypdf import PdfReader
from app.worker import run_worker
from tests.integration.test_inference_reviews import build_grid


def prepare_reviewed_inference(settings,client):
    task_id,grid_id=build_grid(client,settings)
    queued=client.post(f"/api/v1/tasks/{task_id}/inference-jobs",json={"grid_plan_id":grid_id,"provider":"fake"})
    assert queued.status_code==202 and run_worker(once=True,settings=settings)==0
    pending=client.get(f"/api/v1/tasks/{task_id}/reviews",params={"status":"pending"}).json()
    for item in pending["items"]:
        response=client.patch(f"/api/v1/tasks/{task_id}/reviews/{item['id']}",json={"action":"accept","expected_version":item["version"]})
        assert response.status_code==200
    detections=client.get(f"/api/v1/tasks/{task_id}/detections").json()
    return task_id,detections["run_id"],detections["review_snapshot_version"]


def complete_job(client,settings,resource):
    assert run_worker(once=True,settings=settings)==0
    job=client.get(f"/api/v1/jobs/{resource['job']['id']}").json()["job"]
    assert job["status"]=="succeeded",job
    return job


def test_m5_risk_decision_edit_and_all_exports(test_settings,migrated_client):
    task_id,run_id,review_version=prepare_reviewed_inference(test_settings,migrated_client)
    risk_q=migrated_client.post(f"/api/v1/tasks/{task_id}/risk-runs",json={"inference_run_id":run_id,"review_snapshot_version":review_version,"bandwidth_px":180,"resolution_px":32,"medium_threshold":40,"high_threshold":75})
    assert risk_q.status_code==202,risk_q.text
    risk_job=complete_job(migrated_client,test_settings,risk_q.json())
    risk_id=risk_job["result"]["risk_run_id"]
    results=migrated_client.get(f"/api/v1/tasks/{task_id}/results").json()
    assert results["run_id"]==risk_id and results["summary"]["pending_review_count"]==0
    assert results["created_at"]
    assert results["metric"]=={
        "code":"relative_kde_clustering_index",
        "name":"目标聚集指数",
        "unit":"分",
        "minimum":0,
        "maximum":100,
        "normalization":"current_run_peak",
        "comparable_across_runs":False,
        "epidemiological_risk_index":False,
    }
    assert results["thresholds"]=={"medium":40,"high":75}
    assert results["artifacts"]["mosaic_artifact_id"]
    assert results["artifacts"]["density_render_mode"]=="transparent_overlay"
    for hotspot in results["hotspots"]:
        assert hotspot["name"].startswith("拼接图")
        assert hotspot["name"].endswith("重点检查区域")
        assert 0<=hotspot["clustering_index"]<=100
        assert hotspot["clustering_level"] in {"medium","high"}
        assert "score" not in hotspot and "risk_level" not in hotspot
    assert migrated_client.get(f"/api/v1/artifacts/{results['artifacts']['density_preview_id']}/content").content.startswith(b"\x89PNG")
    assert migrated_client.get(f"/api/v1/tasks/{task_id}").json()["progress"]==85

    decision_q=migrated_client.post(f"/api/v1/tasks/{task_id}/decisions",json={"risk_run_id":risk_id,"context":"近期连续降雨","provider":"rules"})
    decision_job=complete_job(migrated_client,test_settings,decision_q.json())
    decision_id=decision_job["result"]["decision_version_id"]
    decision=migrated_client.get(f"/api/v1/tasks/{task_id}/decisions").json()["items"][0]
    assert decision["id"]==decision_id and decision["disclaimer"]
    if results["hotspots"]:
        assert "拼接图" in decision["priorities"][0]["heading"]
        assert "经人工复核后保留" in decision["priorities"][0]["body"]
        assert "区域指标：" in decision["priorities"][0]["body"]
        assert "目标聚集指数" in decision["priorities"][0]["body"]
        assert "布雷图指数" in decision["priorities"][0]["body"]
        assert "\n\n" in decision["priorities"][0]["body"]
        assert "归一化密度指数" not in decision["priorities"][0]["body"]
        assert "模型类别" not in decision["priorities"][0]["body"]
        assert "关联已接受目标" not in decision["priorities"][0]["body"]
    edited=migrated_client.patch(f"/api/v1/tasks/{task_id}/decisions/{decision_id}",json={"expected_current_version":1,"title":decision["title"]+"（复核版）","priorities":decision["priorities"],"disclaimer":decision["disclaimer"]})
    assert edited.status_code==200,edited.text
    edited_id=edited.json()["id"]
    assert edited.json()["version"]==2 and edited.json()["source"]=="edited"
    assert migrated_client.get(f"/api/v1/tasks/{task_id}").json()["progress"]==100

    artifacts={}
    for fmt in ("csv","xlsx","pdf"):
        queued=migrated_client.post(f"/api/v1/tasks/{task_id}/exports",headers={"Idempotency-Key":f"m5-{fmt}"},json={"format":fmt,"risk_run_id":risk_id,"decision_version_id":edited_id,"include_detection_details":True})
        assert queued.status_code==202,queued.text
        job=complete_job(migrated_client,test_settings,queued.json())
        artifact_id=job["result"]["artifact_id"];content=migrated_client.get(f"/api/v1/artifacts/{artifact_id}/content").content;artifacts[fmt]=content
    assert artifacts["csv"].startswith(b"\xef\xbb\xbf") and "检测编号" in artifacts["csv"].decode("utf-8-sig")
    with zipfile.ZipFile(io.BytesIO(artifacts["xlsx"])) as archive:
        assert "xl/workbook.xml" in archive.namelist()
        workbook=archive.read("xl/workbook.xml").decode("utf-8")
        for name in ("任务汇总","类别统计","聚集区域","检测明细","审计参数"):assert name in workbook
    pdf=PdfReader(io.BytesIO(artifacts["pdf"]));assert len(pdf.pages)>=1
    pdf_text="\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "重点检查区域定位图" in pdf_text
    for wording in ("区域编号","边界含义","指标口径","关注依据","现场处置"):assert wording in pdf_text
    for question_heading in ("H01 是什么","虚线框是什么","指数怎么看","为什么关注","怎么处理"):assert question_heading not in pdf_text
    assert "risk_run=" not in pdf_text and "accepted" not in pdf_text
    assert any(
        any(obj.get_object().get("/Subtype")=="/Image" for obj in ((page.get("/Resources") or {}).get("/XObject") or {}).values())
        for page in pdf.pages
    )
    listed=migrated_client.get(f"/api/v1/tasks/{task_id}/exports").json()["items"]
    assert len(listed)==3 and all(item["download_url"] for item in listed)


def test_risk_rejects_pending_reviews(test_settings,migrated_client):
    task_id,grid_id=build_grid(migrated_client,test_settings)
    queued=migrated_client.post(f"/api/v1/tasks/{task_id}/inference-jobs",json={"grid_plan_id":grid_id,"provider":"fake"})
    complete_job(migrated_client,test_settings,queued.json())
    detections=migrated_client.get(f"/api/v1/tasks/{task_id}/detections").json()
    response=migrated_client.post(f"/api/v1/tasks/{task_id}/risk-runs",json={"inference_run_id":detections["run_id"],"review_snapshot_version":detections["review_snapshot_version"]})
    assert response.status_code==409 and response.json()["code"]=="PENDING_REVIEWS"


def test_m5_openapi_paths(migrated_client):
    paths=migrated_client.get("/openapi.json").json()["paths"]
    for path in ("/api/v1/tasks/{task_id}/risk-runs","/api/v1/tasks/{task_id}/results","/api/v1/tasks/{task_id}/decisions","/api/v1/tasks/{task_id}/exports"):assert path in paths
