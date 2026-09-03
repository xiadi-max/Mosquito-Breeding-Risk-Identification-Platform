from enum import StrEnum


class WorkerStatus(StrEnum):
    STARTING = "starting"
    IDLE = "idle"
    BUSY = "busy"
    STOPPING = "stopping"


class TaskState(StrEnum):
    RUNNING = "running"
    DONE = "done"
    ARCHIVED = "archived"
    DELETING = "deleting"


class TaskType(StrEnum):
    ROUTINE = "例行巡查"
    POST_RAIN = "雨后复查"
    PRIORITY_AREA = "重点区域排查"
    EMERGENCY = "应急核查"


class ArtifactKind(StrEnum):
    ORIGINAL_IMAGE = "original_image"
    MOSAIC = "mosaic"
    MOSAIC_PREVIEW = "mosaic_preview"
    GRID_TILE = "grid_tile"
    REVIEW_CROP = "review_crop"
    DENSITY_PREVIEW = "density_preview"
    PREDICTIONS_JSON = "predictions_json"
    CSV = "csv"
    XLSX = "xlsx"
    PDF = "pdf"
    MOSAIC_QUALITY = "mosaic_quality"


class JobType(StrEnum):
    MOSAIC = "mosaic"
    GRID_GENERATE = "grid_generate"
    INFERENCE = "inference"
    RISK_ANALYSIS = "risk_analysis"
    DECISION_GENERATE = "decision_generate"
    EXPORT_CSV = "export_csv"
    EXPORT_XLSX = "export_xlsx"
    EXPORT_PDF = "export_pdf"
    TASK_DELETE = "task_delete"


class JobStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"

    @property
    def terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.CANCELED}


class DerivedStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"


class DetectionState(StrEnum):
    ACCEPTED = "accepted"
    PENDING = "pending"
    DISCARDED = "discarded"
    REJECTED = "rejected"


class ReviewActionType(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    RESET = "reset"


class ExportStatus(StrEnum):
    QUEUED = "queued"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"
