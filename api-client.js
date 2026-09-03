export class ApiProblem extends Error {
  constructor(problem, status, requestId) {
    super(problem.detail || problem.title || `请求失败（${status}）`);
    this.name = 'ApiProblem';
    this.status = status;
    this.code = problem.code || 'HTTP_ERROR';
    this.requestId = problem.request_id || requestId;
    this.problem = problem;
  }
}

export async function apiFetch(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs || 30000);
  const requestId = crypto.randomUUID();
  const headers = new Headers(options.headers || {});
  headers.set('Accept', 'application/json');
  headers.set('X-Request-ID', requestId);
  let body = options.body;
  if (body && !(body instanceof FormData) && typeof body !== 'string') {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(body);
  }
  try {
    const response = await fetch(path, {...options, body, headers, signal: controller.signal});
    if (!response.ok) {
      const problem = await response.json().catch(() => ({
        title: '请求失败', detail: `HTTP ${response.status}`, status: response.status,
      }));
      throw new ApiProblem(problem, response.status, response.headers.get('X-Request-ID') || requestId);
    }
    if (response.status === 204) return null;
    const contentType = response.headers.get('Content-Type') || '';
    return contentType.includes('json') ? response.json() : response;
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new ApiProblem({title: '请求超时', detail: '服务响应超时，请确认 API 和 Worker 正在运行。'}, 0, requestId);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export function createApiClient(baseUrl = '/api/v1') {
  const call = (path, options) => apiFetch(`${baseUrl}${path}`, options);
  return {
    get: path => call(path),
    post: (path, body, headers) => call(path, {method: 'POST', body, headers}),
    put: (path, body, headers) => call(path, {method: 'PUT', body, headers}),
    patch: (path, body, headers) => call(path, {method: 'PATCH', body, headers}),
    delete: path => call(path, {method: 'DELETE'}),
    upload: (path, form) => call(path, {method: 'POST', body: form, timeoutMs: 120000}),
  };
}

export async function waitForJob(api, resource, onProgress = () => {}) {
  let delay = 350;
  for (;;) {
    const current = await api.get(resource.links.self.replace('/api/v1', ''));
    onProgress(current.job);
    if (current.job.status === 'succeeded') return current.job;
    if (['failed', 'canceled'].includes(current.job.status)) {
      const error = current.job.error || {};
      throw new ApiProblem({
        code: error.code || 'JOB_FAILED',
        title: '后台作业失败',
        detail: error.detail || current.job.message || '请查看服务日志。',
      }, 409, null);
    }
    await new Promise(resolve => setTimeout(resolve, delay));
    delay = Math.min(1500, Math.round(delay * 1.35));
  }
}
