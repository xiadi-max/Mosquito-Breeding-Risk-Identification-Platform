import { ApiProblem, apiFetch, createApiClient, waitForJob } from './api-client.js';

const qs = selector => document.querySelector(selector);
const qsa = selector => [...document.querySelectorAll(selector)];
const text = (id, value) => { const node = document.getElementById(id); if (node) node.textContent = value; };
const escapeText = value => String(value ?? '');

export async function startApiIntegration({initialDashboard, toast, goStep}) {
  const config = window.APP_CONFIG;
  const api = createApiClient(config.api.baseUrl);
  const state = {
    dashboard: initialDashboard,
    taskId: initialDashboard.meta?.current_task_id || initialDashboard.tasks?.[0]?.uuid || null,
    task: null, images: [], mosaic: null, roi: null, gridPreview: null, gridPlan: null,
    detections: null, risk: null, decision: null, system: null, mosaicObjectUrl: null,
    mosaicArtifactId: null,
    modelInputSize: initialDashboard.model?.activeVersion?.inputSize || config.grid?.modelPixelSize || 640,
  };
  window.M6_API_STATE = state;

  const notifyError = error => {
    const suffix = error instanceof ApiProblem && error.requestId ? `（请求 ${error.requestId}）` : '';
    toast(`${error.message || '操作失败'}${suffix}`);
  };
  const run = async (button, busyText, action) => {
    const original = button?.textContent;
    if (button) { button.disabled = true; button.textContent = busyText; }
    try { return await action(); }
    catch (error) { notifyError(error); throw error; }
    finally { if (button) { button.disabled = false; button.textContent = original; } }
  };
  const requireTask = () => {
    if (!state.taskId) throw new Error('请先创建或选择任务');
    return state.taskId;
  };
  const idempotency = prefix => `${prefix}-${requireTask()}-${Date.now()}`;
  const jobProgress = (job, labelId) => {
    if (labelId) text(labelId, `${job.progress}%`);
    if (labelId === 'stitchPct') qs('#stitchOrb')?.style.setProperty('--progress', `${job.progress}%`);
  };

  function installModeBadge() {
    // Runtime details belong in diagnostics, not in a floating pill that
    // obscures workflow controls.
    qs('#runtimeMode')?.remove();
  }

  const artifactUrl = artifactId => `${config.api.baseUrl}/artifacts/${encodeURIComponent(artifactId)}/content`;
  const formatCount = value => Number(value || 0).toLocaleString('zh-CN');
  const SVG_XLINK = 'http://www.w3.org/1999/xlink';
  const setSvgImageHref = (image, url) => {
    if (!image) return;
    image.setAttribute('href', url);
    image.setAttributeNS(SVG_XLINK, 'href', url);
  };
  const clearSvgImageHref = image => {
    if (!image) return;
    image.removeAttribute('href');
    image.removeAttributeNS(SVG_XLINK, 'href');
  };
  const categoryLabels = {
    'foam box': '泡沫箱', bucket: '水桶', 'flower pot': '花盆', tire: '轮胎', tyre: '轮胎',
    'water tank': '储水箱', container: '容器', bottle: '瓶罐',
  };
  const displayCategory = value => {
    if (!value) return '未分类目标';
    const translated = categoryLabels[String(value).trim().toLowerCase()];
    return translated ? `${translated}（${value}）` : value;
  };
  const knownMosaicArtifactId = (risk = state.risk) => state.mosaicArtifactId
    || state.mosaic?.mosaic_artifact_id
    || state.roi?.source?.artifact_id
    || state.gridPlan?.source_artifact_id
    || risk?.artifacts?.mosaic_artifact_id
    || null;
  function mosaicLocation(hotspot, width, height) {
    const saved = String(hotspot?.name || '').trim();
    if (saved && !/^热点区域(?:\s+H\d+)?$/i.test(saved)) return saved.replace(/重点检查区域$/, '');
    const x = Number(hotspot?.centroid?.x || 0) / Math.max(1, Number(width || 1));
    const y = Number(hotspot?.centroid?.y || 0) / Math.max(1, Number(height || 1));
    const horizontal = x < 1 / 3 ? '西' : x > 2 / 3 ? '东' : '中';
    const vertical = y < 1 / 3 ? '北' : y > 2 / 3 ? '南' : '中';
    if (horizontal === '中' && vertical === '中') return '拼接图中部';
    if (horizontal === '中') return `拼接图${vertical}部`;
    if (vertical === '中') return `拼接图${horizontal}部`;
    return `拼接图${horizontal}${vertical}部`;
  }
  function hotspotClusteringIndex(hotspot) {
    return Number(hotspot?.clustering_index ?? hotspot?.score ?? 0);
  }
  const setChip = (id, label, level = '') => {
    const node = qs(`#${id}`);
    if (!node) return;
    node.textContent = label;
    node.className = `risk${level ? ` ${level}` : ''}`;
  };
  const appendEmpty = (parent, message) => {
    const empty = document.createElement('div');
    empty.className = 'footnote';
    empty.style.padding = '22px 5px';
    empty.style.textAlign = 'center';
    empty.textContent = message;
    parent.appendChild(empty);
  };

  function ensureHeatImages() {
    const svg = qs('.heatmap svg');
    const anchor = qs('#heatLayer');
    if (!svg || !anchor) return {};
    let mosaic = qs('#heatMosaicPreview');
    if (!mosaic) {
      mosaic = document.createElementNS('http://www.w3.org/2000/svg', 'image');
      mosaic.id = 'heatMosaicPreview';
      mosaic.setAttribute('width', '900'); mosaic.setAttribute('height', '570');
      mosaic.setAttribute('preserveAspectRatio', 'none'); mosaic.style.display = 'none';
      svg.insertBefore(mosaic, anchor);
    }
    let density = qs('#densityPreviewImage');
    if (!density) {
      density = document.createElementNS('http://www.w3.org/2000/svg', 'image');
      density.id = 'densityPreviewImage';
      density.setAttribute('width', '900'); density.setAttribute('height', '570');
      density.setAttribute('preserveAspectRatio', 'none'); density.setAttribute('opacity', '.58');
      density.style.display = 'none'; svg.insertBefore(density, anchor);
    }
    return {svg, mosaic, density};
  }

  function renderPipelineIdle() {
    qsa('.pipe-step').forEach((step, index) => {
      step.className = 'pipe-step';
      step.querySelector('.pipe-state').textContent = index === 0 ? '待开始' : '等待';
    });
  }

  function resetResultPanel() {
    text('acceptedCount', '--'); text('acceptedNote', '等待风险分析'); text('hotCount', '--');
    text('categoryCount', '--'); text('categoryNote', '当前任务'); text('resultRoiArea', '--'); text('roiAreaLabel', '检测范围');
    const categories = qs('#categoryStats');
    if (categories) { categories.replaceChildren(); appendEmpty(categories, '等待当前任务的风险分析结果'); }
    qs('#heatLayer')?.replaceChildren(); qs('#contourLayer')?.replaceChildren();
    qs('.heat-side')?.querySelectorAll('.hotspot').forEach(node => node.remove());
    const {svg, mosaic, density} = ensureHeatImages();
    const mosaicId = knownMosaicArtifactId();
    if (mosaic && mosaicId) {
      setSvgImageHref(mosaic, artifactUrl(mosaicId)); mosaic.style.display = '';
      text('heatBaseStatus', '实景拼接底图 · 已加载');
    } else if (mosaic) { clearSvgImageHref(mosaic); mosaic.style.display = 'none'; }
    if (density) { clearSvgImageHref(density); density.style.display = 'none'; }
    if (!mosaicId) text('heatBaseStatus', '实景拼接底图 · 等待加载');
    if (svg) qsa('.heatmap svg > rect, .heatmap svg > path').forEach(node => { node.style.display = 'none'; });
    qsa('[data-stage="6"] .grid-3 .btn').forEach(button => { button.disabled = true; });
  }

  function resetDecisionPanel() {
    const evidence = qs('#decisionEvidence');
    if (evidence) { evidence.replaceChildren(); const note = document.createElement('span'); note.textContent = '等待本任务的真实风险结果'; evidence.appendChild(note); }
    const article = qs('#suggestion');
    if (article) {
      article.replaceChildren(); article.contentEditable = 'false';
      const title = document.createElement('h3'); title.textContent = '尚未生成处置建议';
      const note = document.createElement('p'); note.textContent = '完成真实风险分析后，点击左侧按钮生成本任务的建议。';
      article.append(title, note);
    }
    const button = qs('#generateAi'); if (button) { button.disabled = true; button.textContent = '✦ 生成处置建议'; }
    qs('#riskBasisExplanation')?.remove();
  }

  function resetApiBusinessPanels() {
    renderPipelineIdle();
    const reviews = qs('#reviewList'); if (reviews) { reviews.replaceChildren(); appendEmpty(reviews, '尚无真实推理候选'); }
    text('reviewCount', '0'); text('reviewSourceNote', '等待真实推理结果；候选图块将从本任务的拼接影像中生成。');
    resetResultPanel(); resetDecisionPanel();
    text('homeTaskTotal', state.dashboard.tasks?.length || 0);
    text('homeTaskRunning', (state.dashboard.tasks || []).filter(task => task.state === 'running').length);
    text('homeDetectionCount', '--'); text('homeHotspotCount', '--');
  }

  function renderDecisionMode() {
    const provider = state.system?.providers?.decision?.name || state.dashboard.meta?.capabilities?.decision || 'rules';
    const rules = provider === 'rules';
    text('decisionProviderBadge', rules ? 'RULES · REAL DATA' : `AI · ${provider.toUpperCase()}`);
    text('decisionModeCopy', rules
      ? '当前使用离线规则引擎，建议只引用本任务的真实重点检查区域、类别和人工补充信息，不会伪装成大模型输出。'
      : '已配置 AI Provider；建议将基于本任务的真实风险结果与人工补充信息生成。');
    const button = qs('#generateAi'); if (button && !state.decision) button.textContent = rules ? '✦ 生成规则处置建议' : '✦ 生成 AI 处置建议';
  }

  function renderRuntimeStatus() {
    const detector = state.system?.providers?.detector;
    const provider = detector?.name || state.dashboard.model?.provider || state.dashboard.meta?.capabilities?.detector || 'detector';
    const active = state.dashboard.model?.activeVersion;
    const configured = Boolean(detector?.configured);
    state.modelInputSize = active?.inputSize || state.modelInputSize;
    text('topModelProvider', provider === 'yolov13' ? 'YOLOv13' : provider);
    setChip('topModelStatus', configured ? (active ? '已接入' : '已配置') : '不可用', configured ? 'low' : 'high');
    setChip('homeModelStatus', configured ? (active ? '已接入' : '已配置') : '不可用', configured ? 'low' : 'high');
    setChip('modelStatus', configured ? (active ? '真实模型' : '已配置') : '不可用', configured ? 'low' : 'high');
    text('modelName', active?.name || (provider === 'yolov13' ? '自训练 YOLOv13 检测模型' : `${provider} 检测模型`));
    const details = active
      ? [active.weightsLabel, `${active.inputSize} × ${active.inputSize}`, String(active.device).toUpperCase(), active.codeVersion]
      : [configured ? '服务端配置已通过检查' : '权重或运行时检查失败'];
    text('modelMeta', details.join(' · '));
    renderDecisionMode();
  }

  async function hydrateRuntime() {
    try { state.system = await api.get('/version'); }
    catch (error) { notifyError(error); state.system = null; }
    renderRuntimeStatus();
  }

  function wireTaskCards() {
    const tasks = state.dashboard.tasks || [];
    qsa('.task-card').forEach((card, index) => {
      const task = tasks[index]; if (!task) return;
      card.dataset.taskId = task.uuid;
      card.onclick = () => selectTask(task.uuid, card);
    });
  }

  async function reloadDashboard(taskId = state.taskId) {
    const suffix = taskId ? `?task_id=${encodeURIComponent(taskId)}` : '';
    state.dashboard = await apiFetch(`${config.api.dynamicDataUrl}${suffix}`);
    state.taskId = state.dashboard.meta?.current_task_id || taskId || null;
    return state.dashboard;
  }

  async function selectTask(taskId, card) {
    try {
      state.taskId = taskId;
      qsa('.task-card').forEach(item => item.classList.toggle('selected', item === card));
      await reloadDashboard(taskId);
      renderRuntimeStatus();
      await hydrateTask();
      const label = `${state.task.name} · ${state.task.code.slice(-4)}`;
      text('currentTaskName', label); text('homeCurrentTask', label); toast(`已切换到任务：${state.task.name}`);
    } catch (error) { notifyError(error); }
  }

  async function hydrateTask() {
    if (!state.taskId) return;
    const taskId = state.taskId;
    if (state.mosaicObjectUrl) URL.revokeObjectURL(state.mosaicObjectUrl);
    Object.assign(state, {
      task:null, images:[], mosaic:null, roi:null, gridPreview:null, gridPlan:null,
      detections:null, risk:null, decision:null, mosaicObjectUrl:null, mosaicArtifactId:null,
    });
    resetApiBusinessPanels(); renderRuntimeStatus();
    const calls = await Promise.allSettled([
      api.get(`/tasks/${taskId}`), api.get(`/tasks/${taskId}/images`), api.get(`/tasks/${taskId}/rois`),
      api.get(`/tasks/${taskId}/grid-plan`), api.get(`/tasks/${taskId}/detections`), api.get(`/tasks/${taskId}/results`),
      api.get(`/tasks/${taskId}/decisions`),
    ]);
    if (calls[0].status === 'fulfilled') state.task = calls[0].value;
    if (calls[1].status === 'fulfilled') { state.images = calls[1].value.items; renderImages(calls[1].value); }
    if (calls[2].status === 'fulfilled') { state.roi = calls[2].value; renderRoiSummary(state.roi); }
    if (calls[3].status === 'fulfilled') state.gridPlan = calls[3].value;
    if (calls[4].status === 'fulfilled') { state.detections = calls[4].value; renderReviews(calls[4].value); renderInferenceSummary(calls[4].value); }
    if (calls[5].status === 'fulfilled' && calls[5].value.run_id) state.risk = calls[5].value;
    if (calls[6].status === 'fulfilled' && calls[6].value.items.length) state.decision = calls[6].value.items[0];
    const mosaicId = state.task?.artifacts?.mosaic_artifact_id || state.task?.artifacts?.mosaic?.id || knownMosaicArtifactId(state.risk);
    if (mosaicId && !state.mosaic) {
      state.mosaic = {mosaic_artifact_id: mosaicId, width: state.roi?.source?.width, height: state.roi?.source?.height};
      await renderMosaicArtifact(state.mosaic);
    }
    if (state.risk) renderRisk(state.risk);
    if (state.decision) renderDecision(state.decision);
    text('homeDetectionCount', state.detections?.stats?.accepted ?? 0);
    text('homeHotspotCount', state.risk?.hotspots?.length ?? 0);
  }

  async function createTask() {
    const button = qs('#taskModal .modal-actions .primary');
    await run(button, '正在创建…', async () => {
      const name = qs('#taskNameInput').value.trim(), area = qs('#taskAreaInput').value.trim();
      if (!name || !area) throw new Error('请先填写任务名称和巡查区域');
      const task = await api.post('/tasks', {name, area, survey_date: qs('#taskDateInput').value, task_type: qs('#taskTypeInput').value});
      state.taskId = task.id; state.task = task; qs('#taskModal').classList.remove('open');
      location.reload();
    });
  }

  async function uploadFiles(files) {
    if (!files.length) return;
    const supported = files.filter(file => /\.(jpe?g|png)$/i.test(file.name));
    const skipped = files.length - supported.length;
    if (!supported.length) throw new Error('请选择 JPG、JPEG 或 PNG 影像');
    const form = new FormData(); supported.slice(0, 50).forEach(file => form.append('files', file, file.name));
    await run(qs('#chooseFiles'), '正在上传…', async () => {
      const result = await api.upload(`/tasks/${requireTask()}/images`, form);
      const listing = await api.get(`/tasks/${requireTask()}/images`);
      state.images = listing.items; renderImages(listing);
      const rejected = result.rejected.length, duplicates = result.duplicates.length;
      const rejectionDetails = result.rejected
        .slice(0, 2)
        .map(item => `${item.display_name}：${item.detail}`)
        .join('；');
      const skippedDetails = skipped ? '；存在非 JPG、JPEG 或 PNG 文件' : '';
      toast(
        `上传完成：新增 ${result.accepted.length}，重复 ${duplicates}，拒绝 ${rejected + skipped}` +
        (rejectionDetails ? `；${rejectionDetails}` : '') +
        skippedDetails
      );
    });
  }

  function renderImages(payload) {
    const items = payload.items || payload.accepted || state.images;
    const summary = payload.summary || {image_count:items.length,total_size_bytes:items.reduce((sum,item)=>sum+item.size_bytes,0),gps_count:items.filter(item=>item.gps).length};
    const list = qs('#fileList'); list.replaceChildren();
    for (const item of items) {
      const row = document.createElement('div'); row.className = 'file';
      const thumb = document.createElement('div'); thumb.className = 'thumb';
      const info = document.createElement('div'), name = document.createElement('div'), meta = document.createElement('div');
      name.className = 'file-name'; name.textContent = item.display_name;
      meta.className = 'file-meta'; meta.textContent = `${(item.size_bytes/1048576).toFixed(1)} MB · ${item.gps ? 'GPS READY' : (item.warnings?.join('；') || '无定位信息')}`;
      info.append(name, meta);
      const actions = document.createElement('div'); actions.className = 'file-actions';
      const check = document.createElement('span'); check.className='check'; check.textContent='✓'; check.title='服务端校验通过';
      const remove = document.createElement('button'); remove.type='button'; remove.className='image-delete'; remove.textContent='删除'; remove.title=`删除 ${item.display_name}`;
      remove.onclick=event=>{event.preventDefault();event.stopPropagation();deleteImage(item,remove).catch(()=>{})};
      actions.append(check,remove); row.append(thumb, info, actions); list.appendChild(row);
    }
    if (!items.length) list.innerHTML='<div class="footnote" style="padding:30px 5px;text-align:center">上传后将在这里检查文件完整性</div>';
    text('uploadCount', summary.image_count); text('gpsCount', summary.gps_count); text('uploadSize', `${(summary.total_size_bytes/1048576).toFixed(1)} MB`);
    text('captureSpan', summary.capture_span_seconds == null ? '--' : `${Math.round(summary.capture_span_seconds/60)} min`);
    text('mosaicSourceCount', items.length);
    text('uploadStatus', items.length >= 2 ? `${items.length} 张影像已由服务端校验` : (items.length ? '已校验 1 张；至少还需 1 张才能拼接' : '等待导入影像'));
    qs('#toStitch').disabled = items.length < 2;
    qs('#startStitch').disabled = items.length < 2;
  }

  function invalidateDerivedClientState() {
    if (state.mosaicObjectUrl) URL.revokeObjectURL(state.mosaicObjectUrl);
    Object.assign(state, {mosaic:null,roi:null,gridPreview:null,gridPlan:null,detections:null,risk:null,decision:null,mosaicObjectUrl:null});
    for (const id of ['mosaicPreviewImage','annotMosaicPreview']) {
      const image=qs(`#${id}`); if(image){image.removeAttribute('href');image.style.display='none'}
    }
    if(qs('#stitchPieces')) qs('#stitchPieces').style.display='';
    text('stitchCanvasStatus','影像已变更，请重新生成拼接图');
    qs('#toAnnot').disabled=true;
  }

  async function deleteImage(item, button) {
    if (!confirm(`确定删除“${item.display_name}”吗？删除后已有拼接、网格和分析结果将失效。`)) return;
    await run(button,'删除中…',async()=>{
      await api.delete(`/tasks/${requireTask()}/images/${item.id}`);
      const listing=await api.get(`/tasks/${requireTask()}/images`);
      state.images=listing.items; invalidateDerivedClientState(); renderImages(listing);
      toast(`已删除影像：${item.display_name}`);
    });
  }

  async function resetUpload() {
    const taskId=requireTask(), listing=await api.get(`/tasks/${taskId}/images`);
    if (!listing.items.length) return;
    if (!confirm('清空影像会使拼接、网格、推理、风险和报告失效，确定继续吗？')) return;
    for (const image of listing.items) await api.delete(`/tasks/${taskId}/images/${image.id}`);
    state.images=[]; invalidateDerivedClientState(); renderImages({items:[],summary:{image_count:0,total_size_bytes:0,gps_count:0,capture_span_seconds:null}}); toast('任务影像已清空');
  }

  async function startMosaic() {
    const button=qs('#startStitch');
    await run(button,'正在拼接…',async()=>{
      const resource=await api.post(`/tasks/${requireTask()}/mosaic-jobs`,{provider:'auto'},{'Idempotency-Key':idempotency('mosaic')});
      const job=await waitForJob(api,resource,current=>{jobProgress(current,'stitchPct');text('stitchCanvasStatus',current.message||current.current_step)});
      state.mosaic=job.result; await renderMosaicArtifact(job.result); text('stitchCanvasStatus','拼接图已生成'); qs('#toAnnot').disabled=false; toast('SCANS 仿射拼接完成');
    });
  }

  async function renderMosaicArtifact(result) {
    if (!result?.mosaic_artifact_id) return;
    state.mosaicArtifactId = result.mosaic_artifact_id;
    const directUrl = artifactUrl(result.mosaic_artifact_id);
    const {mosaic: heatMosaic} = ensureHeatImages();
    const images = ['mosaicPreviewImage', 'annotMosaicPreview', 'heatMosaicPreview'].map(id => qs(`#${id}`)).filter(Boolean);
    let fallbackStarted = false;
    const applySource = url => images.forEach(image => { setSvgImageHref(image, url); image.style.display = ''; });
    if (heatMosaic) {
      text('heatBaseStatus', '实景拼接底图 · 正在加载');
      heatMosaic.onload = () => text('heatBaseStatus', '实景拼接底图 · 已加载');
      heatMosaic.onerror = async () => {
        if (fallbackStarted) { text('heatBaseStatus', '实景拼接底图 · 加载失败'); return; }
        fallbackStarted = true;
        try {
          const response = await api.get(`/artifacts/${result.mosaic_artifact_id}/content`);
          const blob = await response.blob();
          if (state.mosaicObjectUrl) URL.revokeObjectURL(state.mosaicObjectUrl);
          state.mosaicObjectUrl = URL.createObjectURL(blob);
          applySource(state.mosaicObjectUrl);
        } catch (_) { text('heatBaseStatus', '实景拼接底图 · 加载失败'); }
      };
    }
    applySource(directUrl);
    if (qs('#stitchPieces')) qs('#stitchPieces').style.display = 'none';
    if (qs('#annotPlaceholder')) qs('#annotPlaceholder').style.display = 'none';
    if (qs('#annotPlaceholderRoad')) qs('#annotPlaceholderRoad').style.display = 'none';
    text('mosaicDimensions', `MOSAIC · ${result.width || '--'} × ${result.height || '--'} px`);
    const quality = result.quality || {};
    text('qCoverage', quality.strategy === 'opencv_scans_affine' ? 'SCANS 仿射' : (quality.engine || '--'));
    text('qOverlap', quality.work_scale == null ? '--' : String(quality.work_scale));
    text('qGps', `${quality.gps_count ?? 0} / ${quality.source_image_count ?? state.images.length}`);
    text('qError', `${quality.anomalous_images?.length ?? 0} 张`);
  }

  const svgToNative = ([x,y]) => [x/900*(state.mosaic?.width||state.roi?.source?.width||900), y/545*(state.mosaic?.height||state.roi?.source?.height||545)];
  function renderRoiSummary(collection){
    const items=collection?.items||[],measured=items.length>0&&items.every(item=>item.area_m2!=null);
    const area=items.reduce((sum,item)=>sum+(measured?item.area_m2:item.area_px2),0);
    text('roiArea',items.length?(measured?`${formatCount(Math.round(area))} m²`:'未标定'):'--');text('roiCount',items.length);
  }
  async function saveRois() {
    const taskId=requireTask();
    const localRois = window.getEditorRois?.() || [];
    if (!localRois.length) throw new Error('至少需要一个检测范围');
    const current=await api.get(`/tasks/${taskId}/rois`), sourceId=state.mosaic?.mosaic_artifact_id||current.source?.artifact_id;
    if (!sourceId) throw new Error('请先完成拼接');
    state.roi=await api.put(`/tasks/${taskId}/rois`,{expected_version:current.version,source_artifact_id:sourceId,coordinate_space:'mosaic_pixel',items:localRois.map((roi,index)=>({code:roi.id||`ROI-${index+1}`,visible:roi.visible!==false,polygon:roi.points.map(svgToNative)}))});renderRoiSummary(state.roi);
    toast('检测范围已保存到服务端'); return state.roi;
  }

  function renderGridPreview(preview) {
    state.gridPreview=preview; const width=state.roi?.source?.width||900,height=state.roi?.source?.height||520,layer=qs('#gridLayer'); layer.replaceChildren();
    for (const tile of preview.tiles) { const [x1,y1,x2,y2]=tile.source_box,r=document.createElementNS('http://www.w3.org/2000/svg','rect'); r.setAttribute('x',x1/width*900);r.setAttribute('y',y1/height*520);r.setAttribute('width',(x2-x1)/width*900);r.setAttribute('height',(y2-y1)/height*520);r.setAttribute('class','grid-cell');layer.appendChild(r); }
    text('gridCount',preview.count);text('validGrid',preview.count);text('padGrid',preview.padded_count);text('gridSize',`${(preview.estimated_bytes/1048576).toFixed(1)} MB`);text('stepPx',`${preview.step_px} px`);
  }
  async function previewGrid() {
    if (!state.taskId) return; if (!state.roi) { try { await saveRois(); } catch { return; } }
    const preview=await api.post(`/tasks/${state.taskId}/grid-plans/preview`,{roi_version:state.roi.version,tile_size:640,overlap:+qs('#overlapRange').value/100,edge_strategy:'pad',min_roi_intersection:.1});renderGridPreview(preview);
  }
  async function persistGrid() {
    await run(qs('[data-stage="4"] .stage-actions .primary'),'正在生成网格…',async()=>{if(!state.gridPreview)await previewGrid();const payload={roi_version:state.gridPreview.roi_version,tile_size:640,overlap:state.gridPreview.overlap,edge_strategy:'pad',min_roi_intersection:.1,fingerprint:state.gridPreview.fingerprint};const resource=await api.put(`/tasks/${requireTask()}/grid-plan`,payload,{'Idempotency-Key':idempotency('grid')});await waitForJob(api,resource);state.gridPlan=await api.get(`/tasks/${state.taskId}/grid-plan`);goStep(5);toast('网格已生成，可以开始推理')});
  }

  function renderReviews(data) {
    const list=qs('#reviewList'); list.replaceChildren();
    const pending=data.items.filter(item=>item.effective_state==='pending');
    const pendingCount=data.stats?.pending ?? pending.length;
    text('reviewCount',pendingCount);
    for(const item of pending){
      const row=document.createElement('div');row.className='review';row.dataset.detectionId=item.id;
      const img=document.createElement('div');img.className='review-img';
      if(item.crop_artifact_id){img.style.backgroundImage=`url(${artifactUrl(item.crop_artifact_id)})`;img.style.backgroundSize='cover';img.style.backgroundPosition='center'}
      const info=document.createElement('div'),name=document.createElement('div'),meta=document.createElement('div');
      name.className='review-name';name.textContent=`候选 #${item.code} · ${item.category.name}`;
      meta.className='review-meta';meta.textContent=`CONF ${item.confidence.toFixed(2)} · GRID ${item.source_grid}`;info.append(name,meta);
      const actions=document.createElement('div');actions.className='review-actions';
      for(const [label,action,cls] of [['保留','accept',''],['排除','reject',' danger']]){const b=document.createElement('button');b.className=`btn small${cls}`;b.textContent=label;b.onclick=()=>review(item,b,action);actions.appendChild(b)}
      row.append(img,info,actions);list.appendChild(row)
    }
    if(!pending.length) appendEmpty(list,data.run_id?'当前推理没有待复核候选':'尚未运行真实模型推理');
    text('reviewSourceNote',data.run_id
      ? `候选图块来自当前真实推理批次 ${data.run_id.slice(0,8)}；已接受 ${data.stats.accepted}，已排除 ${data.stats.rejected}。`
      : '等待真实推理结果；候选图块将从本任务的拼接影像中生成。');
    const resultButton=qs('#toResults');
    if(resultButton){resultButton.disabled=!data.run_id||pendingCount>0;resultButton.textContent=pendingCount?`请先复核 ${pendingCount} 项`:(state.risk?.run_id?'查看真实结果热力图 →':'计算真实风险结果 →')}
  }
  function renderInferenceSummary(data){
    if(data?.run_id){
      qsa('.pipe-step').forEach(step=>{step.className='pipe-step done';step.querySelector('.pipe-state').textContent='完成'});
      qs('#runModel').textContent='重新运行模型推理';
    }else{
      renderPipelineIdle();qs('#runModel').textContent='开始模型推理';
    }
    text('homeDetectionCount',data?.stats?.accepted ?? 0);
  }
  async function runInference() {
    let completed=false;
    await run(qs('#runModel'),'模型推理中…',async()=>{
      if(state.system?.providers?.detector && !state.system.providers.detector.configured)throw new Error('服务端检测模型检查未通过，请检查权重与运行时版本');
      if(!state.gridPlan)state.gridPlan=await api.get(`/tasks/${requireTask()}/grid-plan`);
      state.risk=null;state.decision=null;resetResultPanel();resetDecisionPanel();
      const minimum=+qs('#confRange').value/100;
      const resource=await api.post(`/tasks/${state.taskId}/inference-jobs`,{grid_plan_id:state.gridPlan.id,provider:'auto',infer_min_confidence:minimum,review_threshold:Math.max(minimum,.5),auto_accept_threshold:Math.max(minimum,.8),nms_iou:.45},{'Idempotency-Key':idempotency('inference')});
      await waitForJob(api,resource,job=>updatePipeline(job));
      state.detections=await api.get(`/tasks/${state.taskId}/detections`);renderReviews(state.detections);completed=true;
    });
    if(completed){renderInferenceSummary(state.detections);toast(`真实模型推理完成：${state.detections.stats.total} 个结果，${state.detections.stats.pending} 个待复核`)}
  }
  function updatePipeline(job){
    const steps=qsa('.pipe-step');
    if(job.status==='succeeded'||job.progress>=100){steps.forEach(step=>{step.className='pipe-step done';step.querySelector('.pipe-state').textContent='完成'});return}
    const map={queued:0,load_model:0,load_tiles:0,detect:1,nms:2,map_coordinates:2,class_aware_nms:2,persist:3,review_queue:3,build_review_queue:3};
    const active=map[job.current_step]??0;
    steps.forEach((step,index)=>{step.className=`pipe-step${index<active?' done':index===active?' active':''}`;step.querySelector('.pipe-state').textContent=index<active?'完成':index===active?(job.status==='failed'?'失败':`${job.progress}%`):'等待'});
  }
  async function review(item,button,action){
    await run(button,'提交中…',async()=>{
      await api.patch(`/tasks/${requireTask()}/reviews/${item.id}`,{action,expected_version:item.version});
      state.detections=await api.get(`/tasks/${requireTask()}/detections`);renderReviews(state.detections);renderInferenceSummary(state.detections);
      toast(action==='accept'?'候选已保留并计入真实结果':'候选已排除')
    });
  }

  let riskRefreshRunning=false,riskRefreshQueued=false,riskRefreshTimer=null;
  function readRiskThresholds(){
    const high=qs('#highRange'),medium=qs('#medRange');let hi=+high.value,med=+medium.value;
    if(med>=hi){med=Math.max(+medium.min,hi-5);medium.value=med}
    text('highVal',hi);text('medVal',med);return{high:hi,medium:med}
  }
  async function calculateRisk({button=qs('#toResults'),navigate=true}={}){
    const thresholds=readRiskThresholds();
    await run(button,'正在重算风险…',async()=>{
      const detections=await api.get(`/tasks/${requireTask()}/detections`);
      if(!detections.run_id)throw new Error('请先完成真实模型推理');
      if(detections.stats.pending)throw new Error(`还有 ${detections.stats.pending} 项待复核`);
      text('riskSyncStatus','正在按新聚集指数分界重算热力图…');
      const resource=await api.post(`/tasks/${state.taskId}/risk-runs`,{inference_run_id:detections.run_id,review_snapshot_version:detections.review_snapshot_version,method:'kde',bandwidth_px:180,resolution_px:32,medium_threshold:thresholds.medium,high_threshold:thresholds.high},{'Idempotency-Key':idempotency('risk')});
      await waitForJob(api,resource);state.risk=await api.get(`/tasks/${state.taskId}/results`);state.decision=null;resetDecisionPanel();renderRisk(state.risk);if(navigate)goStep(6);toast(`聚集指数分界 ${thresholds.medium} / ${thresholds.high} 已应用，热力图已重算`)
    });
  }
  async function runRisk(){return calculateRisk({button:qs('#toResults'),navigate:true})}
  async function refreshRiskFromThresholds(){
    if(!state.detections?.run_id)return;
    if(riskRefreshRunning){riskRefreshQueued=true;return}
    riskRefreshRunning=true;
    try{await calculateRisk({button:qs('#riskRecalculate'),navigate:false})}catch(_){/* run() already reports the API problem */}
    finally{riskRefreshRunning=false;if(riskRefreshQueued){riskRefreshQueued=false;await refreshRiskFromThresholds()}}
  }
  function installRiskAndDecisionControls(){
    const toolbar=qs('[data-stage="6"]>.card .toolbar'),copy=toolbar?.querySelector('.toolbar-copy');
    const baseStatus=toolbar?.querySelector('.status-line span');
    if(baseStatus){baseStatus.id='heatBaseStatus';baseStatus.textContent='实景拼接底图 · 等待加载'}
    const hotMetric=qs('#hotCount')?.closest('.metric');
    const hotMetricLabel=hotMetric?.querySelector('span');if(hotMetricLabel)hotMetricLabel.textContent='重点检查区域';
    const hotspotSideLabel=[...(qs('.heat-side')?.querySelectorAll('.side-label')||[])].at(-1);if(hotspotSideLabel)hotspotSideLabel.textContent='重点检查区域';
    const layerButtons=toolbar?[...toolbar.querySelectorAll('.btn.small')]:[];
    const boundaryButton=layerButtons.find(button=>button.textContent.includes('热点边界'));if(boundaryButton)boundaryButton.textContent='区域边界';
    if(copy)copy.textContent='实景拼接底图 · 相对聚集颜色 · 重点检查区域边界';
    const legend=qs('[data-stage="6"] .legend');
    const legendTitle=legend?.querySelector('b');if(legendTitle)legendTitle.textContent='目标聚集指数（本任务相对值）';
    const legendScale=legend?[...legend.querySelectorAll('.legend-scale span')]:[];
    if(legendScale[0])legendScale[0].textContent='较弱';if(legendScale[1])legendScale[1].textContent='';if(legendScale[2])legendScale[2].textContent='较强';
    const decisionEntry=qs('[data-stage="6"]>.stage-actions .primary');if(decisionEntry)decisionEntry.textContent='进入处置建议 →';
    if(toolbar&&!qs('#riskRecalculate')){
      const status=document.createElement('span');status.id='riskSyncStatus';status.className='quiet';status.textContent='聚集指数分界与热力图已同步';
      const button=document.createElement('button');button.id='riskRecalculate';button.type='button';button.className='btn small';button.textContent='按当前阈值重算';button.onclick=()=>refreshRiskFromThresholds();
      toolbar.insertBefore(status,copy);toolbar.insertBefore(button,copy);
    }
    const heatLayout=qs('[data-stage="6"] .heat-layout');
    if(heatLayout&&!qs('#hotspotMapHelp')){
      const help=document.createElement('div');help.id='hotspotMapHelp';help.className='risk-explanation';help.style.marginTop='12px';
      help.textContent='H01 是本次自动编号的第 1 处重点检查区域：系统先按目标聚集指数从高到低编号，指数相同时再按拼接图从北到南、从西到东排序。白色虚线只表示达到当前分界、且彼此相连范围的近似外包边界，不是目标框、屋顶边界或行政边界；编号会随重新分析而变化。';
      heatLayout.insertAdjacentElement('afterend',help);
    }
    const high=qs('#highRange'),medium=qs('#medRange');
    const changed=()=>{const values=readRiskThresholds();text('riskSyncStatus',`聚集指数分界 ${values.medium} / ${values.high} 待重算`)};
    const committed=()=>{clearTimeout(riskRefreshTimer);riskRefreshTimer=setTimeout(()=>refreshRiskFromThresholds(),250)};
    high.oninput=changed;medium.oninput=changed;high.onchange=committed;medium.onchange=committed;
    const generate=qs('#generateAi'),context=qs('#contextInput');
    if(generate&&context){generate.style.marginTop='12px';context.parentElement.insertBefore(generate,context)}
  }
  function renderDecisionEvidence(){
    const evidence=qs('#decisionEvidence');if(!evidence)return;evidence.replaceChildren();
    if(!state.risk?.run_id){const span=document.createElement('span');span.textContent='等待本任务的真实风险结果';evidence.appendChild(span);qs('#riskBasisExplanation')?.remove();return}
    const createdAt=state.risk.created_at?new Date(state.risk.created_at).toLocaleString('zh-CN',{hour12:false}):'当前结果';
    const values=[
      `分析时间 ${createdAt}`,
      `人工复核保留目标 ${state.risk.summary.accepted_target_count} 个`,
      `重点检查区域 ${state.risk.hotspots.length} 处`,
      `聚集指数分界 ${state.risk.thresholds.medium} / ${state.risk.thresholds.high}`,
      ...state.risk.categories.slice(0,3).map(item=>`${displayCategory(item.name)} ${item.count} 个`),
    ];
    if(state.decision) values.push(`建议版本 ${state.decision.version}`);
    for(const value of values){const span=document.createElement('span');span.textContent=value;evidence.appendChild(span)}
    let explanation=qs('#riskBasisExplanation');
    if(!explanation){explanation=document.createElement('div');explanation.id='riskBasisExplanation';explanation.className='risk-explanation';evidence.insertAdjacentElement('afterend',explanation)}
    const count=state.risk.hotspots.length,medium=state.risk.thresholds.medium;
    explanation.textContent=`“重点检查区域”是目标聚集指数达到 ${medium}、且彼此相连的范围。本次为 ${count} 处${count===1?'，表示所有达到分界的范围连成一个区域':''}。系统按指数从高到低编号为 H01、H02……；白色虚线是近似外包边界，不是目标框、屋顶或行政边界。该指数把本任务 KDE 峰值归一为 100，只用于任务内定位和分级，不是疾病概率、布雷图指数，也不能跨任务直接比较。`;
  }
  function renderRisk(risk){
    const summary=risk.summary||{};
    text('acceptedCount',formatCount(summary.accepted_target_count));
    text('acceptedNote',state.detections?.stats?`排除 ${state.detections.stats.rejected} · 待复核 ${state.detections.stats.pending}`:'当前有效结果');
    text('hotCount',risk.hotspots.length);text('categoryCount',risk.categories.length);
    text('categoryNote',state.dashboard.model?.activeVersion?.provider||state.dashboard.model?.provider||'当前模型');
    text('homeDetectionCount',summary.accepted_target_count||0);text('homeHotspotCount',risk.hotspots.length);
    text('highVal',risk.thresholds.high);text('medVal',risk.thresholds.medium);qs('#highRange').value=risk.thresholds.high;qs('#medRange').value=risk.thresholds.medium;
    const roiItems=state.roi?.items||[],hasMeasuredArea=roiItems.length>0&&roiItems.every(item=>item.area_m2!=null);
    const measuredArea=roiItems.reduce((sum,item)=>sum+Number(item.area_m2||0),0);
    text('resultRoiArea',hasMeasuredArea?formatCount(Math.round(measuredArea)):roiItems.length?'未标定':'--');text('roiAreaLabel',hasMeasuredArea?'检测范围 m²':'检测范围');
    const categories=qs('#categoryStats');categories.replaceChildren();const max=Math.max(1,...risk.categories.map(item=>item.count));
    for(const item of risk.categories){const row=document.createElement('div');row.className='bar-row';const name=document.createElement('span');name.textContent=item.name;const track=document.createElement('div');track.className='bar-track';const fill=document.createElement('div');fill.className='bar-fill';fill.style.width=`${item.count/max*100}%`;track.appendChild(fill);const count=document.createElement('b');count.textContent=item.count;row.append(name,track,count);categories.appendChild(row)}
    if(!risk.categories.length)appendEmpty(categories,'本次没有已接受的检测类别');
    const heat=qs('#heatLayer'),contours=qs('#contourLayer'),side=qs('.heat-side');heat.replaceChildren();contours.replaceChildren();side.querySelectorAll('.hotspot').forEach(node=>node.remove());
    const mosaicId=knownMosaicArtifactId(risk),mosaicImage=qs('#heatMosaicPreview');
    if(mosaicId&&(!mosaicImage?.getAttribute('href')||state.mosaicArtifactId!==mosaicId)){
      state.mosaic={mosaic_artifact_id:mosaicId,width:state.roi?.source?.width,height:state.roi?.source?.height};
      void renderMosaicArtifact(state.mosaic).catch(()=>text('heatBaseStatus','实景拼接底图 · 加载失败'));
    }
    const {density}=ensureHeatImages();const densityId=risk.artifacts?.density_preview_id;
    const transparentDensity=risk.artifacts?.density_render_mode==='transparent_overlay';
    if(density&&densityId&&transparentDensity){setSvgImageHref(density,artifactUrl(densityId));density.style.display=''}
    else if(density){clearSvgImageHref(density);density.style.display='none'}
    const width=state.roi?.source?.width||1,height=state.roi?.source?.height||1;
    for(const [index,hotspot] of risk.hotspots.entries()){
      const points=hotspot.geometry.coordinates?.[0]||[],scaled=points.map(([x,y])=>[x/width*900,y/height*570]);if(!scaled.length)continue;
      const xs=scaled.map(p=>p[0]),ys=scaled.map(p=>p[1]),cx=hotspot.centroid.x/width*900,cy=hotspot.centroid.y/height*570;
      const clusteringIndex=hotspotClusteringIndex(hotspot),clusteringLevel=hotspot.clustering_level??hotspot.risk_level;
      const ellipse=document.createElementNS('http://www.w3.org/2000/svg','ellipse');ellipse.setAttribute('class','heat-blob');ellipse.setAttribute('cx',cx);ellipse.setAttribute('cy',cy);ellipse.setAttribute('rx',Math.max(30,(Math.max(...xs)-Math.min(...xs))/2));ellipse.setAttribute('ry',Math.max(24,(Math.max(...ys)-Math.min(...ys))/2));ellipse.setAttribute('fill',clusteringLevel==='high'?'url(#heatHigh)':'url(#heatMed)');if(!transparentDensity)heat.appendChild(ellipse);
      const polygon=document.createElementNS('http://www.w3.org/2000/svg','polygon');polygon.id=`contour-${hotspot.code}`;polygon.setAttribute('class','hotspot-contour');polygon.setAttribute('points',scaled.map(p=>p.join(',')).join(' '));contours.appendChild(polygon);
      const location=mosaicLocation(hotspot,width,height);
      const mapLabel=document.createElementNS('http://www.w3.org/2000/svg','text');mapLabel.setAttribute('class','hotspot-label');mapLabel.setAttribute('x',cx);mapLabel.setAttribute('y',cy);mapLabel.textContent=`${hotspot.code} · 指数 ${clusteringIndex} · ${hotspot.target_count} 个目标`;contours.appendChild(mapLabel);
      const item=document.createElement('div');item.className=`hotspot${index===0?' active':''}`;item.dataset.hot=hotspot.code;item.dataset.score=clusteringIndex;
      const highClustering=clusteringLevel==='high';
      const head=document.createElement('div');head.className='hotspot-head';const label=document.createElement('span');label.textContent=`${hotspot.code} · ${location}`;const level=document.createElement('span');level.className=`risk ${highClustering?'high':'med'}`;level.textContent=highClustering?'高聚集':'中聚集';head.append(label,level);
      const data=document.createElement('div');data.className='hotspot-data';for(const value of [`目标聚集指数 ${clusteringIndex}/100`,`复核保留 ${hotspot.target_count} 个`, `识别类别 ${displayCategory(hotspot.dominant_category)}`]){const span=document.createElement('span');span.textContent=value;data.appendChild(span)}item.append(head,data);
      item.onclick=()=>{side.querySelectorAll('.hotspot').forEach(node=>node.classList.remove('active'));contours.querySelectorAll('.hotspot-contour').forEach(node=>node.classList.remove('focus'));item.classList.add('active');polygon.classList.add('focus')};side.appendChild(item)
    }
    if(!risk.hotspots.length){const note=document.createElement('div');note.className='footnote';note.style.gridColumn='1/-1';note.textContent=summary.reason==='NO_ACCEPTED_DETECTIONS'?'本次没有人工复核保留的目标，未形成重点检查区域':'当前阈值下未形成重点检查区域';side.appendChild(note)}
    qsa('[data-stage="6"] .grid-3 .btn').forEach(button=>{button.disabled=!risk.run_id});
    const resultButton=qs('#toResults');if(resultButton){resultButton.disabled=false;resultButton.textContent='查看真实结果热力图 →'}
    const decisionButton=qs('#generateAi');if(decisionButton)decisionButton.disabled=!risk.run_id;
    text('riskSyncStatus',`已应用聚集指数分界 ${risk.thresholds.medium} / ${risk.thresholds.high}`);renderDecisionEvidence();renderDecisionMode();
  }

  async function generateDecision(){
    let generated=null;
    await run(qs('#generateAi'),'正在生成建议…',async()=>{
      if(!state.risk?.run_id)state.risk=await api.get(`/tasks/${requireTask()}/results`);
      if(!state.risk?.run_id)throw new Error('请先完成真实风险分析');
      const provider=state.system?.providers?.decision?.name||state.dashboard.meta?.capabilities?.decision||'rules';
      const resource=await api.post(`/tasks/${state.taskId}/decisions`,{risk_run_id:state.risk.run_id,context:qs('#contextInput').value.trim()||null,provider},{'Idempotency-Key':idempotency('decision')});
      await waitForJob(api,resource);const list=await api.get(`/tasks/${state.taskId}/decisions`);generated=list.items[0];state.decision=generated;
    });
    if(generated){renderDecision(generated);toast(`基于真实风险结果的处置建议版本 ${generated.version} 已生成`)}
  }
  function renderDecision(decision){
    const article=qs('#suggestion');article.replaceChildren();article.contentEditable='true';
    const title=document.createElement('h3');title.textContent=decision.title;article.appendChild(title);
    for(const priority of decision.priorities){const block=document.createElement('div');block.className=`priority${priority.level==='P1'?'':' med'}`;const heading=document.createElement('h4');heading.textContent=`优先级 ${priority.level}：${priority.heading}`;block.appendChild(heading);for(const paragraph of priority.body.split(/\n\s*\n/).filter(Boolean)){const body=document.createElement('p');body.textContent=paragraph;block.appendChild(body)}article.appendChild(block)}
    const evidence=document.createElement('div');evidence.className='evidence';
    const provider=decision.provider?.name||decision.source;for(const value of [`版本 ${decision.version}`,new Date(decision.created_at).toLocaleString(),`来源 ${provider}`,decision.disclaimer]){const span=document.createElement('span');span.textContent=value;evidence.appendChild(span)}article.appendChild(evidence);
    text('decisionDisclaimer',decision.disclaimer);qs('#generateAi').textContent=provider==='rules'?'✦ 重新生成规则建议':'✦ 重新生成 AI 建议';renderDecisionEvidence();
  }
  async function saveDecision(){if(!state.decision)throw new Error('请先生成处置建议');const blocks=qsa('#suggestion .priority'),priorities=blocks.map((block,index)=>({level:state.decision.priorities[index]?.level||'P2',hotspot_code:state.decision.priorities[index]?.hotspot_code||null,heading:block.querySelector('h4')?.textContent.replace(/^优先级 P\d：/,'')||'处置建议',body:[...block.querySelectorAll('p')].map(node=>node.textContent).join('\n\n'),evidence_refs:state.decision.priorities[index]?.evidence_refs||[]}));state.decision=await api.patch(`/tasks/${requireTask()}/decisions/${state.decision.id}`,{title:qs('#suggestion h3')?.textContent||state.decision.title,priorities,disclaimer:state.decision.disclaimer,expected_current_version:state.decision.version});renderDecision(state.decision);toast(`建议草稿已保存为版本 ${state.decision.version}`);}
  async function exportReport(format,button){await run(button,`正在生成 ${format.toUpperCase()}…`,async()=>{if(!state.risk?.run_id)state.risk=await api.get(`/tasks/${requireTask()}/results`);if(!state.risk?.run_id)throw new Error('请先完成真实风险分析');const resource=await api.post(`/tasks/${state.taskId}/exports`,{format,risk_run_id:state.risk.run_id,decision_version_id:state.decision?.id||null,include_detection_details:true},{'Idempotency-Key':idempotency(`export-${format}`)});const job=await waitForJob(api,resource);const url=job.result.download_url;const anchor=document.createElement('a');anchor.href=url;anchor.download='';document.body.appendChild(anchor);anchor.click();anchor.remove();toast(`${format.toUpperCase()} 已根据当前真实结果生成并开始下载`)});}

  // Install the API handlers before hydrating the selected task. A rendering
  // error in an old/completed task must not leave the legacy demo handlers in
  // control of task creation or image upload.
  installModeBadge(); installRiskAndDecisionControls(); resetApiBusinessPanels(); wireTaskCards();
  window.createTask=createTask; window.resetUpload=()=>resetUpload().catch(notifyError); window.resolveReview=()=>toast('请使用当前复核项按钮');
  qs('#taskModal .modal-actions .primary').onclick=event=>{event.preventDefault();createTask().catch(()=>{})};
  const fileInput=qs('#fileInput');
  qs('#chooseFiles').onclick=event=>{event.preventDefault();event.stopPropagation();fileInput.value='';fileInput.click()};
  fileInput.onchange=()=>{const files=[...fileInput.files];fileInput.value='';uploadFiles(files).catch(()=>{})};
  qs('#dropzone').ondrop=event=>{event.preventDefault();qs('#dropzone').classList.remove('drag');uploadFiles([...event.dataTransfer.files]).catch(()=>{})};
  qs('#demoFiles').onclick=event=>{event.stopPropagation();toast('API 模式请上传真实影像；演示模式请使用 ?demo=1')};qs('#startStitch').onclick=()=>startMosaic().catch(()=>{});
  const saveButton=qs('[data-stage="3"] .stage-actions .right .btn');saveButton.onclick=()=>saveRois().catch(notifyError);qs('[data-stage="3"] .stage-actions .primary').onclick=()=>saveRois().then(()=>goStep(4)).catch(notifyError);
  let previewTimer;qs('#overlapRange').oninput=event=>{text('overlapValue',`${event.target.value}%`);clearTimeout(previewTimer);previewTimer=setTimeout(()=>previewGrid().catch(notifyError),250)};qs('[data-stage="4"] .stage-actions .primary').onclick=()=>persistGrid().catch(()=>{});qs('[data-stage="4"] .stage-actions .right .btn').onclick=()=>previewGrid().catch(notifyError);
  qs('#runModel').onclick=()=>runInference().catch(()=>{});qs('#toResults').onclick=()=>state.risk?.run_id?goStep(6):runRisk().catch(()=>{});qs('#generateAi').onclick=()=>generateDecision().catch(()=>{});
  const exportButtons=qsa('[data-stage="6"] .grid-3 .btn');[['csv',exportButtons[0]],['xlsx',exportButtons[1]],['pdf',exportButtons[2]]].forEach(([format,button])=>button.onclick=()=>exportReport(format,button).catch(()=>{}));
  const decisionButtons=qsa('[data-stage="7"] .stage-actions .right .btn');decisionButtons[0].onclick=()=>saveDecision().catch(notifyError);decisionButtons[1].onclick=()=>exportReport('pdf',decisionButtons[1]).catch(()=>{});
  document.addEventListener('click',event=>{const button=event.target.closest('.task-delete');if(!button)return;event.preventDefault();event.stopImmediatePropagation();const card=button.closest('.task-card'),taskId=card?.dataset.taskId;if(!taskId||!confirm('确定删除此任务及其影像和结果吗？'))return;api.delete(`/tasks/${taskId}`).then(()=>location.reload()).catch(notifyError)},true);
  await hydrateRuntime();
  if(state.taskId) {
    try { await hydrateTask(); }
    catch(error) { notifyError(error); }
  }
}
