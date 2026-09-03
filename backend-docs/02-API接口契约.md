# API 接口契约

## 1. 通用规则

- 基础前缀：`/api/v1`。
- JSON：UTF-8，字段使用 `snake_case`。
- 时间：UTC ISO 8601，例如 `2026-08-10T08:30:00Z`。
- 主键：对外使用 UUID 字符串；任务同时有可读 `code`。
- 每个响应返回 `X-Request-ID`；客户端可传同名头用于串联日志。
- 所有 POST 作业接口接受 `Idempotency-Key`。同键同请求返回相同资源；同键不同请求返回 `409 IDEMPOTENCY_KEY_REUSED`。
- 修改带版本实体时传 `If-Match: "<version>"`，或在 JSON 中传 `expected_version`；冲突返回 409。
- 列表统一为 `{items, next_cursor}`；默认 `limit=20`，最大 100。
- 二进制资源通过 artifact API 下载，不向前端暴露服务器绝对路径。

## 2. 通用错误

Content-Type：`application/problem+json`

```json
{
  "type": "https://mosquito-mapper.local/problems/version-conflict",
  "title": "资源版本冲突",
  "status": 409,
  "detail": "ROI 已被其他请求更新，请刷新后重试。",
  "instance": "/api/v1/tasks/8c.../rois",
  "code": "VERSION_CONFLICT",
  "request_id": "req_01J...",
  "errors": [
    {"field": "expected_version", "message": "expected 2, current 3"}
  ]
}
```

至少实现：

| 状态 | code | 场景 |
|---|---|---|
| 400 | `INVALID_WORKFLOW_STATE` | 尚无拼接图却保存 ROI |
| 400 | `INVALID_POLYGON` | ROI 顶点不足、越界或自交 |
| 404 | `TASK_NOT_FOUND` | 任务不存在 |
| 404 | `ARTIFACT_NOT_FOUND` | 产物不存在或不属于该任务 |
| 409 | `VERSION_CONFLICT` | 乐观锁冲突 |
| 409 | `JOB_ALREADY_RUNNING` | 同类型互斥作业正在执行 |
| 413 | `UPLOAD_LIMIT_EXCEEDED` | 文件数/单文件/任务总量超限 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` | magic bytes 或解码不符合图片类型 |
| 422 | `VALIDATION_ERROR` | schema 校验错误 |
| 503 | `MODEL_NOT_CONFIGURED` | 生产推理 provider 未就绪 |
| 503 | `MOSAIC_ENGINE_NOT_CONFIGURED` | 真实拼接 provider 未就绪 |

## 3. 健康与版本

### `GET /api/v1/health/live`

仅表示 API 进程可响应。

```json
{"status":"ok"}
```

### `GET /api/v1/health/ready`

```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "storage": "ok",
    "mosaic_provider": {
      "name": "opencv",
      "configured": true,
      "strategy": "opencv_scans_affine"
    },
    "detector_provider": {
      "name": "fake",
      "configured": true,
      "runtime_version": null
    },
    "worker_last_seen_at": "2026-08-10T08:30:00Z"
  }
}
```

### `GET /api/v1/version`

返回应用版本、schema revision、commit（若可得）和 provider 概要，不返回密钥或完整路径。

## 4. 原型兼容 Dashboard

### `GET /api/mosquito-workbench/dashboard?task_id={uuid}`

用途：让 `data.js` 把 `dataMode` 从 `test` 改为 `api` 后，`index.html` 可先加载真实动态数据。

- 未传 `task_id`：选择最近更新的 running 任务，否则选择最近任务；空库返回空集合。
- 传入 `task_id`：返回该任务的当前有效 ROI、复核、风险结果。
- 必须保留前端当前读取的顶层字段：`tasks`、`demoImages`、`rois`、`model`、`risk`。
- 建议额外返回 `meta.current_task_id`、`meta.api_version`、`meta.capabilities`。

示例：

```json
{
  "meta": {
    "api_version": "v1",
    "current_task_id": "8ca054ea-4b4a-4efc-950a-1eaab3e9d1ca",
    "capabilities": {"mosaic":"fake","detector":"fake","decision":"rules"}
  },
  "tasks": [
    {
      "uuid": "8ca054ea-4b4a-4efc-950a-1eaab3e9d1ca",
      "name": "棠下村航拍巡查",
      "id": "T-20260716-A1B2",
      "type": "重点区域排查",
      "status": "处理中",
      "state": "running",
      "progress": 14,
      "date": "2026-07-16",
      "summary": "12 张影像",
      "selected": true
    }
  ],
  "demoImages": [],
  "rois": [
    {"id":"ROI-01","visible":true,"points":[[82,86],[383,55],[649,82]]}
  ],
  "model": {
    "completedTargetCount": 36,
    "reviews": [
      {"id":"C-018","detection_id":"...","category":"其他容器","confidence":0.42,"grid":"G08"}
    ]
  },
  "risk": {
    "highThreshold": 75,
    "mediumThreshold": 40,
    "hotspots": []
  }
}
```

注意：这里的 `points`、`contour`、`label`、`blob` 是旧 UI 适配字段。canonical API 使用 native pixel/GeoJSON；兼容层负责换算到当前 SVG viewBox。

## 5. Tasks

### `GET /api/v1/tasks`

查询参数：`q`、`state=running|done|archived`、`limit`、`cursor`。

```json
{
  "items": [{
    "id": "8ca054ea-4b4a-4efc-950a-1eaab3e9d1ca",
    "code": "T-20260810-A1B2",
    "name": "棠下村 8 月雨后复查",
    "area": "棠下村东南片区",
    "survey_date": "2026-08-10",
    "task_type": "雨后复查",
    "state": "running",
    "progress": 14,
    "current_stage": "image_ingest",
    "blocked_by": null,
    "image_count": 12,
    "version": 3,
    "created_at": "2026-08-10T08:00:00Z",
    "updated_at": "2026-08-10T08:20:00Z"
  }],
  "next_cursor": null
}
```

### `POST /api/v1/tasks`

```json
{
  "name": "棠下村 8 月雨后复查",
  "area": "棠下村东南片区",
  "survey_date": "2026-08-10",
  "task_type": "雨后复查"
}
```

返回 `201 Created`、任务对象和 `Location: /api/v1/tasks/{id}`。

### `GET /api/v1/tasks/{task_id}`

返回任务、派生进度、当前产物摘要和 `links`。

### `PATCH /api/v1/tasks/{task_id}`

可修改 `name`、`area`、`survey_date`、`task_type`。需 `If-Match`。

### `POST /api/v1/tasks/{task_id}/archive`

归档不删除文件；存在 running job 时返回 409，除非先取消。

### `DELETE /api/v1/tasks/{task_id}`

返回 202 deletion job 更稳妥；小型 MVP 也可同步返回 204，但必须先把状态置 `deleting`，防止部分删除后仍可操作。

## 6. Images 与上传

### `GET /api/v1/tasks/{task_id}/images`

返回影像元数据，不返回服务器路径。

### `POST /api/v1/tasks/{task_id}/images`

`multipart/form-data`，字段 `files` 可重复。仅接受 JPG、JPEG、PNG；TIFF 和其他格式按文件返回 `UNSUPPORTED_MEDIA_TYPE`。MVP 限制由配置返回在 `/version` 或 `meta.capabilities`。

响应 `201`：

```json
{
  "accepted": [{
    "id": "img_uuid",
    "display_name": "DJI_20260810_0801.JPG",
    "size_bytes": 7100000,
    "mime_type": "image/jpeg",
    "sha256": "...",
    "width": 4000,
    "height": 3000,
    "captured_at": "2026-08-10T00:01:10Z",
    "gps": {"latitude":23.1,"longitude":113.3,"altitude_m":80.2},
    "warnings": []
  }],
  "duplicates": [],
  "rejected": [],
  "summary": {
    "image_count": 12,
    "total_size_bytes": 91234567,
    "gps_count": 11,
    "capture_span_seconds": 660
  }
}
```

批量上传应定义原子策略。推荐“逐文件持久化 + 每文件结果”，这样一张坏图不丢掉其余已成功图片；若前端需要全有或全无，另增加 upload session，不要假装 multipart 自带事务。

### `DELETE /api/v1/tasks/{task_id}/images/{image_id}`

若已有 mosaic，删除影像会使 mosaic 及全部下游 stale；响应可带 `invalidated_resources`。

## 7. Artifacts

### `GET /api/v1/artifacts/{artifact_id}/content`

- 返回固定服务器生成的 `Content-Type`、安全 `Content-Disposition`、`ETag`、`Content-Length`；
- 支持 `If-None-Match` 与单 Range；
- 图片预览可用 query `variant=preview`，实际映射到已登记的 preview artifact；
- 不接受任意 `path` 参数。

## 8. Jobs 与 SSE

### `POST /api/v1/tasks/{task_id}/mosaic-jobs`

`provider` 允许 `auto | opencv | fake`；生产环境使用 `auto/opencv`。OpenCV 至少需要 2 张已校验的 JPG/JPEG/PNG。

```json
{
  "provider": "auto",
  "options": {}
}
```

SCANS 参数由服务端环境变量控制，客户端不能传任意 OpenCV 参数。实际步骤为 `preflight → load_images → feature_registration → seam_blending → render → quality_check`。

响应 `202 Accepted`：

```json
{
  "job": {
    "id": "job_uuid",
    "type": "mosaic",
    "status": "queued",
    "progress": 0,
    "current_step": "queued",
    "attempt_count": 0,
    "created_at": "2026-08-10T08:30:00Z"
  },
  "links": {
    "self": "/api/v1/jobs/job_uuid",
    "events": "/api/v1/jobs/job_uuid/events",
    "cancel": "/api/v1/jobs/job_uuid/cancel"
  }
}
```

### `GET /api/v1/jobs/{job_id}`

返回进度、步骤、错误、result links。终态不会随读取而改变。

OpenCV 成功结果包含：

```json
{
  "mosaic_artifact_id": "artifact_uuid",
  "preview_artifact_id": "preview_uuid",
  "quality_artifact_id": "quality_uuid",
  "width": 4839,
  "height": 2722,
  "provider": "opencv",
  "quality": {
    "strategy": "opencv_scans_affine",
    "source_image_count": 6,
    "work_scale": 0.6,
    "pano_confidence_threshold": 0.3,
    "black_border_cropped": true,
    "output_format": "jpeg",
    "measurement_grade": false,
    "georeferenced": false
  }
}
```

### `POST /api/v1/jobs/{job_id}/cancel`

设置 `cancel_requested_at`。Worker 在安全点确认后置 canceled；已终态返回当前资源而非重复报错。

### `GET /api/v1/jobs/{job_id}/events`

请求头可含 `Last-Event-ID: 23`。Content-Type `text/event-stream`。

```text
id: 24
event: job.progress
data: {"job_id":"job_uuid","progress":48,"step":"blend","message":"正在融合重叠区域"}

id: 25
event: job.succeeded
data: {"job_id":"job_uuid","progress":100,"result":{"mosaic_artifact_id":"artifact_uuid"}}

```

## 9. ROI

### `GET /api/v1/tasks/{task_id}/rois`

```json
{
  "version": 2,
  "coordinate_space": "mosaic_pixel",
  "source": {"artifact_id":"mosaic_uuid","width":4096,"height":3072},
  "items": [{
    "id": "roi_uuid",
    "code": "ROI-01",
    "visible": true,
    "polygon": [[373.19,484.69],[1743.08,309.94],[2953.46,461.42]],
    "area_px2": 1234567.8,
    "area_m2": null
  }]
}
```

### `PUT /api/v1/tasks/{task_id}/rois`

覆盖当前 ROI 集合并生成新版本：

```json
{
  "expected_version": 2,
  "source_artifact_id": "mosaic_uuid",
  "coordinate_space": "mosaic_pixel",
  "items": [{"id":null,"code":"ROI-01","visible":true,"polygon":[[373.19,484.69],[1743.08,309.94],[2953.46,461.42]]}]
}
```

响应列出 `invalidated`: `grid_plan`, `inference_run`, `risk_run`, `decision`, `exports`。

## 10. Grid

### `POST /api/v1/tasks/{task_id}/grid-plans/preview`

纯计算/短请求，只返回矩形和统计，不裁出所有文件：

```json
{
  "roi_version": 3,
  "tile_size": 640,
  "overlap": 0.2,
  "edge_strategy": "pad",
  "min_roi_intersection": 0.1
}
```

```json
{
  "tile_size": 640,
  "step_px": 512,
  "count": 42,
  "padded_count": 11,
  "estimated_bytes": 98654720,
  "tiles": [
    {"code":"G001","source_box":[0,0,640,640],"padding":[0,0,0,0],"roi_intersection":0.83}
  ],
  "fingerprint": "sha256..."
}
```

### `PUT /api/v1/tasks/{task_id}/grid-plan`

持久化 plan 并创建 `grid_generate` job；返回 202。若实现为推理过程中按需切片，也要保存完全相同的 grid metadata，确保可追溯。

## 11. Inference 与 Review

### `POST /api/v1/tasks/{task_id}/inference-jobs`

```json
{
  "grid_plan_id": "grid_plan_uuid",
  "model_version_id": "model_uuid",
  "infer_min_confidence": 0.2,
  "review_threshold": 0.5,
  "auto_accept_threshold": 0.8,
  "nms_iou": 0.45
}
```

返回 202 job。

### `GET /api/v1/tasks/{task_id}/detections`

查询：`run_id`、`status`、`category`、`min_confidence`、`cursor`。

```json
{
  "items": [{
    "id":"detection_uuid",
    "code":"C-018",
    "category":{"id":4,"name":"其他容器"},
    "confidence":0.42,
    "mosaic_box":{"x1":1024.2,"y1":862.4,"x2":1090.0,"y2":940.2},
    "center":{"x":1057.1,"y":901.3},
    "source_grid":"G008",
    "review_state":"pending",
    "effective_state":"pending"
  }],
  "next_cursor":null
}
```

### `GET /api/v1/tasks/{task_id}/reviews?status=pending`

除 detection 信息外，返回受控 crop artifact 供人工查看。

### `PATCH /api/v1/tasks/{task_id}/reviews/{detection_id}`

```json
{
  "action": "accept",
  "comment": "现场特征符合水桶",
  "expected_version": 1
}
```

`action` 为 `accept|reject|reset`。操作追加到 `review_actions`，不覆盖原预测；响应包含新的有效统计和哪些风险/报告已 stale。

## 12. Risk 与结果

### `POST /api/v1/tasks/{task_id}/risk-runs`

可同步完成小数据，也建议统一返回 202 job：

```json
{
  "inference_run_id":"run_uuid",
  "review_snapshot_version":7,
  "method":"kde",
  "bandwidth_px":180,
  "resolution_px":32,
  "medium_threshold":40,
  "high_threshold":75
}
```

### `GET /api/v1/tasks/{task_id}/results`

```json
{
  "task_id":"task_uuid",
  "run_id":"risk_uuid",
  "status":"current",
  "summary": {
    "accepted_target_count":36,
    "pending_review_count":0,
    "hotspot_count":3,
    "roi_area":{"value":7860,"unit":"m2","estimated":false}
  },
  "categories":[{"name":"水桶","count":14}],
  "metric":{
    "code":"relative_kde_clustering_index",
    "name":"目标聚集指数",
    "unit":"分",
    "minimum":0,
    "maximum":100,
    "normalization":"current_run_peak",
    "comparable_across_runs":false,
    "epidemiological_risk_index":false
  },
  "thresholds":{"medium":40,"high":75},
  "hotspots":[{
    "id":"hotspot_uuid",
    "code":"H01",
    "name":"东南片区",
    "clustering_index":88,
    "clustering_level":"high",
    "target_count":16,
    "dominant_category":"水桶",
    "geometry":{"type":"Polygon","coordinates":[[[565,310],[610,250],[830,330],[565,310]]]},
    "centroid":{"x":702,"y":390}
  }],
  "artifacts":{"density_preview_id":"artifact_uuid"}
}
```

canonical `geometry` 坐标为 mosaic pixel；若返回地理坐标必须明确 CRS（GeoJSON 通常为 WGS84）。`clustering_index` 是当前 risk run 内以 KDE 峰值归一化的相对聚集强度，只用于和同一响应中的 `thresholds` 比较；不得解释为疾病概率或布雷图指数，也不得跨 run 直接比较。

`H01` 是本次 risk run 中按 `clustering_index` 从高到低编号的第 1 处重点检查区域；同分时按 `centroid.y`、`centroid.x` 排序。它不是单个检测框的编号。`geometry` 在当前基础算法中是达到 medium 分界且四邻域相连范围的近似外包边界，UI/PDF 可用白色虚线显示，但必须说明其不是建筑、地块或行政边界，且编号可能随重新分析变化。

## 13. Decision

### `POST /api/v1/tasks/{task_id}/decisions`

```json
{
  "risk_run_id":"risk_uuid",
  "context":"近期连续降雨；周边人口密集",
  "provider":"rules"
}
```

返回 202 job 或对规则 provider 返回 201。为了前端一致，建议都走 job。

生成结果：

```json
{
  "id":"decision_version_uuid",
  "version":1,
  "source":"generated",
  "title":"棠下村航拍巡查 · 风险处置建议",
  "priorities":[{
    "level":"P1",
    "hotspot_code":"H01",
    "heading":"立即核查 H01 东南片区",
    "body":"...",
    "evidence_refs":["hotspot:H01","threshold:high"]
  }],
  "disclaimer":"AI 建议为辅助信息，最终处置决定由疾控专业人员确认。",
  "provider":{"name":"rules","model":null},
  "created_at":"2026-08-10T09:00:00Z"
}
```

### `GET /api/v1/tasks/{task_id}/decisions`

返回版本历史。

### `PATCH /api/v1/tasks/{task_id}/decisions/{version_id}`

保存人工编辑为新版本，字段使用结构化 `title/priorities/disclaimer`；不要直接信任并持久化未清洗 HTML。若为了兼容 `contenteditable` 接收 HTML，必须严格 allowlist 清洗，并同时保存 canonical 结构。

## 14. Exports

### `POST /api/v1/tasks/{task_id}/exports`

```json
{
  "format":"pdf",
  "risk_run_id":"risk_uuid",
  "decision_version_id":"decision_uuid",
  "include_detection_details":true
}
```

`format`：`csv|xlsx|pdf`。返回 202 job。

### `GET /api/v1/tasks/{task_id}/exports`

返回导出历史、状态、生成时间、输入版本、`stale` 标志和 download artifact link。

## 15. 与当前 `index.html` 的动作映射

| 当前函数/按钮 | 真实接口 | UI 行为 |
|---|---|---|
| `loadDynamicData` | dashboard | 首屏加载；无任务显示空态 |
| `createTask` | POST tasks | 保存真实 UUID，不再用日期拼 ID |
| `selectTask` | GET dashboard?task_id | 切换完整任务上下文 |
| `loadFiles` | POST images | 显示 accepted/rejected/warnings |
| `resetUpload` | DELETE images（逐个或批量端点） | 明确提示会使下游 stale |
| `startStitch` | POST mosaic-jobs + SSE | 真实进度替换 `setInterval` |
| ROI 保存 | PUT rois | SVG → native pixel 后发送 |
| `renderGrid` | POST grid-plans/preview | 使用后端返回的 tile 矩形 |
| `runModel` | POST inference-jobs + SSE | 真实阶段与错误 |
| `resolveReview` | PATCH review | 并发冲突刷新候选 |
| `updateRisks` | POST risk-runs | 阈值变化创建新 run，不就地改标签 |
| `generateAi` | POST decisions | 版本化结果，不用 `setTimeout` |
| 导出按钮 | POST exports + artifact | 作业完成后触发下载 |
