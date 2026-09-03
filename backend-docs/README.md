# MosquitoMapper v2.2 后端开发资料包

本资料包依据以下现有材料整理：

- `../index.html`：当前唯一可信的前端交互基线；
- `../data.js`：静态配置和兼容接口地址；
- `../test_data.js`：当前前端期望的动态数据示例；
- 项目早期 MVP PRD：FastAPI、SQLite、本地存储、纯 HTML、低成本部署等范围约束。

目标不是另写一份泛化方案，而是让后端能逐项替换 `index.html` 中的模拟逻辑，最终跑通“任务 → 上传 → 拼接 → ROI → 网格 → 推理/复核 → 热点 → AI 建议 → 报告”的真实闭环。

## 文档导航

1. [00-完整后端开发提示词.md](./00-完整后端开发提示词.md)：可整段复制给 Codex/编码 Agent 执行的主提示词。
2. [01-系统架构与任务状态机.md](./01-系统架构与任务状态机.md)：技术选型、组件图、流程图、状态机、故障恢复与扩展边界。
3. [02-API接口契约.md](./02-API接口契约.md)：REST/SSE 接口、请求响应、错误格式、前端动作映射。
4. [03-数据模型与文件存储.md](./03-数据模型与文件存储.md)：SQLite 表、坐标规范、文件目录、幂等与数据一致性。
5. [04-部署测试与验收.md](./04-部署测试与验收.md)：本地/容器运行、测试矩阵、性能基线、安全清单和最终验收。
6. [05-前后端联调清单.md](./05-前后端联调清单.md)：将 `dataMode: 'test'` 切到真实 API 的最短联调路径。

## 已锁定的架构决策

| 主题 | MVP 决策 | 升级触发点 |
|---|---|---|
| 应用形态 | 模块化单体，API 与计算 Worker 分进程 | 多团队独立发布时再拆服务 |
| API | FastAPI，统一 `/api/v1`；保留原型兼容端点 | 无 |
| 数据库 | SQLite + WAL + Alembic | 多实例、多写入节点或明显锁竞争时迁 PostgreSQL |
| 异步任务 | SQLite 作业表 + 租约式 Worker，不依赖 Redis | 多机 Worker/GPU 池时迁 Redis/RabbitMQ 队列 |
| 文件 | 本地文件系统，数据库仅存相对路径与元数据 | 多实例或正式容灾时迁 S3/MinIO |
| 进度 | 持久化 `job_events` + SSE，可用 `Last-Event-ID` 续传 | 需要双向控制再考虑 WebSocket |
| 拼接 | 测试 Fake；正式使用 OpenCV SCANS 仿射模型，JPEG 像素级输出 | 场景不再近似共面或出现测绘精度刚需时重新立项 |
| 推理 | YOLOv13 适配器；模型版本、哈希、类别表均留痕 | GPU/ONNX/TensorRT 通过同一接口替换 |
| AI 决策 | 先结构化规则/模板，可选 LLM；人工编辑和版本留痕 | 疾控审核通过后开放外部模型提供商 |
| 身份权限 | 单操作员 MVP，不做多租户/SSO | 正式政务环境上线前接 OIDC/RBAC |

## 关键边界

- SVG 的 `900 × 545`、`900 × 520` 是展示坐标，不是后端真实影像坐标。
- 网格是模型计算单元，不是管理统计单元；统计按任务、ROI、热点和类别输出。
- 拼接、推理、风险分析、报告均为可重试的异步作业；HTTP 请求不得长时间阻塞。
- 生产模式不得用演示结果伪装成功。模型或拼接引擎未配置时，返回明确的可诊断错误。
- 原图、权重、报告路径不得直接由客户端指定；所有文件访问必须经过受控 artifact API。

## 外部技术依据

- YOLOv13 官方仓库使用 Python 3.11 示例、`ultralytics.YOLO` 接口，支持导出 ONNX/TensorRT，并标明 AGPL-3.0 许可：[iMoonLab/yolov13](https://github.com/iMoonLab/yolov13)。
- 最新拼接策略、参数、输入限制和质量语义见 [07-OpenCV-SCANS拼接方案.md](./07-OpenCV-SCANS拼接方案.md)。
- FastAPI 官方原生 SSE 支持 `EventSourceResponse`、事件 ID、心跳和断线续传语义：[FastAPI SSE](https://fastapi.tiangolo.com/tutorial/server-sent-events/)。
- SQLite WAL 允许读写并发但仍只有一个 writer，且数据库、WAL 与 shared-memory 文件必须位于同一主机文件系统：[SQLite WAL](https://www.sqlite.org/wal.html)。

> 许可提醒：YOLOv13 官方仓库目前标示 AGPL-3.0。用于政务交付、闭源部署或对外提供网络服务前，应由项目方完成许可证兼容性审查；本文不构成法律意见。
