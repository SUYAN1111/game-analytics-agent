// Protect method attribution: unknown models must not inherit known explanations.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {analysisMethods,methodRegistry,methodMarkdown} from './src/analysis-methods.ts';
const read=async file=>JSON.parse(await fs.readFile(file,'utf8'));
const host=await read('assets/runtime/host.json');
const card=await read('assets/artifacts/tool_runtime/tools0821fc6e3b48e2cf818e585ddd/cards.json');
const freeze=await read('assets/models/m03/m03ef3c03af2f324e0e12d7ecf37/freeze.json');
const cluster=await read('assets/segmentation/model.json');
const rules=await read('assets/association/rules.json');
assert.equal(card.evaluation.model_id,methodRegistry.prediction);
assert.equal(host.definition.model_id,methodRegistry.prediction);
assert.equal(freeze.selected_candidate_id,'lr_c0p1');
assert.equal(card.evaluation.selected_candidate_id,freeze.selected_candidate_id);
assert.equal(card.evaluation.feature_fields.length,19);
assert.equal(cluster.segmentation_model_id,methodRegistry.cluster);
assert.equal(cluster.selected_k,3);
assert.deepEqual(cluster.features,['completed_active_dates_14d','completed_sessions_14d','median_session_minutes_14d','session_45min_share_14d']);
assert.equal(rules.rule_set_id,methodRegistry.rules);assert.equal(rules.rules.length,6);
const metric={id:'metric',kind:'claims',fact:{metric_id:methodRegistry.metric,kind:'metric_rate',scope:{window_hours:72}}};
const prediction={id:'prediction',kind:'claims',fact:{metric_id:methodRegistry.metric,kind:'prediction_probability',scope:{model_id:methodRegistry.prediction,time_mode:'frozen_t0_replay'}}};
const group={id:'group',kind:'cluster_selections',fact:{selection:{scope:{segmentation_model_id:methodRegistry.cluster,snapshot_id:'fit_V3main'}}}};
const rule={id:'rule',kind:'rule_selections',fact:{selection:{scope:{rule_set_id:methodRegistry.rules}}}};
const knowledge={id:'knowledge',kind:'knowledge_selections',fact:{text:'逻辑回归与聚类'}};
assert.deepEqual(analysisMethods([metric,prediction,group,rule,knowledge]).map(m=>m.key),['metric','prediction','cluster','rules','knowledge']);
assert.equal(analysisMethods([prediction,prediction]).length,1);
assert.deepEqual(analysisMethods([]),[]);
for(const e of [metric,prediction,group,rule]){
  const changed=structuredClone(e);
  if(changed.fact.scope){changed.fact.scope={model_id:'unregistered',time_mode:'live',window_hours:24};}
  else changed.fact.selection.scope={};
  assert.equal(analysisMethods([changed])[0].key,'unknown');
}
assert.equal(analysisMethods([{id:'missing',kind:'claims'}])[0].key,'unknown');
const mixed=analysisMethods([metric,{...prediction,fact:{...prediction.fact,scope:{model_id:'other'}}}]);
assert.deepEqual(mixed.map(m=>m.key),['metric','unknown']);
assert.ok(!analysisMethods([knowledge])[0].technical.includes('lr_c0p1'));
const exported=methodMarkdown([prediction]);
assert.ok(exported.includes('不是准确率')&&exported.includes('决策树没有参与这次预测')&&exported.includes('prediction'));
await fs.mkdir('state/ux-stage4',{recursive:true});
await fs.writeFile('state/ux-stage4/method-contract-results.json',JSON.stringify({status:'PASS',checks:['registered model identity and 19 inputs','three clusters and four inputs','six frozen association rules','evidence-driven attribution; mixed/unknown/missing scopes fail closed','knowledge explanation does not pretend to execute algorithms','export retains method limitations']},null,2));
console.log('Method attribution and asset contracts: PASS');
