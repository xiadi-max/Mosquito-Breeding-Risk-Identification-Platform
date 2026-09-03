from __future__ import annotations
import json
from uuid import uuid4
from sqlalchemy import func, update
from sqlalchemy.orm import Session, sessionmaker
from app.core.config import Settings
from app.core.errors import AppError
from app.core.fingerprint import canonical_json
from app.core.time import ensure_utc, utc_now
from app.domain.enums import JobStatus
from app.domain.m5_schemas import DecisionContent, DecisionEdit, DecisionList, DecisionRead, PriorityItem
from app.domain.models import DecisionVersion, Job, RiskRun, Task
from app.repositories.m5_repository import M5Repository
from app.services.job_service import JobService
from app.services.mosaic_service import JobExecutionError
from app.services.risk_service import describe_mosaic_location
from app.services.workflow_service import WorkflowService

DISCLAIMER="系统建议基于当前任务的真实检测与风险分析生成，仅作辅助；最终处置决定由疾控专业人员确认。"

CATEGORY_LABELS={
    "foam box":"泡沫箱","bucket":"水桶","flower pot":"花盆","tire":"轮胎","tyre":"轮胎",
    "water tank":"储水箱","container":"容器","bottle":"瓶罐",
    "potted_plant":"盆栽","green_plants":"绿色植物",
}


def _display_category(value):
    if not value:return "未分类目标"
    translated=CATEGORY_LABELS.get(value.strip().lower())
    return f"{translated}（识别类别：{value}）" if translated else value


def _clustering_metric(h, risk):
    threshold=(risk.high_threshold if h.clustering_level=="high" else risk.medium_threshold)
    label="高聚集" if h.clustering_level=="high" else "中聚集"
    return f"{h.clustering_index}/100",f"{label}阈值 {threshold}"


def _rule_priorities(risk,context=None):
    mosaic=risk.inference_run.grid_plan.mosaic_artifact
    priorities=[]
    for index,h in enumerate(sorted(risk.hotspots,key=lambda x:(-x.clustering_index,x.centroid_y,x.centroid_x))):
        location=describe_mosaic_location(h.centroid_x,h.centroid_y,mosaic.width,mosaic.height)
        category=_display_category(h.dominant_category)
        clustering_index,threshold=_clustering_metric(h,risk)
        level="P1" if h.clustering_level=="high" else "P2"
        action="优先检查" if level=="P1" else "近期检查" if level=="P2" else "持续观察"
        paragraphs=[
            f"识别结果：这里有 {h.target_count} 个经人工复核后保留并计入统计的{category}。",
            f"区域指标：目标聚集指数 {clustering_index}，达到{threshold}；区域内有 {h.target_count} 个经人工复核后保留的目标。",
            f"判断依据：系统将达到当前聚集指数分界且彼此相连的范围合并为这一处重点检查区域。{h.code} 只是图上定位编号；该指数是本次任务内部的 KDE 相对聚集强度，不是疾病概率、布雷图指数或可跨任务比较的流行病学风险值。",
        ]
        if index==0 and context and context.strip():
            paragraphs.append(f"现场信息：{context.strip()[:240]}。")
        paragraphs.append(f"处置建议：请到结果页 {h.code} 标记的{location}核查是否存在积水或蚊虫孳生环境；地图上的白色虚线仅表示大致范围。如有积水或孳生环境，立即清理并拍照记录，随后安排复查。")
        priorities.append(PriorityItem(
            level=level,hotspot_code=h.code,
            heading=f"{action}{location}（图上编号 {h.code}）",body="\n\n".join(paragraphs),
            evidence_refs=[f"hotspot:{h.code}",f"clustering-threshold:{h.clustering_level}"],
        ))
    if priorities:return priorities
    stats=json.loads(risk.stats_json)
    accepted=stats.get("summary",{}).get("accepted_target_count",0)
    return [PriorityItem(
        level="P3",heading="当前没有达到阈值的重点检查区域",
        body=f"本次有 {accepted} 个经人工复核后保留的目标，但在当前聚集指数分界下没有形成需要单独编号的重点检查区域。请结合现场情况保持常规巡查；这不代表现场风险为零。",
        evidence_refs=["risk:no-hotspot"],
    )]


def decision_read(item):
    content=DecisionContent.model_validate_json(item.content_json)
    if item.provider=="rules" and item.source=="generated" and item.prompt_template_version!="rules-v4":
        content=DecisionContent(title=content.title,priorities=_rule_priorities(item.risk_run,item.context_text),disclaimer=DISCLAIMER)
    return DecisionRead(id=item.id,task_id=item.task_id,risk_run_id=item.risk_run_id,version=item.version,source=item.source,parent_version_id=item.parent_version_id,context=item.context_text,status=item.status,provider={"name":item.provider,"model":item.model},created_at=ensure_utc(item.created_at),**content.model_dump())


class DecisionService:
    def __init__(self,session):self.s=session;self.repo=M5Repository(session)
    def list(self,task_id):return DecisionList(items=[decision_read(i) for i in self.repo.decisions(task_id)])
    def edit(self,task_id,version_id,data:DecisionEdit):
        source=self.repo.decision(task_id,version_id);current=self.repo.current_decision(task_id)
        if source is None:raise AppError(status_code=404,code="DECISION_NOT_FOUND",title="建议版本不存在",detail="未找到指定建议版本。")
        if current is None or current.version!=data.expected_current_version or source.id!=current.id:raise AppError(status_code=409,code="VERSION_CONFLICT",title="建议版本冲突",detail=f"当前建议版本为 {current.version if current else 'none'}。")
        current.status="stale";WorkflowService(self.s).invalidate_from_decision(task_id,current.id)
        new=DecisionVersion(id=str(uuid4()),task_id=task_id,risk_run_id=current.risk_run_id,version=current.version+1,source="edited",parent_version_id=current.id,provider=current.provider,model=current.model,context_text=current.context_text,content_json=canonical_json(data.model_dump(exclude={"expected_current_version"})),evidence_snapshot_json=current.evidence_snapshot_json,prompt_template_version=current.prompt_template_version,status="current",created_at=utc_now());self.s.add(new);self.s.execute(update(Task).where(Task.id==task_id).values(version=Task.version+1,updated_at=utc_now()));self.s.commit();return decision_read(new)


class DecisionJobExecutor:
    def __init__(self,factory:sessionmaker[Session],settings:Settings):self.f=factory;self.settings=settings
    def execute(self,job_id,worker_id):
        with self.f() as s:
            job=s.get(Job,job_id);snap=json.loads(job.input_json) if job else {}
            if job is None or job.worker_id!=worker_id or job.status!=JobStatus.RUNNING.value:raise JobExecutionError("JOB_OWNERSHIP_LOST","Worker 已失去建议作业租约。")
            risk=M5Repository(s).risk(job.task_id,snap["risk_run_id"])
            if risk is None or risk.status!="current" or risk.input_fingerprint!=snap["risk_fingerprint"]:raise JobExecutionError("DECISION_INPUT_STALE","风险结果已变化。")
            hotspots=list(risk.hotspots);task=s.get(Task,job.task_id);stats=json.loads(risk.stats_json)
            priorities=_rule_priorities(risk,snap.get("context"))
        content=DecisionContent(title=f"{task.name} · 风险处置建议",priorities=priorities,disclaimer=DISCLAIMER)
        evidence={"risk_run_id":risk.id,"metric":"relative_kde_clustering_index","summary":stats["summary"],"hotspots":[{"code":h.code,"clustering_index":h.clustering_index,"clustering_level":h.clustering_level,"location":h.name} for h in hotspots]}
        with self.f() as s:
            job=s.get(Job,job_id);risk=M5Repository(s).risk(job.task_id,snap["risk_run_id"])
            if risk is None or risk.status!="current":raise JobExecutionError("DECISION_INPUT_STALE","风险结果已变化。")
            old=M5Repository(s).current_decision(job.task_id)
            if old:old.status="stale"
            WorkflowService(s).invalidate_from_decision(job.task_id)
            version=(s.query(func.max(DecisionVersion.version)).filter(DecisionVersion.task_id==job.task_id).scalar() or 0)+1
            decision=DecisionVersion(id=str(uuid4()),task_id=job.task_id,risk_run_id=risk.id,version=version,source="generated",provider="rules",model=None,context_text=snap.get("context"),content_json=canonical_json(content.model_dump()),evidence_snapshot_json=canonical_json(evidence),prompt_template_version="rules-v4",status="current",created_at=utc_now());s.add(decision);s.execute(update(Task).where(Task.id==job.task_id).values(version=Task.version+1,updated_at=utc_now()));s.flush();result={"decision_version_id":decision.id,"version":version};JobService(s,self.settings).succeed(job_id,worker_id,result);return result
