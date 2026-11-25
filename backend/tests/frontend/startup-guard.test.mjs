import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html=fs.readFileSync(new URL('../../../index.html',import.meta.url),'utf8');
const guard=html.match(/<script>\s*(if \(window\.APP_CONFIG\.dataMode === 'api'\)[\s\S]*?)<\/script>/)[1];

test('an unavailable API cannot fall through to demo upload handlers',()=>{
  const handlers={},status={textContent:''};
  const window={APP_CONFIG:{dataMode:'api'},addEventListener:()=>{}};
  const document={addEventListener:(type,fn)=>{handlers[type]=fn;},getElementById:()=>status};
  vm.runInNewContext(guard,{window,document});
  for(const type of ['click','change','drop']) {
    let prevented=false,stopped=false;
    handlers[type]({target:{closest:()=>true},preventDefault:()=>{prevented=true;},stopImmediatePropagation:()=>{stopped=true;}});
    assert.equal(prevented,true);assert.equal(stopped,true);
  }
  assert.match(status.textContent,/正在连接服务/);
  window.MOSQUITO_API_READY=true;
  handlers.click({target:{closest:()=>true},preventDefault:()=>assert.fail(),stopImmediatePropagation:()=>assert.fail()});
});
