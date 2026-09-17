"""Allowlisted DTOs from HOST-VERIFIED selections, never raw logs/configuration."""
import copy


def snapshots(answer, host):
    output = []
    for family, label in [('claims', '指标'), ('knowledge_selections', '知识'),
                          ('cluster_selections', '分群'), ('rule_selections', '关联规则')]:
        for fact in answer[family]:
            selection = fact.get('selection', fact.get('claim'))
            dto = {k: copy.deepcopy(fact[k]) for k in ('value', 'unit', 'denominator', 'precision', 'rendered_fact',
                'rendered_quote', 'knowledge_scope', 'verification_status') if k in fact}
            dto['reference'] = copy.deepcopy(selection)
            dto['kind'] = family
            if family == 'claims':
                entry = host.evidence.entries[selection['evidence_id']]
                # EvidenceIndex stores the tool envelope itself.
                dto['metric'] = copy.deepcopy(entry.get('data', {}))
                dto['fact'] = copy.deepcopy(fact['binding'])
            elif family == 'knowledge_selections':
                dto['chunk'] = {k: copy.deepcopy(fact['chunk'][k]) for k in
                    ('chunk_id', 'title', 'section_title', 'text', 'scope', 'source_refs') if k in fact['chunk']}
                dto['fact'] = {'text': fact['raw_quote'], 'scope': fact['knowledge_scope'], 'title': fact['chunk']['title']}
            elif family == 'cluster_selections':
                data = host.clusters.entries[selection['evidence_id']]['data']
                dto['snapshot'] = {k: copy.deepcopy(data[k]) for k in ('snapshot_id', 'S', 'counts', 'groups', 'feature_contract', 'freeze') if k in data}
                dto['fact'] = {k: copy.deepcopy(fact[k]) for k in ('value', 'unit', 'denominator', 'selection', 'precision')}
                dto['fact']['snapshot_at'] = data['S']
            else:
                data = host.rules.entries[selection['evidence_id']]['data']
                dto['rules'] = {k: copy.deepcopy(data[k]) for k in ('rule_set_id', 'evaluation_id', 'versions', 'windows', 'counts', 'rules', 'activity_names') if k in data}
                dto['fact'] = {k: copy.deepcopy(fact[k]) for k in ('value', 'unit', 'denominator', 'selection')}
                rid = selection['scope']['rule_id']
                selected = next((r for r in data['rules'] if r['rule_id'] == rid), None)
                if selected:
                    dto['fact']['antecedent'] = [data['activity_names'][a] for a in selected['antecedent']]
                    dto['fact']['consequent'] = [data['activity_names'][a] for a in selected['consequent']]
                dto['fact']['windows'] = copy.deepcopy(data['windows'])
            dto['limitations'] = '固定模拟数据；引用已核验不代表结论保证正确。相关关系不能证明因果关系。'
            output.append((family, label, dto))
    return output
