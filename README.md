# Mosquito Breeding Risk Identification Platform

蚊媒潜在孳生地智能识别与巡查工作台（v2.2）。项目提供交互式前端、FastAPI 后端、异步作业处理、图像拼接、风险分析和报告生成能力。

## 项目结构

- `index.html`、`api-client.js`、`api-integration.js`：前端工作台。
- `backend/`：FastAPI 服务、数据迁移、任务 Worker 与自动化测试。
- `backend-docs/`：架构、接口与联调文档。
- `test_pictures/`：测试用图像。

## 本地运行

在 `backend` 目录中复制环境模板并初始化：

```powershell
Copy-Item .env.example .env
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\init_db.ps1
```

随后可分别启动 API 与 Worker：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\worker.ps1
```

打开 `http://127.0.0.1:8000/` 使用工作台；详细说明见 [后端文档](backend/README.md)。

> 本仓库不会包含本机 `.env`、虚拟环境、模型权重、数据库、运行数据或临时文件。请基于 `.env.example` 配置本地环境。
