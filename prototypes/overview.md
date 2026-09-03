# MosquitoMapper 数据拆分重构

## 做了什么
将 `mosquito-platform-wireframe.html` 中内联的数据做了 **静态配置 vs 动态数据** 的分离：

### 新增文件

**`data.js`** — 前端静态常量配置（不依赖后端，永不变化）：
| 模块 | 说明 |
|---|---|
| `APP_META` | 应用名/版本 |
| `APP_CONFIG` | 网格尺寸、上传上限、画布参数 |
| `SIMULATED_LOCATIONS` | 8 个模拟巡检点位 |
| `BUILDING_LAYOUTS` | 4 套建筑布局模板 |
| `RISK_CONFIG` | 风险等级颜色/大小/标签映射 |
| `HEATMAP_GRADIENT` | 热力图渐变 |
| `PROGRESS_STEPS` | 处理流水线步骤定义 |
| `ZONE_POLYGON` | 地图 Zone 边界 |
| `MOCK_DATE_RANGE` | 模拟时间范围 |

**`test_data.js`** — 模拟后端 API 返回的动态数据：
| 函数/常量 | 对应接口语义 |
|---|---|
| `getTimestamp(i)` | 模拟时间戳生成 |
| `generateMockUploadFiles(n)` | `GET /api/files?batch=xxx` — 文件列表+预标注 |
| `MOCK_MAP_POINTS` | `GET /api/map/points?zone=xxx` — 风险检测点位 |
| `generateHeatmapData(points)` | 热力图图层数据 |
| `generateProgressLogs(totalZones)` | 流水线进度日志 |

### HTML 修改点
- 在 `<script>` 前引入 `data.js` 和 `test_data.js`
- 移除内联 `simulatedLocations` / `buildingLayouts` / progress steps / map points / heatmap gradient
- `initDemoData()` 改为调用 `generateMockUploadFiles(6)`
- `simulateProgress()` 改为调用 `generateProgressLogs()`
- `initMap()` 改为引用 `ZONE_POLYGON` / `MOCK_MAP_POINTS` / `RISK_CONFIG` / `generateHeatmapData()` / `HEATMAP_GRADIENT`
- 变量命名统一为 `UPPER_SNAKE_CASE`（常量）

## 关键决策
- **分类原则**：数据是否会随请求变化 → test_data.js；是否为展示/规则/布局的固定配置 → data.js
- **依赖顺序**：`data.js` → `test_data.js`（test_data 依赖 APP_CONFIG / SIMULATED_LOCATIONS / RISK_CONFIG / PROGRESS_STEPS）
- 所有 mock 函数都有对应 API 语义注释，方便后续替换为真实 fetch
