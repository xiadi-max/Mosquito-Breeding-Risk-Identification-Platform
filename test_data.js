/* 测试数据：仅用于前端联调。生产环境由后端接口返回相同结构的动态数据。 */
window.TEST_DATA = {
  tasks: [
    { name: '棠下村航拍巡查', id: 'T-0716', type: '城中村', status: '处理中', state: 'running', progress: 14, date: '2026-07-16', summary: '12 张影像', selected: true },
    { name: '石牌村雨后复查', id: 'T-0709', type: '雨后复查', status: '已完成', state: 'done', date: '2026-07-09', summary: '28 张影像' },
    { name: '黄埔片区例行巡查', id: 'T-0628', type: '例行巡查', status: '已归档', state: 'archived', date: '2026-06-28', summary: '46 张影像' }
  ],
  demoImages: [
    { name: 'DJI_20260716_0801.JPG', size: 7100000 }, { name: 'DJI_20260716_0802.JPG', size: 7240000 }, { name: 'DJI_20260716_0803.JPG', size: 7380000 }, { name: 'DJI_20260716_0804.JPG', size: 7520000 },
    { name: 'DJI_20260716_0805.JPG', size: 7660000 }, { name: 'DJI_20260716_0806.JPG', size: 7800000 }, { name: 'DJI_20260716_0807.JPG', size: 7940000 }, { name: 'DJI_20260716_0808.JPG', size: 8080000 },
    { name: 'DJI_20260716_0809.JPG', size: 8220000 }, { name: 'DJI_20260716_0810.JPG', size: 8360000 }, { name: 'DJI_20260716_0811.JPG', size: 8500000 }, { name: 'DJI_20260716_0812.JPG', size: 8640000 }
  ],
  rois: [{ id: 'ROI-01', visible: true, points: [[82, 86], [383, 55], [649, 82], [826, 145], [834, 353], [725, 478], [420, 502], [145, 452], [52, 296]] }],
  model: {
    completedTargetCount: 36,
    reviews: [
      { id: 'C-018', category: '其他容器', confidence: 0.42, grid: 'G08' },
      { id: 'C-026', category: '花盆', confidence: 0.38, grid: 'G11' },
      { id: 'C-031', category: '水桶', confidence: 0.44, grid: 'G14' }
    ]
  },
  risk: {
    highThreshold: 75,
    mediumThreshold: 40,
    hotspots: [
      { id: 'H01', area: '东南片区', clusteringIndex: 88, targets: 16, category: '水桶', contour: 'M565 310C610 250 760 245 830 330C885 400 820 495 720 510C620 522 535 438 565 310Z', label: [702, 390], blob: { cx: 700, cy: 380, rx: 180, ry: 148, fill: 'url(#heatHigh)' } },
      { id: 'H02', area: '中北片区', clusteringIndex: 72, targets: 12, category: '花盆', contour: 'M260 95C310 42 425 45 485 110C540 175 472 264 380 270C294 273 225 190 260 95Z', label: [365, 155], blob: { cx: 370, cy: 155, rx: 150, ry: 125, fill: 'url(#heatMed)' } },
      { id: 'H03', area: '西南片区', clusteringIndex: 45, targets: 8, category: '轮胎', contour: 'M80 340C118 290 220 285 272 344C315 397 264 475 180 486C105 495 48 415 80 340Z', label: [160, 392], blob: { cx: 175, cy: 390, rx: 126, ry: 108, fill: 'url(#heatLow)' } }
    ]
  }
};
