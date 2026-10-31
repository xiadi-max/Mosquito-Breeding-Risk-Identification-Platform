import json
from unittest.mock import patch

from app.domain.m5_schemas import DecisionContent, PriorityItem
from app.worker import run_worker
from tests.integration.test_m5_workflow import prepare_reviewed_inference, complete_job


def test_ai_decision_is_generated_and_persisted_with_model_and_evidence(test_settings, migrated_client):
    task_id, run_id, review_version = prepare_reviewed_inference(test_settings, migrated_client)
    queued = migrated_client.post(f'/api/v1/tasks/{task_id}/risk-runs', json={
        'inference_run_id': run_id, 'review_snapshot_version': review_version,
    })
    risk_job = complete_job(migrated_client, test_settings, queued.json())
    risk_id = risk_job['result']['risk_run_id']
    test_settings.decision_provider = 'openai_compatible'
    test_settings.openai_base_url = 'https://api.deepseek.com'
    test_settings.openai_api_key = 'unit-secret'
    test_settings.openai_model = 'deepseek-flash'
    with patch('app.adapters.decision.openai_compatible.generate') as generate:
        generate.return_value = DecisionContent(title='AI巡查建议', priorities=[PriorityItem(
            level='P3', heading='现场核查', body='根据检测结果安排现场核查。', evidence_refs=[],
        )], disclaimer='专业人员确认')
        queued = migrated_client.post(f'/api/v1/tasks/{task_id}/decisions', json={
            'risk_run_id': risk_id, 'provider': 'openai_compatible', 'context': '用户补充降雨',
        })
        assert queued.status_code == 202, queued.text
        job = complete_job(migrated_client, test_settings, queued.json())
        assert generate.call_args.args[2] == '用户补充降雨'
        evidence = generate.call_args.args[1]
        assert evidence['risk_run_id'] == risk_id and 'hotspots' in evidence
    decision = migrated_client.get(f'/api/v1/tasks/{task_id}/decisions').json()['items'][0]
    assert decision['id'] == job['result']['decision_version_id']
    assert decision['provider'] == {'name': 'openai_compatible', 'model': 'deepseek-flash'}
    assert decision['priorities'][0]['heading'] == '现场核查'
    assert 'unit-secret' not in json.dumps(decision)
    version = migrated_client.get('/api/v1/version').json()
    assert version['providers']['decision']['display_name'] == 'DeepSeek'
    assert 'unit-secret' not in json.dumps(version)
    from app.adapters.decision.openai_compatible import DecisionProviderError
    with patch('app.adapters.decision.openai_compatible.generate', side_effect=DecisionProviderError('DECISION_API_ERROR', '余额不足')):
        failed = migrated_client.post(f'/api/v1/tasks/{task_id}/decisions', json={
            'risk_run_id': risk_id, 'provider': 'openai_compatible', 'context': '再次生成',
        })
        assert failed.status_code == 202
        assert run_worker(once=True, settings=test_settings) == 0
        failed_job=migrated_client.get(f"/api/v1/jobs/{failed.json()['job']['id']}").json()['job']
        assert failed_job['status'] == 'failed'
        assert failed_job['error']['code'] == 'DECISION_API_ERROR'
    preserved = migrated_client.get(f'/api/v1/tasks/{task_id}/decisions').json()['items'][0]
    assert preserved['id'] == decision['id'] and preserved['status'] == 'current'


def test_unconfigured_ai_is_rejected_without_calling_provider(test_settings, migrated_client):
    task_id, run_id, review_version = prepare_reviewed_inference(test_settings, migrated_client)
    queued = migrated_client.post(f'/api/v1/tasks/{task_id}/risk-runs', json={
        'inference_run_id': run_id, 'review_snapshot_version': review_version,
    })
    risk_id = complete_job(migrated_client, test_settings, queued.json())['result']['risk_run_id']
    response = migrated_client.post(f'/api/v1/tasks/{task_id}/decisions', json={
        'risk_run_id': risk_id, 'provider': 'openai_compatible',
    })
    assert response.status_code == 503
    assert response.json()['code'] == 'DECISION_PROVIDER_NOT_CONFIGURED'
