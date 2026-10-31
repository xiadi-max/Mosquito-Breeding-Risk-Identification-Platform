import test from 'node:test';
import assert from 'node:assert/strict';
import { loadAcceptedDetections, detectionOverlayData } from '../../../api-integration.js';

const detection = (id, overrides = {}) => ({
  id, effective_state: 'accepted', category: {id: 1, name: 'potted_plant'}, confidence: .79,
  mosaic_box: {x1: 100, y1: 200, x2: 300, y2: 400}, ...overrides,
});

test('boxes use stitched coordinates, with category and confidence labels', () => {
  const [box] = detectionOverlayData([detection('a')], 1800, 1140);
  assert.deepEqual([box.x, box.y, box.width, box.height], [50, 100, 100, 100]);
  assert.equal(box.label, 'potted_plant 0.79');
});

test('pending, excluded and invalid boxes are not rendered', () => {
  assert.deepEqual(detectionOverlayData([
    detection('pending', {effective_state:'pending'}),
    detection('rejected', {effective_state:'rejected'}),
    detection('invalid', {mosaic_box:{x1:NaN, y1:0, x2:1, y2:1}}),
    detection('outside', {mosaic_box:{x1:2000, y1:0, x2:2200, y2:10}}),
  ], 1800, 1140), []);
  assert.deepEqual(detectionOverlayData([detection('a')], 0, 0), []);
});

test('edge boxes are clipped and class colors stay stable across result order', () => {
  const a=detection('a', {mosaic_box:{x1:-10, y1:-20, x2:1900, y2:1200}});
  const b=detection('b', {category:{id:2, name:'container'}});
  const boxes=detectionOverlayData([a,b],1800,1140);
  assert.deepEqual([boxes[0].x,boxes[0].y,boxes[0].width,boxes[0].height],[0,0,900,570]);
  assert.equal(boxes[0].color,detectionOverlayData([b,a],1800,1140)[1].color);
});

test('loads accepted results across all pages of the same inference run', async () => {
  const paths=[];
  const api={get:async path=>{
    paths.push(path);
    return {run_id:'run', run_status:'current', items:path.includes('cursor=')?[detection('b')]:[detection('a')], next_cursor:paths.length===1?'next/page':null};
  }};
  assert.deepEqual((await loadAcceptedDetections(api,'task','run')).map(item=>item.id),['a','b']);
  assert.ok(paths.every(path=>path.includes('status=accepted')&&path.includes('run_id=run')));
  assert.ok(paths[1].includes('cursor=next%2Fpage'));
});

test('rejects stale inference results', async () => {
  const api={get:async()=>({run_id:'other',run_status:'stale',items:[]})};
  await assert.rejects(loadAcceptedDetections(api,'task','run'),/检测批次已变化/);
});
