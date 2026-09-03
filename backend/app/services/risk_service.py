from __future__ import annotations
import json
from collections import Counter
from uuid import uuid4
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload, sessionmaker
from app.core.config import Settings
from app.core.fingerprint import canonical_json
from app.core.security import resolve_storage_path
from app.core.time import ensure_utc, utc_now
from app.domain.enums import ArtifactKind, DerivedStatus, JobStatus
from app.domain.m5_schemas import ClusteringMetricRead, HotspotRead, RiskResults
from app.domain.models import Artifact, Detection, GridPlan, Hotspot, InferenceRun, Job, RiskRun, Task
from app.repositories.m5_repository import M5Repository
from app.services.job_service import JobService
from app.services.mosaic_service import JobCanceled, JobExecutionError, _file_metadata
from app.services.risk_algorithm import RiskPoint, analyze
from app.services.workflow_service import WorkflowService


def describe_mosaic_location(x: float, y: float, width: int, height: int) -> str:
    """Return a plain-language location within the stitched mosaic."""
    horizontal = "西" if x < width / 3 else "东" if x > width * 2 / 3 else "中"
    vertical = "北" if y < height / 3 else "南" if y > height * 2 / 3 else "中"
    if horizontal == "中" and vertical == "中":
        return "拼接图中部"
    if horizontal == "中":
        return f"拼接图{vertical}部"
    if vertical == "中":
        return f"拼接图{horizontal}部"
    return f"拼接图{horizontal}{vertical}部"


class RiskService:
    def __init__(self,session):self.session=session;self.repo=M5Repository(session)
    def results(self,task_id):
        risk=self.repo.current_risk(task_id)
        if risk is None:return RiskResults(task_id=task_id,run_id=None,status=None,summary={"accepted_target_count":0,"pending_review_count":0,"hotspot_count":0,"reason":"RISK_NOT_RUN"},categories=[],metric=ClusteringMetricRead(),thresholds={},hotspots=[],artifacts={"density_preview_id":None})
        stats=json.loads(risk.stats_json)
        mosaic=risk.inference_run.grid_plan.mosaic_artifact
        hotspots=sorted(risk.hotspots,key=lambda h:(-h.clustering_index,h.centroid_y,h.centroid_x))
        return RiskResults(
            task_id=task_id,run_id=risk.id,status=risk.status,created_at=ensure_utc(risk.created_at),
            summary=stats["summary"],categories=stats["categories"],metric=ClusteringMetricRead(),
            thresholds={"medium":risk.medium_threshold,"high":risk.high_threshold},
            hotspots=[HotspotRead(
                id=h.id,code=h.code,
                name=f"{describe_mosaic_location(h.centroid_x,h.centroid_y,mosaic.width,mosaic.height)}重点检查区域",
                clustering_index=h.clustering_index,clustering_level=h.clustering_level,target_count=h.target_count,
                dominant_category=h.dominant_category,
                geometry={"type":"Polygon","coordinates":[json.loads(h.polygon_pixel_json)]},
                centroid={"x":h.centroid_x,"y":h.centroid_y},area_px2=h.area_px2,area_m2=h.area_m2,
            ) for h in hotspots],
            artifacts={
                "mosaic_artifact_id":mosaic.id,
                "density_preview_id":risk.density_artifact_id,
                "density_render_mode":"transparent_overlay" if risk.algorithm_version in {"gaussian-grid-v2","gaussian-grid-v3"} else None,
            },
        )


class RiskJobExecutor:
    def __init__(self,factory:sessionmaker[Session],settings:Settings):self.factory=factory;self.settings=settings
    def execute(self,job_id,worker_id):
        with self.factory() as s:
            job=s.get(Job,job_id); snapshot=json.loads(job.input_json) if job else {}
            if job is None or job.worker_id!=worker_id or job.status!=JobStatus.RUNNING.value:raise JobExecutionError("JOB_OWNERSHIP_LOST","Worker 已失去风险作业租约。")
            run=s.execute(select(InferenceRun).options(joinedload(InferenceRun.grid_plan).joinedload(GridPlan.mosaic_artifact)).where(InferenceRun.id==snapshot["inference_run_id"])).unique().scalar_one_or_none()
            if run is None or run.status!="current" or run.review_snapshot_version!=snapshot["review_snapshot_version"]:raise JobExecutionError("RISK_INPUT_STALE","推理或复核快照已变化。")
            detections=list(s.execute(select(Detection).where(Detection.inference_run_id==run.id,Detection.effective_state=="accepted")).scalars())
            pending=s.execute(select(func.count(Detection.id)).where(Detection.inference_run_id==run.id,Detection.effective_state=="pending")).scalar_one()
            if pending:raise JobExecutionError("PENDING_REVIEWS","仍有待复核结果。")
            width=run.grid_plan.mosaic_artifact.width;height=run.grid_plan.mosaic_artifact.height;task_id=job.task_id
        self._p(job_id,worker_id,15,"load_effective_detections","已读取有效检测结果")
        specs,image,peak=analyze([RiskPoint(d.center_x,d.center_y,d.class_name) for d in detections],width,height,snapshot["bandwidth_px"],snapshot["resolution_px"],snapshot["medium_threshold"],snapshot["high_threshold"])
        specs=sorted(specs,key=lambda h:(-h.clustering_index,h.centroid_y,h.centroid_x))
        self._p(job_id,worker_id,70,"contours","已生成密度图和热点边界")
        directory=resolve_storage_path(self.settings.resolved_storage_root,f"tasks/{task_id}/risk/{job_id}");directory.mkdir(parents=True,exist_ok=True);path=directory/"density.png";image.save(path,"PNG");image.close();sha,size=_file_metadata(path);artifact_id=str(uuid4());risk_id=str(uuid4())
        categories=[{"name":name,"count":count} for name,count in Counter(d.class_name for d in detections).most_common()]
        summary={"accepted_target_count":len(detections),"pending_review_count":0,"hotspot_count":len(specs),"reason":None if detections else "NO_ACCEPTED_DETECTIONS"}
        with self.factory() as s:
            job=s.get(Job,job_id)
            if job is None or job.worker_id!=worker_id:raise JobExecutionError("JOB_OWNERSHIP_LOST","提交风险结果前失去租约。")
            s.execute(update(RiskRun).where(RiskRun.task_id==task_id,RiskRun.status=="current").values(status="stale"));WorkflowService(s).invalidate_from_risk(task_id)
            s.execute(update(Artifact).where(Artifact.task_id==task_id,Artifact.kind==ArtifactKind.DENSITY_PREVIEW.value,Artifact.is_current.is_(True)).values(is_current=False))
            s.add(Artifact(id=artifact_id,task_id=task_id,job_id=job_id,kind=ArtifactKind.DENSITY_PREVIEW.value,relative_path=path.relative_to(self.settings.resolved_storage_root).as_posix(),sha256=sha,size_bytes=size,mime_type="image/png",width=width,height=height,metadata_json=canonical_json({"algorithm":"gaussian-grid-v3","render_mode":"transparent_overlay","peak":peak,"metric":"relative_kde_clustering_index","normalization":"current_run_peak"}),is_current=True,created_at=utc_now()))
            risk=RiskRun(id=risk_id,task_id=task_id,inference_run_id=snapshot["inference_run_id"],job_id=job_id,density_artifact_id=artifact_id,review_snapshot_version=snapshot["review_snapshot_version"],method="kde",bandwidth_px=snapshot["bandwidth_px"],resolution_px=snapshot["resolution_px"],medium_threshold=snapshot["medium_threshold"],high_threshold=snapshot["high_threshold"],accepted_detection_count=len(detections),input_fingerprint=job.input_fingerprint,status="current",stats_json=canonical_json({"summary":summary,"categories":categories}),algorithm_version="gaussian-grid-v3",created_at=utc_now());s.add(risk)
            for i,h in enumerate(specs,1):
                s.add(Hotspot(id=str(uuid4()),risk_run=risk,code=f"H{i:02d}",name=f"{describe_mosaic_location(h.centroid_x,h.centroid_y,width,height)}重点检查区域",clustering_index=h.clustering_index,clustering_level=h.clustering_level,target_count=h.target_count,dominant_category=h.dominant_category,polygon_pixel_json=canonical_json(h.polygon),centroid_x=h.centroid_x,centroid_y=h.centroid_y,area_px2=h.area_px2))
            s.execute(update(Task).where(Task.id==task_id).values(version=Task.version+1,updated_at=utc_now()));s.flush();JobService(s,self.settings).succeed(job_id,worker_id,{"risk_run_id":risk_id,"density_artifact_id":artifact_id,"summary":summary})
        return {"risk_run_id":risk_id,"summary":summary}
    def _p(self,*args):
        with self.factory() as s:JobService(s,self.settings).report_progress(args[0],args[1],progress=args[2],step=args[3],message=args[4])
