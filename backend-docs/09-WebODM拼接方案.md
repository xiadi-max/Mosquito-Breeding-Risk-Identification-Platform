# WebODM 外部拼接方案

## 目标

“预处理－图片拼接”正式 Provider 为 `webodm`。平台后端负责上传任务影像、轮询远程状态、同步进度和取消请求、下载正射成果，并把结果接回现有 ROI、网格、推理、风险分析和报告流程。

原 `opencv` Provider 保留为离线兼容选项，自动化测试继续使用 `fake`，但 YOLOv13 与 YOLO11 两个启动配置均默认选择 `webodm`。

## 一次性配置

在 `backend` 目录执行：

```powershell
Copy-Item -LiteralPath '.\config\webodm.local.env.example' `
  -Destination '.\config\webodm.local.env'
notepad '.\config\webodm.local.env'
```

填写：

```dotenv
WEBODM_URL=http://你的-WebODM-地址:端口
WEBODM_USERNAME=你的用户名
WEBODM_PASSWORD=你的密码
```

`webodm.local.env` 已加入 `.gitignore`，YOLOv13 与 YOLO11 共用这份账号配置。配置不完整时仍可启动平台、创建任务和上传影像；提交拼接时会返回明确的 Provider 未配置错误。

## 远程流程

```text
本地拼接作业
→ JWT 登录 WebODM
→ 按本地任务复用或创建远程项目
→ 按本地作业复用或创建远程任务
→ 上传全部源影像
→ 轮询 queued/running/completed 状态
→ 下载 orthophoto.tif 与 orthophoto.png
→ PNG 等比例生成平台 JPEG 和预览图
→ 登记 Artifact 并继续 ROI/网格/识别流程
```

使用稳定的本地任务 ID 和作业 ID 命名远程项目与任务，因此 Worker 因暂时网络问题重试时会恢复原远程任务，不会盲目重复提交。

## 产物

| Artifact | 用途 |
|---|---|
| `mosaic` | 等比例 JPEG，供 ROI、网格、检测和网页主视图使用 |
| `mosaic_preview` | 小尺寸 JPEG，供快速预览 |
| `mosaic_geotiff` | WebODM 原始 `orthophoto.tif`，保留地理信息 |
| `mosaic_quality` | Provider、远程项目/任务 ID、分辨率、源影像数等追溯信息 |

拼接作业结果包含 `geotiff_download_url`，可通过平台受控 Artifact 接口下载，不向浏览器暴露服务器绝对路径或 WebODM 密码。

## 参数口径

- `WEBODM_ORTHOPHOTO_RESOLUTION=5`：单位为厘米/像素。OpenDroneMap 官方默认值也是 `5`。数值越小越清晰，但耗时、内存和文件大小都会增加。
- `WEBODM_JPEG_MAX_SIDE=12000`：平台后续流程使用的 JPEG 最长边；原 GeoTIFF 不缩小。
- `WEBODM_POLL_SECONDS=10`：远程状态轮询间隔。
- `MOSAIC_JOB_TIMEOUT_SECONDS=172800`：本地最大等待时间，当前为 48 小时。
- `WEBODM_VERIFY_SSL=true`：HTTPS 证书校验。正式环境不应为了绕过证书错误而关闭。

外部样例曾使用 `orthophoto-resolution=0.05`。由于该参数单位是厘米/像素，这相当于请求极端精细的输出，不适合作为平台常规默认值。

## 取消与故障

- 用户取消本地作业后，Worker 会调用 WebODM 的 `cancel` API。
- 401/403 返回 `WEBODM_AUTH_FAILED`，提示检查账号。
- 网络或 WebODM 5xx 返回可重试错误，沿用平台原有重试队列。
- 远程任务失败返回 `WEBODM_TASK_FAILED`，保留 WebODM 的 `last_error`。
- 完成任务缺少 `orthophoto.tif` 或 `orthophoto.png` 时返回 `WEBODM_ASSET_MISSING`。
- 远程账号与密码不会写入数据库、Artifact 元数据或日志。

## 数据与精度边界

上传到 WebODM 的照片会离开本机并保存在外部服务中，正式使用前应确认数据出域、留存和账号权限要求。GeoTIFF 是否可作为测绘成果取决于 GPS/GCP、相机标定、航线重叠、采集质量和项目验收标准；仅使用 WebODM 不等于自动满足测绘精度。
