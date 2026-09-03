from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import Field, model_validator
from app.domain.schemas import StrictSchema


class RiskRunCreate(StrictSchema):
    inference_run_id: str
    review_snapshot_version: int = Field(ge=0)
    method: Literal["kde"] = "kde"
    bandwidth_px: float = Field(default=180, gt=0, le=5000)
    resolution_px: int = Field(default=32, ge=8, le=512)
    medium_threshold: int = Field(default=40, ge=0, le=99)
    high_threshold: int = Field(default=75, ge=1, le=100)

    @model_validator(mode="after")
    def ordered(self):
        if self.medium_threshold >= self.high_threshold:
            raise ValueError("medium_threshold must be lower than high_threshold")
        return self


class HotspotRead(StrictSchema):
    id: str; code: str; name: str; clustering_index: int; clustering_level: str
    target_count: int; dominant_category: str | None
    geometry: dict; centroid: dict[str, float]; area_px2: float; area_m2: float | None


class ClusteringMetricRead(StrictSchema):
    code: Literal["relative_kde_clustering_index"] = "relative_kde_clustering_index"
    name: str = "目标聚集指数"
    unit: str = "分"
    minimum: int = 0
    maximum: int = 100
    normalization: Literal["current_run_peak"] = "current_run_peak"
    comparable_across_runs: bool = False
    epidemiological_risk_index: bool = False


class RiskResults(StrictSchema):
    task_id: str; run_id: str | None; status: str | None
    created_at: datetime | None = None
    summary: dict; categories: list[dict]; metric: ClusteringMetricRead
    thresholds: dict[str, int]
    hotspots: list[HotspotRead]; artifacts: dict[str, str | None]


class DecisionCreate(StrictSchema):
    risk_run_id: str
    context: str | None = Field(default=None, max_length=4000)
    provider: Literal["rules", "openai_compatible"] = "rules"


class PriorityItem(StrictSchema):
    level: Literal["P1", "P2", "P3"]
    hotspot_code: str | None = None
    heading: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class DecisionContent(StrictSchema):
    title: str = Field(min_length=1, max_length=200)
    priorities: list[PriorityItem] = Field(max_length=50)
    disclaimer: str = Field(min_length=1, max_length=500)


class DecisionEdit(DecisionContent):
    expected_current_version: int = Field(ge=1)


class DecisionRead(DecisionContent):
    id: str; task_id: str; risk_run_id: str; version: int; source: str
    parent_version_id: str | None; context: str | None; status: str
    provider: dict; created_at: datetime


class DecisionList(StrictSchema):
    items: list[DecisionRead]


class ExportCreate(StrictSchema):
    format: Literal["csv", "xlsx", "pdf"]
    risk_run_id: str
    decision_version_id: str | None = None
    include_detection_details: bool = True


class ExportRead(StrictSchema):
    id: str; task_id: str; format: str; risk_run_id: str
    decision_version_id: str | None; artifact_id: str | None; status: str
    stale: bool; created_at: datetime; completed_at: datetime | None
    download_url: str | None


class ExportList(StrictSchema):
    items: list[ExportRead]
