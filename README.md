# Mosquito Breeding Risk Identification Platform

蚊媒潜在孳生地智能识别与巡查工作台（v2.2）。项目提供交互式前端、FastAPI 后端、异步作业处理、图像拼接、目标识别、风险分析和报告导出能力。

## 当前完成度

后端当前版本为 `0.8.0`，M0–M6 主流程已完成，包括：

- 任务、图片和产物管理；
- 异步作业、Worker、进度事件与超时处理；
- ROI、网格、目标识别结果及人工复核；
- OpenCV `Stitcher_SCANS` 图像拼接；
- 风险计算、处置建议与 PDF/Excel 报告导出；
- v2.2 前端工作台与真实 API 联调；
- YOLOv13 与 YOLO11 两套隔离运行配置；
- 单元、接口、集成和端到端测试。

当前属于本地试运行阶段，不代表已经完成面向其他电脑的一键部署或生产环境发布。

## 当前运行环境

项目目前按开发者本机 Windows 环境配置：

- YOLOv13：Conda 环境 `mosquito311-yolov13`，Python 3.11.15，默认端口 `8000`；
- YOLO11：Conda 环境 `mosquito311-yolov11`，Python 3.11.16，默认端口 `8011`；
- 启动脚本使用本机 `D:\Anaconda3` 下的 Conda 环境；
- 模型权重使用本机 `E:` 盘路径，权重文件未上传到 GitHub；
- `.env`、虚拟环境、数据库、运行数据、模型和临时文件均不纳入仓库。

因此，仓库中的两个 `.bat` 启动文件当前只能在已配置上述环境和模型路径的本机直接运行。其他电脑克隆仓库后不能直接双击运行，需要另行安装依赖、准备模型并修改路径配置。

## 本机启动

- `启动蚊媒识别本地试运行-YOLOv13.bat`：启动 YOLOv13 API 和 Worker；
- `启动蚊媒识别-YOLOv11.bat`：启动 YOLO11 API 和 Worker。

服务就绪后，启动脚本会自动打开对应的本地网页。

## 项目结构

- `index.html`、`api-client.js`、`api-integration.js`：v2.2 前端工作台；
- `backend/`：FastAPI 服务、数据库迁移、Worker 与自动化测试；
- `backend-docs/`：架构、接口、部署和联调文档；
- `test_pictures/`：本地测试图像。

更详细的开发、启动和测试说明见 [`backend/README.md`](backend/README.md)。
