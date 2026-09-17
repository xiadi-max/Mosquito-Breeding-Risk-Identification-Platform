/*
 * Netlify 静态演示配置。
 * 该部署仅展示预置的交互数据，不连接 FastAPI、Worker 或 YOLO 模型。
 */
(() => {
  const url = new URL(window.location.href);
  if (url.searchParams.get('demo') !== '1') {
    url.searchParams.set('demo', '1');
    window.location.replace(url.toString());
    return;
  }

  window.RUNTIME_CONFIG = {
    demoAllowed: true,
    environment: 'netlify-demo'
  };
})();
