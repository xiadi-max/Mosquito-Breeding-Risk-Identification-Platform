# MosquitoMapper v2.2 Backend

当前实现阶段：M6 + 最新拼接策略，版本 `0.8.0`。M0-M6 全流程已经完成；生产拼接使用 OpenCV `Stitcher_SCANS` 仿射模型，执行特征匹配、几何配准、曝光/接缝融合和黑边裁切。FastAPI 在 `/` 同源托管 v2.2 工作台，页面默认使用真实 API；开发环境可用 `?demo=1` 显式进入演示模式。

使用当前激活的 Conda 环境启动 API 和 Worker：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_m6.ps1
```

随后打开 `http://127.0.0.1:8000/`。完整自动验收使用：

```powershell
python scripts\run_m6_validation.py
```

作业还会执行最大运行时长检查；超过 `MOSAIC_JOB_TIMEOUT_SECONDS` 后以 `JOB_TIMEOUT` 终止。生产环境误配 Fake 拼接或检测 Provider 时，ready 检查返回未就绪。

## 环境要求

- Windows PowerShell
- Python 3.11
- OpenCV/NumPy（随项目依赖自动安装）
- 后续真实推理需要受控的 YOLOv13 权重

没有模型或外部 LLM 时，开发和测试环境仍可使用 fake/rules Provider；内部试运行的拼接 Provider 应使用 `opencv`。

## 初始化

在 PowerShell 中执行：

```powershell
Set-Location -LiteralPath 'E:\vibecoding\蚊媒识别\codex-v2\v2.2\backend'
Copy-Item -LiteralPath '.env.example' -Destination '.env'
powershell -NoProfile -ExecutionPolicy Bypass -File '.\scripts\init_db.ps1'
```

初始化脚本创建 `.venv`、安装项目和开发依赖，并执行：

```powershell
python -m alembic upgrade head
```

## 启动

终端一：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File '.\scripts\dev.ps1'
```

终端二：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File '.\scripts\worker.ps1'
```

访问：

- OpenAPI：`http://127.0.0.1:8000/docs`
- Live：`http://127.0.0.1:8000/api/v1/health/live`
- Ready：`http://127.0.0.1:8000/api/v1/health/ready`
- Version：`http://127.0.0.1:8000/api/v1/version`
- Tasks：`http://127.0.0.1:8000/api/v1/tasks`
- Dashboard：`http://127.0.0.1:8000/api/mosquito-workbench/dashboard`

## YOLOv13 与 YOLO11 双运行配置

后端业务代码由两个模型版本共用，模型运行库、配置、端口、数据库和产物目录相互隔离：

- `config/yolov13.env`：YOLOv13、端口 `8000`、`data/yolov13`。
- `config/yolo11.env`：YOLO11、端口 `8011`、`data/yolo11`。

保留原 YOLOv13 Conda 环境后，可以使用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File '.\scripts\start_yolov13.ps1'
```

创建并安装 `mosquito311-yolov11` 环境后，可以使用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File '.\scripts\start_yolo11.ps1'
```

也可以显式指定 Python，避免依赖固定的 Conda 安装目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File '.\scripts\start_yolo11.ps1' `
  -PythonPath 'D:\Anaconda3\envs\mosquito311-yolov11\python.exe'
```

配置由启动进程载入，不会覆盖现有 `.env`。不要让两个版本共用 SQLite 数据库或 Artifact 目录，否则两个 Worker 可能竞争同一作业队列。

## 测试

```powershell
& '.\.venv\Scripts\python.exe' -m pytest
```

API 启动后可运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File '.\scripts\smoke_test.ps1'
```

M1 完整 HTTP 验证：

```powershell
& '.\.venv\Scripts\python.exe' '.\scripts\m1_smoke_test.py'
```

该脚本会创建临时任务、上传确定性 PNG、下载 Artifact、检查 Dashboard、验证乐观锁并删除临时任务。

M2 API + 独立 Worker 完整验证：

```powershell
python '.\scripts\m2_smoke_test.py'
```

该脚本会通过 API 创建任务和拼接作业，再启动一次独立 Worker 进程，验证 Job 终态、SSE、Fake Mosaic Artifact 和任务 28% 进度，最后自动清理临时任务。

最新 OpenCV SCANS 样例验证：

```powershell
python .\scripts\validate_opencv_mosaic.py --input-dir 'E:\图像识别\预处理-图像拼接-hzz\拼接'
```

样例应显示 `OpenCV SCANS validation passed`，输出尺寸应为 `4839 x 2722`。结果位于 `data/opencv-validation/mosaic.jpg`。

## 运行数据

数据库、WAL、上传文件、模型权重、日志和生成产物均被 `.gitignore` 排除。数据库只保存 Artifact 的相对路径，客户端不能提供或读取服务器绝对路径。

## 数据库迁移

- `20260810_0001`：创建 `worker_heartbeats`。
- `20260810_0002`：创建 `tasks`、`images` 和 `artifacts`。
- `20260811_0003`：创建 `jobs`、`job_events`，并为派生 Artifact 增加 current 标记。

## 拼接 Provider 范围

- `fake`：测试和联调，输出明确标记 `demo=true`。
- `opencv`：内部试运行和生产拼接。仅接受至少 2 张 JPG/JPEG/PNG；默认 `work_scale=0.6`、置信阈值 `0.3`、JPEG 质量 `95`。

该策略适用于同一连续区域、重叠充分、近似共面的影像。它输出像素坐标拼接图，不包含 CRS/GSD，不能标记为测绘级正射成果。默认不对单张原图做去噪、对比度增强、Gamma 或锐化，避免损伤配准特征并制造不一致接缝。
