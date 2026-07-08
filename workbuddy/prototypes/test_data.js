/**
 * test_data.js — 模拟后端 API 返回的动态数据
 * 真实环境中这些数据由后端接口提供，此处用于前端原型/联调
 * 数据特征：会随请求变化、与业务状态强相关
 */

// ============================================================
// 工具函数：生成模拟时间戳
// ============================================================
function getTimestamp(i) {
  const d = new Date(MOCK_DATE_RANGE.year, MOCK_DATE_RANGE.month - 1, MOCK_DATE_RANGE.day);
  d.setHours(MOCK_DATE_RANGE.startHour + Math.floor(i / 2));
  d.setMinutes((i % 2) * 30 + Math.floor(Math.random() * 20));
  return d.toISOString().slice(0, 19).replace('T', ' ');
}

// ============================================================
// 接口1：生成模拟上传文件列表（含预标注）
// 对应 POST /api/files 或 GET /api/files?batch=xxx 返回值
// ============================================================
function generateMockUploadFiles(count) {
  count = count || 6;
  const files = [];

  for (let i = 0; i < count; i++) {
    const loc = SIMULATED_LOCATIONS[i % SIMULATED_LOCATIONS.length];
    files.push({
      id:          Date.now() + i,
      name:        `DJI_20260708_1403${String(i + 1).padStart(2, '0')}.JPG`,
      size:        8500000 + Math.random() * 3000000,
      zone:        loc.zone,
      lat:         loc.lat + (Math.random() - 0.5) * 0.002,
      lng:         loc.lng + (Math.random() - 0.5) * 0.002,
      alt:         loc.alt + (Math.random() - 0.5) * 2,
      time:        getTimestamp(i),
      desc:        loc.desc,
      autoExtracted: true,
      selected:    false,
      thumbnail:   null,
      annotations: [],
      annotStatus: 'pending',
    });
  }

  // 预标注数据（模拟推理结果）
  if (count >= 3) {
    // 第1张：3个屋顶
    files[0].annotations = [
      { id: 'R01', points: [{ x: 30, y: 30 }, { x: 200, y: 35 }, { x: 195, y: 200 }, { x: 20, y: 195 }], area: 170 * 165 },
      { id: 'R02', points: [{ x: 290, y: 30 }, { x: 460, y: 25 }, { x: 470, y: 210 }, { x: 300, y: 215 }], area: 180 * 185 },
      { id: 'R03', points: [{ x: 30, y: 270 }, { x: 205, y: 265 }, { x: 200, y: 410 }, { x: 15, y: 405 }], area: 190 * 145 },
    ];
    files[0].annotStatus = 'done';

    // 第2张：1个屋顶
    files[1].annotations = [
      { id: 'R01', points: [{ x: 20, y: 20 }, { x: 180, y: 15 }, { x: 175, y: 190 }], area: 150 * 170 },
    ];
    files[1].annotStatus = 'done';

    // 第3张：2个屋顶
    files[2].annotations = [
      { id: 'R01', points: [{ x: 530, y: 15 }, { x: 640, y: 10 }, { x: 635, y: 200 }, { x: 525, y: 195 }], area: 110 * 185 },
      { id: 'R02', points: [{ x: 675, y: 15 }, { x: 780, y: 12 }, { x: 785, y: 150 }, { x: 680, y: 148 }], area: 105 * 138 },
    ];
    files[2].annotStatus = 'done';
  }

  return files;
}

// ============================================================
// 接口2：地图风险检测点位列表
// 对应 POST /api/detections/map 或 GET /api/map/points?zone=xxx
// ============================================================
const MOCK_MAP_POINTS = [
  { lat: 23.1265, lng: 113.3605, risk: 'high', label: 'D01 水桶 0.92', desc: '积水容器' },
  { lat: 23.1268, lng: 113.3620, risk: 'high', label: 'D06 水桶 0.91', desc: '积水容器' },
  { lat: 23.1270, lng: 113.3685, risk: 'high', label: 'D08 水桶 0.87', desc: '积水容器' },
  { lat: 23.1260, lng: 113.3610, risk: 'med',  label: 'D02 花盆 0.88', desc: '花盆' },
  { lat: 23.1290, lng: 113.3660, risk: 'med',  label: 'D04 水桶 0.42', desc: '人工确认' },
  { lat: 23.1275, lng: 113.3635, risk: 'med',  label: 'D05 花盆 0.86', desc: '花盆' },
  { lat: 23.1305, lng: 113.3615, risk: 'med',  label: 'D07 花盆 0.82', desc: '花盆' },
  { lat: 23.1265, lng: 113.3690, risk: 'med',  label: 'D12 容器 0.38', desc: '人工确认' },
  { lat: 23.1315, lng: 113.3680, risk: 'med',  label: 'D21 容器 0.35', desc: '人工确认' },
  { lat: 23.1300, lng: 113.3700, risk: 'med',  label: 'D18 容器 0.31', desc: '排除' },
  { lat: 23.1255, lng: 113.3590, risk: 'low',  label: 'D03 绿植 0.95', desc: '绿植' },
  { lat: 23.1285, lng: 113.3640, risk: 'low',  label: 'D10 绿植 0.94', desc: '绿植' },
  { lat: 23.1310, lng: 113.3650, risk: 'low',  label: 'D09 花盆 0.85', desc: '花盆' },
];

// ============================================================
// 函数：从点位数据生成热力图密度数据
// 对应后端热力图图层数据（或服务端渲染瓦片）
// ============================================================
function generateHeatmapData(points) {
  const data = points.map(p => {
    const intensity = RISK_CONFIG.heatIntensity[p.risk] || 0.3;
    return [p.lat, p.lng, intensity];
  });

  // 补充随机散点增加密度细节
  for (let i = 0; i < 20; i++) {
    const base = points[Math.floor(Math.random() * points.length)];
    data.push([
      base.lat + (Math.random() - 0.5) * 0.002,
      base.lng + (Math.random() - 0.5) * 0.002,
      0.3 + Math.random() * 0.4,
    ]);
  }

  return data;
}

// ============================================================
// 函数：根据 upload 总数动态生成流水线首条日志
// ============================================================
function generateProgressLogs(totalZones) {
  const steps = PROGRESS_STEPS.map(s => ({ ...s }));
  steps[0].log = `[INFO] 准备处理 ${totalZones} 个 Zone，网格 ${APP_CONFIG.DEFAULT_GRID_SIZE}×${APP_CONFIG.DEFAULT_GRID_SIZE}`;
  steps[steps.length - 1].log = '[DONE] 全链路完成 · 耗时 2m 14s';
  return steps;
}
