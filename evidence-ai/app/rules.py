import re
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from .schemas import AnalysisContext, DocumentType, Extraction, Recommendation, Ruleset


def load_rules(path: Path) -> Ruleset:
    ruleset = Ruleset.model_validate_json(path.read_text(encoding='utf-8'))
    ids = [r.id for r in ruleset.rules]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate rule IDs')
    if any(r.points > r.max_points for r in ruleset.rules):
        raise ValueError('Rule points exceed maximum')
    return ruleset


def normalize(value: str) -> str:
    return re.sub(r'\s+', '', value).casefold()


def keyword_matches(keyword: str, value: str) -> bool:
    normalized_keyword = normalize(keyword)
    if re.fullmatch(r'[a-z0-9-]+', normalized_keyword):
        pattern = r'\s*'.join(re.escape(c) for c in normalized_keyword)
        return re.search(r'(?<![a-z0-9])' + pattern + r'(?![a-z0-9])', value.casefold()) is not None
    pattern = r'\s*'.join(re.escape(c) for c in normalized_keyword)
    return re.search(r'(?<![a-z0-9가-힣])' + pattern + r'(?![a-z0-9가-힣])', value.casefold()) is not None


def certificate_title_matches(title: str, ruleset: Ruleset) -> bool:
    keywords = list(ruleset.certificate_keywords)
    for rule in ruleset.rules:
        if rule.document_type in {DocumentType.CERTIFICATE, DocumentType.LANGUAGE}:
            keywords.extend(rule.title_keywords)
    return bool(title) and any(keyword_matches(word, title) for word in keywords)


def is_recognized_certificate(extraction: Extraction, ruleset: Ruleset) -> bool:
    # Catalog membership is separate from eligibility, name checks and points.
    return (extraction.document_type in {DocumentType.CERTIFICATE, DocumentType.LANGUAGE}
            and certificate_title_matches(extraction.title or '', ruleset))


def evaluate(extraction: Extraction, context: AnalysisContext, document_hash: str,
             ruleset: Ruleset) -> tuple[Recommendation | None, list[str]]:
    flags = list(extraction.uncertainties)
    blocked = False
    if document_hash in context.known_document_hashes:
        flags.append('DUPLICATE_DOCUMENT: 동일한 파일 해시가 제출 내역에 있습니다.')
        blocked = True
    if context.expected_name:
        if not extraction.recipient_name or normalize(context.expected_name) != normalize(extraction.recipient_name):
            flags.append('RECIPIENT_MISMATCH: 학생 이름을 원본과 대조하세요.')
            blocked = True
    if extraction.confidence < 0.7:
        flags.append('LOW_CONFIDENCE: 판독이 불확실하여 점수 제안을 보류합니다.')
        blocked = True
    rule = next((r for r in ruleset.rules if r.id == extraction.candidate_rule_id), None)
    if not rule:
        flags.append('NO_MATCHING_RULE: 등록된 평가 기준과 연결하지 못했습니다.')
        return None, flags
    if rule.document_type != extraction.document_type:
        flags.append('DOCUMENT_TYPE_MISMATCH')
        blocked = True
    title = extraction.title or ''
    if not any(keyword_matches(word, title) for word in rule.title_keywords):
        flags.append('TITLE_MISMATCH: 문서 제목이 평가 기준과 일치하지 않습니다.')
        blocked = True
    if rule.required_text_keywords and not all(
            keyword_matches(word, extraction.extracted_text) for word in rule.required_text_keywords):
        flags.append('REQUIRED_CONDITION_MISSING')
        blocked = True
    if rule.issuer_keywords and not any(keyword_matches(word, extraction.issuer or '')
                                        for word in rule.issuer_keywords):
        flags.append('ISSUER_MISMATCH')
        blocked = True
    flags.extend(rule.review_checks)
    for field in rule.required_fields:
        if not getattr(extraction, field):
            flags.append(f'MISSING_FIELD:{field}')
            blocked = True
    if extraction.issued_date:
        try:
            issued = date.fromisoformat(extraction.issued_date)
            if issued > datetime.now(ZoneInfo('Asia/Seoul')).date():
                flags.append('FUTURE_DATE: 발급일을 확인하세요.')
                blocked = True
        except ValueError:
            flags.append('INVALID_DATE: 발급일이 YYYY-MM-DD 형식이 아닙니다.')
            blocked = True
    quote = extraction.evidence_quote
    if not quote or normalize(quote) not in normalize(extraction.extracted_text):
        flags.append('MISSING_SOURCE_QUOTE: 제안 근거를 추출 텍스트에서 확인하지 못했습니다.')
        blocked = True
    if rule.example_only:
        flags.append('EXAMPLE_RULE: 실제 학교 기준이 아닌 예시 배점입니다.')
    if blocked:
        return None, flags
    return Recommendation(rule_id=rule.id, score_type=rule.score_type, item=rule.item,
                          proposed_points=rule.points, max_points=rule.max_points,
                          example_only=rule.example_only,
                          reason=f'등록 기준 {rule.id}와 문서 유형·제목을 대조했습니다. 인용 근거: {quote}'), flags
