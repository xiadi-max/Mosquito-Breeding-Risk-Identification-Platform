from __future__ import annotations
import json
from uuid import uuid4
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.errors import AppError
from app.core.fingerprint import canonical_json, fingerprint
from app.core.time import utc_now
from app.domain.enums import ExportStatus, JobStatus, JobType, TaskState
from app.domain.job_schemas import JobResource
from app.domain.m5_schemas import DecisionCreate, ExportCreate, RiskRunCreate
from app.domain.models import Detection, Export, InferenceRun, Job, JobEvent
from app.repositories.job_repository import JobRepository
from app.repositories.m5_repository import M5Repository
from app.services.job_service import job_resource
from app.services.task_service import TaskService


class M5JobService:
    def __init__(self, session: Session, settings):
        self.session=session; self.settings=settings; self.repo=M5Repository(session)

    def create_risk(self, task_id, data: RiskRunCreate, key):
        task=self._running(task_id)
        run=self.session.get(InferenceRun,data.inference_run_id)
        if run is None or run.task_id!=task_id or run.status!="current": self._state("只能分析当前有效推理结果。")
        pending=self.session.execute(select(func.count(Detection.id)).where(Detection.inference_run_id==run.id,Detection.effective_state=="pending")).scalar_one()
        if pending: raise AppError(status_code=409,code="PENDING_REVIEWS",title="仍有待复核结果",detail=f"请先处理 {pending} 条待复核检测。")
        if run.review_snapshot_version!=data.review_snapshot_version: raise AppError(status_code=409,code="VERSION_CONFLICT",title="复核快照已变化",detail=f"当前 review_snapshot_version 为 {run.review_snapshot_version}。")
        snapshot={"operation":"risk_analysis","inference_run_id":run.id,"inference_fingerprint":run.input_fingerprint,"review_snapshot_version":run.review_snapshot_version,**data.model_dump(exclude={"inference_run_id","review_snapshot_version"})}
        return self._queue(task.id,JobType.RISK_ANALYSIS.value,snapshot,key,"风险分析作业已进入队列")

    def create_decision(self, task_id, data: DecisionCreate, key):
        self._running(task_id); risk=self.repo.risk(task_id,data.risk_run_id)
        if risk is None or risk.status!="current": self._state("只能基于当前风险结果生成建议。")
        if data.provider!="rules": raise AppError(status_code=503,code="DECISION_PROVIDER_NOT_CONFIGURED",title="建议 Provider 未配置",detail="M5 默认仅启用离线 rules Provider。")
        snapshot={"operation":"decision_generate","risk_run_id":risk.id,"risk_fingerprint":risk.input_fingerprint,"context":data.context,"provider":data.provider}
        return self._queue(task_id,JobType.DECISION_GENERATE.value,snapshot,key,"建议生成作业已进入队列")

    def create_export(self, task_id, data: ExportCreate, key):
        self._running(task_id); risk=self.repo.risk(task_id,data.risk_run_id)
        if risk is None or risk.status!="current": self._state("只能导出当前风险结果。")
        decision=None
        if data.decision_version_id:
            decision=self.repo.decision(task_id,data.decision_version_id)
            if decision is None or decision.status!="current" or decision.risk_run_id!=risk.id: self._state("建议版本不存在、已失效或与风险结果不匹配。")
        job_type={"csv":JobType.EXPORT_CSV.value,"xlsx":JobType.EXPORT_XLSX.value,"pdf":JobType.EXPORT_PDF.value}[data.format]
        snapshot={"operation":job_type,"format":data.format,"risk_run_id":risk.id,"risk_fingerprint":risk.input_fingerprint,"decision_version_id":decision.id if decision else None,"include_detection_details":data.include_detection_details}
        resource,created=self._queue(task_id,job_type,snapshot,key,f"{data.format.upper()} 导出作业已进入队列")
        if created:
            self.session.add(Export(id=str(uuid4()),task_id=task_id,job_id=resource.job.id,format=data.format,risk_run_id=risk.id,decision_version_id=decision.id if decision else None,input_fingerprint=resource.job.id and fingerprint(snapshot),status=ExportStatus.QUEUED.value,created_at=utc_now()))
            self.session.commit()
        return resource,created

    def _queue(self,task_id,job_type,snapshot,key,message):
        input_hash=fingerprint(snapshot); request_hash=input_hash; effective=(key or f"auto:{input_hash}").strip()
        if not effective or len(effective)>255: raise AppError(status_code=422,code="VALIDATION_ERROR",title="幂等键无效",detail="Idempotency-Key 长度必须为 1–255 个字符。")
        jobs=JobRepository(self.session); existing=jobs.get_idempotent(task_id,job_type,effective)
        if existing:
            if existing.request_hash!=request_hash: raise AppError(status_code=409,code="IDEMPOTENCY_KEY_REUSED",title="幂等键已用于不同请求",detail="请为不同参数使用新的 Idempotency-Key。")
            return job_resource(existing),False
        active=jobs.active_for_type(task_id,job_type)
        if active: raise AppError(status_code=409,code="JOB_ALREADY_RUNNING",title="同类作业正在执行",detail=f"已有未结束作业 {active.id}。")
        now=utc_now(); job=Job(id=str(uuid4()),task_id=task_id,type=job_type,status=JobStatus.QUEUED.value,progress=0,current_step="queued",message=message,input_json=canonical_json(snapshot),input_fingerprint=input_hash,idempotency_key=effective,request_hash=request_hash,available_at=now,attempt_count=0,max_attempts=self.settings.job_max_retries,created_at=now)
        self.session.add(job)
        try:self.session.flush()
        except IntegrityError:
            self.session.rollback(); concurrent=jobs.get_idempotent(task_id,job_type,effective)
            if concurrent is None: raise
            return job_resource(concurrent),False
        self.session.add(JobEvent(job_id=job.id,event_type="job.queued",data_json=canonical_json({"job_id":job.id,"status":job.status,"message":message}),created_at=now)); self.session.commit()
        return job_resource(job),True

    def _running(self,task_id):
        task=TaskService(self.session).get_model(task_id)
        if task.state!=TaskState.RUNNING.value:self._state("只有处理中的任务可以执行此操作。")
        return task
    @staticmethod
    def _state(detail): raise AppError(status_code=400,code="INVALID_WORKFLOW_STATE",title="当前工作流状态不允许此操作",detail=detail)
