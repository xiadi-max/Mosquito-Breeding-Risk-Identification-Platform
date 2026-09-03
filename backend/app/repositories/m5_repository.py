from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload
from app.domain.models import DecisionVersion, Export, RiskRun


class M5Repository:
    def __init__(self, session: Session): self.session = session
    def current_risk(self, task_id):
        return self.session.execute(select(RiskRun).options(selectinload(RiskRun.hotspots)).where(RiskRun.task_id==task_id, RiskRun.status=="current")).scalar_one_or_none()
    def risk(self, task_id, risk_id):
        return self.session.execute(select(RiskRun).options(selectinload(RiskRun.hotspots), joinedload(RiskRun.inference_run)).where(RiskRun.task_id==task_id, RiskRun.id==risk_id)).unique().scalar_one_or_none()
    def current_decision(self, task_id):
        return self.session.execute(select(DecisionVersion).where(DecisionVersion.task_id==task_id, DecisionVersion.status=="current")).scalar_one_or_none()
    def decision(self, task_id, decision_id):
        return self.session.execute(select(DecisionVersion).where(DecisionVersion.task_id==task_id, DecisionVersion.id==decision_id)).scalar_one_or_none()
    def decisions(self, task_id):
        return list(self.session.execute(select(DecisionVersion).where(DecisionVersion.task_id==task_id).order_by(DecisionVersion.version.desc())).scalars())
    def exports(self, task_id):
        return list(self.session.execute(select(Export).where(Export.task_id==task_id).order_by(Export.created_at.desc())).scalars())
