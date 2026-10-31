"""Check the locally configured AI service without printing its credential."""
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.adapters.decision.openai_compatible import NoRedirect, DecisionProviderError, generate, configured
from app.core.config import Settings

values = {}
for line in (Path(__file__).resolve().parents[1] / 'config' / 'ai.local.env').read_text(encoding='utf-8-sig').splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        name, value = line.split('=', 1)
        values[name.strip().lower()] = value.strip()
settings = Settings(_env_file=None, **values)
if not configured(settings):
    print('FAIL: AI configuration is incomplete or the endpoint is invalid')
    sys.exit(1)
try:
    request = Request(settings.openai_base_url.rstrip('/') + '/models', headers={
        'Authorization': 'Bearer ' + settings.openai_api_key.strip(),
    })
    with build_opener(NoRedirect()).open(request, timeout=25) as response:
        models = json.load(response)
    ids = [entry['id'] for entry in models.get('data', [])]
    print('Authentication: OK')
    print('Available models: ' + ', '.join(ids))
    if settings.openai_model not in ids:
        print('FAIL: configured model is not available: ' + settings.openai_model)
        sys.exit(2)
    result = generate(settings, {
        'summary': {'accepted_target_count': 0}, 'hotspots': [], 'categories': [],
        'thresholds': {'medium': 40, 'high': 75},
        'metric_note': 'Synthetic connectivity test; no real task data.',
    }, None, '连通性测试', '仅供测试')
    print('Generation: OK; model=' + settings.openai_model)
    print('Validated suggestions: ' + str(len(result.priorities)))
except DecisionProviderError as error:
    print('FAIL: ' + error.code + ': ' + error.detail)
    sys.exit(1)
except HTTPError as error:
    print('FAIL: HTTP ' + str(error.code) + '; check account permissions or API credential')
    sys.exit(1)
except (URLError, TimeoutError):
    print('FAIL: API connection failed or timed out')
    sys.exit(1)
