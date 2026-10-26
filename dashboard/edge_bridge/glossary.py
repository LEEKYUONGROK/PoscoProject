"""Small local glossary retrieval and validation; never rewrites source/report text."""
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import re

PATH = Path(__file__).with_name('technical_glossary.json')
RULES = '''제조·품질관리 기술 용어는 technical_glossary의 프로젝트 표준 한국어를 사용한다.
동일 개념에는 동일 표현을 쓰되, JSON 키·API 필드명·코드 식별자·센서/로그 ID·수치·단위는 번역하거나 변환하지 않는다.
측정 사실과 추정 원인을 구분하고 미확인 원인·임계값·신뢰도 점수·오탐·미탐을 만들어내지 않는다.
용어 정의는 사건의 증거가 아니다. 해당 개념이 필요할 때만 사용하며 모든 용어를 억지로 본문에 넣지 않는다.
다의어는 제시한 문맥별 표현을 따르고, 문맥이 모호하면 영문을 유지하여 검토 대상으로 남긴다.
불필요한 영어·직역투를 줄이고 객관적인 한국어 기술 문체로 작성한다.'''


@lru_cache(maxsize=1)
def load():
    raw = PATH.read_bytes()
    data = json.loads(raw)
    names = [e['english'] for e in data['entries']]
    if len(names) != len(set(names)):
        raise ValueError('duplicate glossary English term')
    for entry in data['entries']:
        if not all(entry.get(k) for k in ('english', 'korean', 'definition', 'domains', 'translation_notes')):
            raise ValueError('incomplete glossary entry')
    return data, hashlib.sha256(raw).hexdigest()


def prose(text):
    """Exclude quoted code/identifiers, not ordinary English event descriptions."""
    text = re.sub(r'`[^`]*`|"(?:[^"\\]|\\.)*"\s*(?=:)', ' ', text)
    text = re.sub(r'\b[A-Za-z_][A-Za-z0-9_]*(?=\s*(?:필드|키|식별자|속성))', ' ', text)
    text = re.sub(r'\b[A-Za-z_][A-Za-z0-9_]*\s*=\s*(?:\{[A-Za-z_0-9]+\}|[^\s,;]+)', ' ', text)
    return re.sub(r'\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b', ' ', text)


def contains(text, phrase):
    pattern = re.escape(phrase).replace(r'\ ', r'[\s-]+')
    return bool(re.search(r'(?<![A-Za-z0-9_])' + pattern + r'(?![A-Za-z0-9_])', text, re.I))


def translation(entry, text):
    choices = entry.get('contextual_translations')
    if not choices:
        return entry['korean'], False
    contexts = []
    for kind, pattern in [('software', r'소프트웨어|통신|파싱|프로그램|(?<![A-Za-z0-9_])(?:software|parsing|network|API)(?![A-Za-z0-9_])'),
                          ('mechanical', r'기계|베어링|모터|(?<![A-Za-z0-9_])(?:mechanical|bearing|motor)(?![A-Za-z0-9_])'),
                          ('functional', r'기능\s*(?:상실|수행\s*불능)|(?<![A-Za-z0-9_])(?:functional|loss of function)(?![A-Za-z0-9_])')]:
        if kind in choices and re.search(pattern, text, re.I):
            contexts.append(kind)
    if len(contexts) != 1:
        return entry['english'], True
    return choices[contexts[0]], False


def select(text='', facts=None, max_entries=8):
    data, digest = load()
    clean = prose(text)
    facts = facts or {}
    fields = {f.get('field') for f in facts.get('facts', [])}
    candidates = []
    for index, entry in enumerate(data['entries']):
        terms = [entry['english'], *entry.get('aliases', []), *entry['korean'].split(' / ')]
        explicit = any(contains(clean, term) for term in terms)
        identifier = entry['english'].lower().replace(' ', '_')
        explicit = explicit or bool(re.search(
            r'(?<![A-Za-z0-9_])' + re.escape(identifier) + r'(?:[\"\x27]\s*:|\s*=)', text, re.I))
        field_match = bool(set(entry.get('fields', [])) & fields)
        if entry['english'] == 'Fault':
            field_match = any(f.get('field') == 'dht_ok' and f['kind'] == 'signal' for f in facts.get('facts', []))
        concept = ((entry['english'] == 'Threshold' and any(c['id'] == 'C_THRESHOLD' for c in facts.get('checks', [])))
                   or (entry['english'] == 'Evidence' and bool(facts.get('facts')))
                   or (entry['english'] == 'Root Cause' and bool(facts.get('hypotheses')))
                   or (entry['english'] == 'Data Integrity' and any(h['id'] == 'H_DATA' for h in facts.get('hypotheses', []))))
        if not (explicit or field_match or concept):
            continue
        preferred, review = translation(entry, clean)
        candidates.append((int(explicit), int(field_match), -index, {
            'english': entry['english'], 'korean': preferred, 'definition': entry['definition'],
            'note': entry['translation_notes'], 'review_required': review}))
    candidates.sort(key=lambda x: x[:3], reverse=True)
    entries = [c[3] for c in candidates[:max_entries]]
    return {'version': data['version'], 'sha256': digest, 'entries': entries,
            'matched_count': len(candidates), 'omitted_count': max(0, len(candidates) - len(entries))}


def prompt_payload(context):
    # Definitions/domains/aliases stay local; context notes carry the needed distinctions.
    return [{'en': e['english'], 'ko': e['korean'], 'note': e['note']}
            for e in context['entries']]


def validate_report(text, context=None):
    data, digest = load()
    clean = prose(text)
    selected = {e['english']: e for e in (context or {}).get('entries', [])}
    errors, reviews, standard = [], [], []
    for entry in data['entries']:
        name = entry['english']
        resolved = selected.get(name)
        preferred, ambiguous = translation(entry, clean) if resolved is None else (resolved['korean'], resolved['review_required'])
        if contains(clean, name):
            issue = {'term': name, 'preferred': preferred, 'kind': 'untranslated_english'}
            (reviews if ambiguous else errors).append(issue)
        for alias in entry.get('aliases', []):
            if contains(clean, alias):
                issue = {'term': name, 'found': alias, 'preferred': preferred, 'kind': 'nonstandard_project_term'}
                (reviews if ambiguous else errors).append(issue)
        if not ambiguous and contains(clean, preferred):
            standard.append(name)
        if entry.get('contextual_translations') and re.search(r'오류|고장|기능 상실', clean):
            # Bare Korean words are not enough to infer which English concept was intended.
            if resolved and ambiguous:
                reviews.append({'term': name, 'kind': 'ambiguous_context', 'action': '원문 유지 또는 사람 검토'})
            elif resolved:
                other = set(entry['contextual_translations'].values()) - {preferred}
                if any(word in clean for word in other):
                    reviews.append({'term': name, 'kind': 'context_sensitive_alternative',
                                    'preferred': preferred, 'action': '다른 개념을 뜻할 수 있어 자동 치환하지 않음'})
    allowed = {'DHT', 'MQ', 'ID', 'API', 'JSON', 'TCP', 'CRC', 'MQTT', 'Protobuf', 'UTF', 'Qwen', 'C', 'F'}
    # Unknown proper names/identifiers are review items, never auto-translated.
    covered = clean
    for e in data['entries']:
        covered = re.sub(re.escape(e['english']), ' ', covered, flags=re.I)
    unknown = sorted({w for w in re.findall(r'\b[A-Za-z][A-Za-z0-9]*\b', covered)
                      if w not in allowed and not re.fullmatch(r'MQ[27]', w, re.I)})
    if unknown:
        reviews.append({'kind': 'unrecognized_english_or_identifier', 'tokens': unknown})
    return {'version': data['version'], 'sha256': digest, 'errors': errors, 'review_items': reviews,
            'standard_terms_used': sorted(set(standard)),
            'status': 'rejected' if errors else ('review_required' if reviews else 'passed'),
            'automatic_replacements': 0}
