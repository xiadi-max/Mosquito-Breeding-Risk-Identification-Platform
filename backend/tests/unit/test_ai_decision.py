import json
from urllib.error import HTTPError
from unittest.mock import MagicMock, patch

import pytest

from app.adapters.decision.openai_compatible import DecisionProviderError, configured, generate
from app.core.config import Settings


def settings(**values):
    return Settings(_env_file=None, decision_provider='openai_compatible',
                    openai_base_url='https://api.deepseek.com', openai_api_key='test-key',
                    openai_model='deepseek-flash', **values)


EVIDENCE = {'summary': {'accepted_target_count': 12}, 'hotspots': [{'code': 'H01'}]}
CONTENT = {'title': 'AI标题', 'priorities': [{'level': 'P1', 'hotspot_code': 'H01',
           'heading': '检查H01', 'body': '根据检测统计，现场核查并记录。',
           'evidence_refs': ['hotspot:H01']}], 'disclaimer': 'AI免责声明'}


def mock_response(payload=CONTENT, finish='stop'):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({
        'choices': [{'message': {'content': json.dumps(payload)}, 'finish_reason': finish}]
    }).encode()
    return response


def test_ai_request_uses_statistics_and_context_and_returns_validated_content():
    with patch('app.adapters.decision.openai_compatible.build_opener') as opener:
        opener.return_value.open.return_value = mock_response()
        result = generate(settings(), EVIDENCE, '近期降雨', '任务标题', '固定免责声明')
        request = opener.return_value.open.call_args.args[0]
        body = json.loads(request.data)
        assert request.full_url == 'https://api.deepseek.com/chat/completions'
        assert request.get_header('Authorization') == 'Bearer test-key'
        assert body['response_format'] == {'type': 'json_object'}
        assert body['thinking'] == {'type': 'disabled'}
        data = json.loads(body['messages'][1]['content'])
        assert data['evidence']['summary']['accepted_target_count'] == 12
        assert data['user_context'] == '近期降雨'
        assert 'test-key' not in request.data.decode()
        assert result.title == '任务标题' and result.disclaimer == '固定免责声明'
        assert result.priorities[0].hotspot_code == 'H01'


@pytest.mark.parametrize('status', [401, 402, 429, 500])
def test_api_errors_do_not_leak_credentials_or_remote_body(status):
    with patch('app.adapters.decision.openai_compatible.build_opener') as opener:
        opener.return_value.open.side_effect = HTTPError('https://api.deepseek.com', status, 'test-key', {}, None)
        with pytest.raises(DecisionProviderError) as error:
            generate(settings(), EVIDENCE, None, 'title', 'disclaimer')
        assert error.value.code == 'DECISION_API_ERROR'
        assert 'test-key' not in str(error.value)


def test_unknown_hotspot_and_truncated_json_are_rejected():
    invalid = {**CONTENT, 'priorities': [{**CONTENT['priorities'][0], 'hotspot_code': 'H99'}]}
    for payload, finish in [(invalid, 'stop'), (CONTENT, 'length')]:
        with patch('app.adapters.decision.openai_compatible.build_opener') as opener:
            opener.return_value.open.return_value = mock_response(payload, finish)
            with pytest.raises(DecisionProviderError):
                generate(settings(), EVIDENCE, None, 'title', 'disclaimer')


def test_missing_key_or_insecure_url_is_not_configured():
    value = settings()
    assert configured(value)
    assert 'test-key' not in repr(value)
    value.openai_api_key = ''
    assert not configured(value)
    value.openai_api_key = 'test-key'
    value.openai_base_url = 'http://api.deepseek.com'
    assert not configured(value)


def test_no_hotspot_empty_reference_is_normalized_without_accepting_unknown_codes():
    payload = {**CONTENT, 'priorities': [{
        'level': 'P3', 'hotspot_code': '', 'heading': '常规巡查',
        'body': '保持常规巡查并记录现场情况。', 'evidence_refs': [],
    }]}
    with patch('app.adapters.decision.openai_compatible.build_opener') as opener:
        opener.return_value.open.return_value = mock_response(payload)
        result = generate(settings(), {'hotspots': []}, None, 'title', 'disclaimer')
    assert result.priorities[0].hotspot_code is None
