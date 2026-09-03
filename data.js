/* 前端静态配置：不随任务、识别结果或风险分析而变化。 */
const runtimeConfig = window.RUNTIME_CONFIG || {};
const demoRequested = new URLSearchParams(window.location.search).get('demo') === '1';
window.APP_CONFIG = {
  dataMode: demoRequested && runtimeConfig.demoAllowed ? 'test' : 'api',
  api: {
    baseUrl: runtimeConfig.apiBaseUrl || '/api/v1',
    dynamicDataUrl: runtimeConfig.dashboardUrl || '/api/mosquito-workbench/dashboard'
  },
  stageMeta: [
    ['HOME · TASK HUB', '从一个任务开始，完成一套<em>蚊媒风险识别</em>', '这里是你的任务首页：先选择或创建巡查任务，再按流程完成影像处理、目标识别、热点分析和处置建议。'],
    ['STEP 01 · IMAGE INGEST', '把一次航拍，变成一个<em>识别任务</em>', '上传同一区域的连续航拍影像。系统整理影像与定位信息，为后续拼接建立任务批次。'],
    ['STEP 02 · MOSAIC PREPROCESSING', '先拼成全貌，再开始<em>理解区域</em>', '使用 OpenCV SCANS 对同一区域重叠影像做仿射配准、曝光与接缝融合，并自动裁掉黑边。'],
    ['STEP 03 · DETECTION ROI', '圈定真正需要关注的<em>连片屋顶</em>', '在拼接图上标注一个或多个检测范围 ROI。模型只识别范围内部，不以单栋屋顶作为统计单位。'],
    ['STEP 04 · GRID PREVIEW', '把完整区域，切成模型熟悉的<em>视野</em>', '按 640 × 640 像素生成重叠网格，边缘自动补边。调整参数时，预览与数据量会即时变化。'],
    ['STEP 05 · MODEL INFERENCE', '让自训练模型完成<em>检测与识别</em>', '预留 YOLOv13 接入位置，可调置信度阈值，并保留低置信度候选的人工复核环节。'],
    ['STEP 06 · KERNEL DENSITY', '从检测点，看到<em>目标聚集区域</em>', '检测结果映射回拼接图并计算 KDE 目标聚集指数。指数为本任务内部相对值，重点检查区域不直接展示检测框与编号。'],
    ['STEP 07 · AI DECISION', '从聚集分布，走向<em>处置行动</em>', '面向疾控管理人员按目标聚集指数与复核证据生成优先处理区域，支持补充现场信息、编辑和重新生成。'],
    ['GUIDE · GETTING STARTED', '第一次使用？先了解<em>准备事项与基本规则</em>', '这里介绍工作台能做什么、开始前需要准备什么，以及新手最常遇到的问题。'],
    ['WORKFLOW · ALL STEPS', '七个操作步骤，组成一套<em>完整识别流程</em>', '具体流程操作属于当前任务。按顺序完成，也可以从总览中进入任一步查看。']
  ],
  grid: {
    tileWidth: 300,
    tileHeight: 260,
    startX: 30,
    startY: 38,
    limitX: 870,
    limitY: 500,
    modelPixelSize: 640,
    defaultOverlap: 20,
    megabytesPerTile: 2.35
  },
  model: {
    confidenceDefault: 45,
    pipeline: [
      { name: '载入模型与网格', description: '初始化推理任务' },
      { name: '目标检测与类别识别', description: '水桶、花盆、轮胎、水箱及其他容器' },
      { name: '跨网格去重与坐标还原', description: '将结果映射回拼接图' },
      { name: '低置信度结果筛选', description: '进入人工复核队列' }
    ]
  }
};
