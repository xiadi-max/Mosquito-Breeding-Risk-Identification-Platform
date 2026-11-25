import test from 'node:test';
import assert from 'node:assert/strict';
import { advanceUpload, resumeStep, validateUploadFiles } from '../../../api-integration.js';

test('one prestitched image goes directly to ROI after server import', async () => {
  const events = [], mosaic = {mosaic_artifact_id:'mosaic'};
  await advanceUpload({mode:'imported', images:[{id:'image'}],
    createImported:async()=>{events.push('import');return mosaic;},
    displayMosaic:async value=>{assert.equal(value,mosaic);events.push('display');},
    navigate:step=>events.push(step)});
  assert.deepEqual(events,['import','display',3]);
});

test('a saved mosaic is reused when returning to upload', async () => {
  const events = [], mosaic = {mosaic_artifact_id:'saved'};
  await advanceUpload({mode:'imported',images:[{}],existingMosaic:mosaic,
    createImported:async()=>assert.fail('Must not import again'),
    displayMosaic:async value=>assert.equal(value,mosaic),navigate:step=>events.push(step)});
  assert.deepEqual(events,[3]);
});

test('import failure never advances to stitching or ROI', async () => {
  await assert.rejects(advanceUpload({mode:'imported',images:[{}],
    createImported:async()=>{throw Error('Upload unavailable');},
    displayMosaic:async()=>assert.fail(),navigate:()=>assert.fail()}),/Upload unavailable/);
});

test('raw photos retain the stitching workflow', async () => {
  const steps=[];
  await advanceUpload({mode:'raw',images:[{},{}],navigate:step=>steps.push(step),
    createImported:async()=>assert.fail(),displayMosaic:async()=>assert.fail()});
  assert.deepEqual(steps,[2]);
});

test('image counts are validated before creating jobs or navigating', async () => {
  for(const [mode,images] of [['raw',[{}]],['imported',[]],['imported',[{},{}]]]) {
    await assert.rejects(advanceUpload({mode,images,navigate:()=>assert.fail(),
      createImported:async()=>assert.fail(),displayMosaic:async()=>assert.fail()}));
  }
  assert.equal(resumeStep({current_stage:'image_ingest',image_count:1},'imported'),1);
  assert.equal(resumeStep({current_stage:'mosaic',image_count:1},'imported'),3);
});

test('upload accepts 200 images and a 200 MB file without truncation', () => {
  const files=Array.from({length:200},(_,i)=>({name:`${i}.jpg`,size:1024}));
  assert.equal(validateUploadFiles(files,'raw').length,200);
  assert.equal(validateUploadFiles([{name:'large.jpg',size:200*1024**2}],'imported').length,1);
  assert.throws(()=>validateUploadFiles([...files,files[0]],'raw'),/200 张/);
  assert.throws(()=>validateUploadFiles([{name:'large.jpg',size:200*1024**2+1}],'imported'),/200 MB/);
  assert.throws(()=>validateUploadFiles(Array.from({length:52},()=>({name:'large.jpg',size:200*1024**2})),'raw'),/10 GB/);
});
