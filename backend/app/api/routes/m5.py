from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.orm import Session
from app.api.deps import session_from_request
from app.domain.job_schemas import JobResource
from app.domain.m5_schemas import DecisionCreate, DecisionEdit, DecisionList, DecisionRead, ExportCreate, ExportList, RiskResults, RiskRunCreate
from app.services.decision_service import DecisionService
from app.services.export_service import ExportService
from app.services.m5_job_service import M5JobService
from app.services.risk_service import RiskService

router=APIRouter(prefix="/tasks/{task_id}",tags=["risk","decisions","exports"])

def _job(resource_created,response):
    resource,created=resource_created;response.headers["Location"]=resource.links.self
    if not created:response.headers["Idempotency-Replayed"]="true"
    return resource

@router.post("/risk-runs",response_model=JobResource,status_code=status.HTTP_202_ACCEPTED)
def create_risk(task_id:str,data:RiskRunCreate,request:Request,response:Response,session:Session=Depends(session_from_request),key:str|None=Header(default=None,alias="Idempotency-Key")):
    return _job(M5JobService(session,request.app.state.settings).create_risk(task_id,data,key),response)

@router.get("/results",response_model=RiskResults)
def results(task_id:str,session:Session=Depends(session_from_request)):return RiskService(session).results(task_id)

@router.post("/decisions",response_model=JobResource,status_code=status.HTTP_202_ACCEPTED)
def create_decision(task_id:str,data:DecisionCreate,request:Request,response:Response,session:Session=Depends(session_from_request),key:str|None=Header(default=None,alias="Idempotency-Key")):
    return _job(M5JobService(session,request.app.state.settings).create_decision(task_id,data,key),response)

@router.get("/decisions",response_model=DecisionList)
def decisions(task_id:str,session:Session=Depends(session_from_request)):return DecisionService(session).list(task_id)

@router.patch("/decisions/{version_id}",response_model=DecisionRead)
def edit_decision(task_id:str,version_id:str,data:DecisionEdit,session:Session=Depends(session_from_request)):return DecisionService(session).edit(task_id,version_id,data)

@router.post("/exports",response_model=JobResource,status_code=status.HTTP_202_ACCEPTED)
def create_export(task_id:str,data:ExportCreate,request:Request,response:Response,session:Session=Depends(session_from_request),key:str|None=Header(default=None,alias="Idempotency-Key")):
    return _job(M5JobService(session,request.app.state.settings).create_export(task_id,data,key),response)

@router.get("/exports",response_model=ExportList)
def exports(task_id:str,session:Session=Depends(session_from_request)):return ExportService(session).list(task_id)
