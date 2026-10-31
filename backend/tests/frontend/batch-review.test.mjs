import test from 'node:test';
import assert from 'node:assert/strict';
import { applyPendingReviews } from '../../../api-integration.js';

const pending = (id, version = 1) => ({ id, version, effective_state: 'pending' });

for (const action of ['accept', 'reject']) {
  test(`${action} handles every page and preserves already reviewed candidates`, async () => {
    const calls = [], progress = [];
    const api = {
      get: async path => path.includes('cursor=')
        ? { run_id: 'run', items: [pending('b', 3)], next_cursor: null }
        : { run_id: 'run', items: [pending('a'), { id: 'done', effective_state: 'accepted' }], next_cursor: 'next/page' },
      patch: async (path, body) => calls.push([path, body]),
    };
    assert.equal(await applyPendingReviews(api, 'task', action, (...args) => progress.push(args)), 2);
    assert.deepEqual(calls, [
      ['/tasks/task/reviews/a', { action, expected_version: 1 }],
      ['/tasks/task/reviews/b', { action, expected_version: 3 }],
    ]);
    assert.deepEqual(progress, [[1, 2], [2, 2]]);
  });
}

test('no pending candidates makes no changes', async () => {
  const api = {
    get: async () => ({ run_id: 'run', items: [], next_cursor: null }),
    patch: async () => assert.fail('Unexpected review'),
  };
  assert.equal(await applyPendingReviews(api, 'task', 'accept'), 0);
});

test('version conflict stops further changes and reports partial completion', async () => {
  const visited = [];
  const api = {
    get: async () => ({ run_id: 'run', items: [pending('a'), pending('b'), pending('c')], next_cursor: null }),
    patch: async path => {
      visited.push(path);
      if (path.endsWith('/b')) throw new Error('版本冲突');
    },
  };
  await assert.rejects(applyPendingReviews(api, 'task', 'reject'), /已处理 1\/3 项；版本冲突/);
  assert.equal(visited.length, 2);
});

test('changing inference run between pages prevents submission', async () => {
  let count = 0;
  const api = {
    get: async () => ({ run_id: `run-${++count}`, items: [pending('a')], next_cursor: count === 1 ? 'next' : null }),
    patch: async () => assert.fail('Unexpected review'),
  };
  await assert.rejects(applyPendingReviews(api, 'task', 'accept'), /推理批次已变化/);
});
