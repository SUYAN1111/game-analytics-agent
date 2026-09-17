"""Compose strictly verified Task09 numeric facts with exact current-turn quotations."""
import html
import json
import re
from pathlib import Path
from agent_runtime.claims import HOST_NOTES, render_fact
from agent_runtime.common import HostError, require

NOTES = {**HOST_NOTES,
    "knowledge_not_found":"本轮检索未找到可引用的相关业务资料，暂不能据此解释。",
    "knowledge_unavailable":"本轮知识检索未成功，暂不能提供有来源的业务说明。"}

# One local, identity-bound contract for both prompt checks and host enforcement.
LIMITS = json.loads((Path(__file__).parent/'configs/answer_v1.json').read_text(encoding='utf-8'))['limits']


def completion_summary(result):
    text = result.get('final_response')
    return {'finish_reason':result.get('finish_reason'),
            'response_characters':len(text) if isinstance(text,str) else None,
            'complete_reference_blocks':len(re.findall(r'\{\{(?:claim|knowledge|note):[^{}\n]+\}\}',text))
                if isinstance(text,str) else None}


def require_completed(result):
    reason = result.get('finish_reason')
    if reason in ('max-tokens','length'):
        raise HostError('answer_truncated', '模型达到输出上限，最终答案被截断；不展示为核验答案，不自动续写或重试。'+
                        json.dumps(completion_summary(result),ensure_ascii=False))
    require(reason == 'completed', 'finish_reason', 'model turn did not complete: '+repr(reason))


def literal(value):
    # Encode Markdown/link/template syntax as entities, then display as plain text.
    # Escape original characters once; do not re-escape '#' inside HTML entities.
    return ''.join('&#'+str(ord(c))+';' if c in r'\`*_{}[]()#!|~'
                   else html.escape(c, quote=True) for c in value)


def quote(checked):
    c = checked["chunk"]
    source = '; '.join(r["source_id"]+' '+r["locator"]+' SHA256='+r["sha256"] for r in c["source_refs"])
    raw = c["title"]+'｜'+c["section_title"]+'\n'+c["text"]+'\n来源：'+source
    return {**checked,"raw_quote":raw,"rendered_quote":'\n'.join('> '+literal(line) for line in raw.splitlines()),
            "verification_status":"exact_source_quote_candidate"}


def parse_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "answer_json", "duplicate JSON key")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (ValueError,TypeError) as exc:
        raise HostError("answer_json", "one strict JSON object required, no fences/external text") from exc


def answer_envelope(text):
    """Bound and bind the finite envelope before resolving any evidence.

    This validates structure only; verify_answer still resolves every selection.
    Never extract, repair, truncate or silently deduplicate the model's response.
    """
    require(type(text) is str, 'answer_json', 'answer must be a JSON string')
    require(len(text) <= LIMITS['json_characters'], 'answer_limits', 'final JSON exceeds character limit')
    value = parse_json(text)
    require(type(value) is dict and set(value) == {"answer_markdown","claims","knowledge_selections"},
            "answer", "Task10 requires exactly three answer fields")
    require(type(value["answer_markdown"]) is str and type(value["claims"]) is list and
            type(value["knowledge_selections"]) is list, "answer", "invalid answer field types")
    require(len(value['claims']) <= LIMITS['claims'] and
            len(value['knowledge_selections']) <= LIMITS['knowledge_selections'] and
            len(value['answer_markdown']) <= LIMITS['body_characters'],
            'answer_limits', 'too many selections or answer body too long')
    ids = set()
    for key, fields, prefix, code in (
        ('claims',{'id','evidence_id','field','scope'},'c','selection'),
        ('knowledge_selections',{'id','evidence_id','chunk_id'},'k','knowledge_selection')):
        for item in value[key]:
            require(type(item) is dict and set(item) == fields, code, 'invalid selection fields')
            identifier = item['id']
            require(type(identifier) is str and re.fullmatch(prefix+r'[1-9]\d*',identifier),code,'invalid selection ID')
            require(len(identifier) <= len(str(LIMITS[key]))+1 and int(identifier[1:]) <= LIMITS[key],
                    'answer_limits','selection ID outside finite range')
            require(identifier not in ids, 'answer', 'duplicate selection ID')
            ids.add(identifier)
    blocks = [s.strip() for s in value['answer_markdown'].splitlines() if s.strip()]
    require(len(blocks) <= LIMITS['blocks'], 'answer_limits', 'too many answer blocks')
    used, notes = [], set()
    for block in blocks:
        match = re.fullmatch(r'\{\{(claim|knowledge):([ck][1-9]\d*)\}\}',block)
        note = re.fullmatch(r'\{\{note:([a-z_]+)\}\}',block)
        if match:
            require(match[2].startswith('c' if match[1]=='claim' else 'k') and match[2] in ids,
                    'answer_body','unknown/mismatched block reference')
            used.append(match[2])
        elif note and note[1] in NOTES:
            require(note[1] not in notes, 'answer', 'duplicate note block')
            notes.add(note[1])
        else:
            raise HostError('answer_body','only whole claim/knowledge/note blocks; no independent prose')
    require(len(notes) <= LIMITS['notes'], 'answer_limits', 'too many note blocks')
    require(blocks and len(used)==len(ids) and set(used)==ids,
            'answer','nonempty answer and each selection exactly once required')
    return value


def verify_answer(text, numeric, knowledge, turn_id):
    value = answer_envelope(text)
    facts = [render_fact(numeric.resolve_selection(c),numeric.definition["metric_id"]) for c in value["claims"]]
    quotations = [quote(knowledge.select(k,numeric.session_id,turn_id)) for k in value["knowledge_selections"]]
    fact_keys = [(f['claim']['content_fingerprint'],f['claim']['pointer']) for f in facts]
    require(len(set(fact_keys)) == len(fact_keys), 'answer', 'same verified numeric fact selected more than once')
    chunk_keys = [q['chunk']['chunk_id'] for q in quotations]
    require(len(set(chunk_keys)) == len(chunk_keys), 'answer', 'same knowledge chunk selected more than once')
    mapping = {c["claim"]["id"]:c["rendered_fact"] for c in facts}
    mapping.update({k["selection"]["id"]:k["rendered_quote"] for k in quotations})
    require(len(mapping) == len(facts)+len(quotations), "answer", "duplicate selection ID")
    rendered, used = [], []
    for block in (s.strip() for s in value["answer_markdown"].splitlines() if s.strip()):
        match = re.fullmatch(r"\{\{(claim|knowledge):([ck][1-9]\d*)\}\}",block)
        note = re.fullmatch(r"\{\{note:([a-z_]+)\}\}",block)
        if match:
            require(match[2].startswith('c' if match[1] == 'claim' else 'k') and match[2] in mapping,
                    "answer_body", "unknown/mismatched block reference")
            rendered.append(mapping[match[2]]); used.append(match[2])
        elif note and note[1] in NOTES:
            if note[1].startswith('knowledge_'):
                require(knowledge.note_allowed(note[1],turn_id), "knowledge_note", "note contradicts actual current-turn searches")
            rendered.append(NOTES[note[1]])
        else:
            raise HostError("answer_body", "only whole claim/knowledge/note blocks; no independent prose")
    require(rendered and len(used) == len(mapping) and set(used) == set(mapping),
            "answer", "nonempty answer and each selection exactly once required")
    if NOTES["limitations"] not in rendered: rendered.append(NOTES["limitations"])
    return {"answer_markdown":"\n\n".join(rendered),"claims":facts,"knowledge_selections":quotations,
            "status":"reference_checked_candidate","presentation_contract":"host_bound_knowledge_v1",
            "limitations":"受控检索与原文引用；精确引用不保证选对主题、完整回答、因果或设计审核批准。"}
