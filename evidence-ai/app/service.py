import hashlib
from .schemas import (AnalysisContext, AnalysisResponse, DocumentSummary,
                      ScoreSuggestion, Ruleset)
from .rules import evaluate, is_recognized_certificate

MESSAGE_LABELS = {
    'DUPLICATE_DOCUMENT': '이미 제출한 파일입니다.',
    'RECIPIENT_MISMATCH': '문서의 이름과 학생 이름이 일치하지 않습니다.',
    'LOW_CONFIDENCE': '내용을 확실하게 읽지 못해 점수 제안을 보류했습니다.',
    'RECOGNIZED_NEEDS_REVIEW': '기준에 포함된 자격증입니다. 점수는 추가 확인이 필요합니다.',
    'NO_MATCHING_RULE': '이 문서에 해당하는 평가 기준이 없습니다.',
    'DOCUMENT_TYPE_MISMATCH': '문서 종류가 평가 기준과 일치하지 않습니다.',
    'TITLE_MISMATCH': '문서 명칭이 평가 기준과 일치하지 않습니다.',
    'FUTURE_DATE': '발급일이 미래로 표시되어 있습니다. 원본을 확인하세요.',
    'INVALID_DATE': '발급일을 확인할 수 없습니다.',
    'MISSING_SOURCE_QUOTE': '점수 제안의 근거를 확인하지 못했습니다.',
    'EXAMPLE_RULE': '제안 점수는 실제 학교 기준이 아닌 개발용 예시입니다.',
    'REQUIRED_CONDITION_MISSING': '평가 기준의 필수 조건을 문서에서 확인하지 못했습니다.',
    'ISSUER_MISMATCH': '평가 기준에서 지정한 발급기관인지 확인이 필요합니다.',
    'CHECK_ENROLLMENT': '재학 기간 중 취득한 자격증인지 확인하세요.',
    'CHECK_CERTIFICATE_CAP': '전공 관련 자격증의 누적 상한 30점과 기존 인정 내역을 확인하세요.',
    'CHECK_INTERNAL_ASSESSMENT': '외부평가 취득 점수만 제안합니다. 내부평가 최대 6점은 별도입니다.',
    'CHECK_HRD_CATEGORY': '한국산업인력공단 시행종목의 정보통신·전기전자·디자인 분야에 해당하는지 확인하세요.',
    'MOCK_RESULT': '모의 분석 결과입니다.',
    'MOCK_NO_OCR': '모의 모드에서는 파일 내용을 읽지 않습니다.',
}
FIELD_LABELS = {'title': '문서 명칭', 'recipient_name': '이름', 'issuer': '발급기관',
                'issued_date': '발급일', 'award': '수상내역'}


def public_messages(flags: list[str]) -> list[str]:
    messages = []
    unknown = False
    for flag in flags:
        code, _, detail = flag.partition(':')
        if code == 'MISSING_FIELD':
            message = f"{FIELD_LABELS.get(detail.strip(), '필수 정보')} 확인이 필요합니다."
        elif code in MESSAGE_LABELS:
            message = MESSAGE_LABELS[code]
        else:
            unknown = True
            continue
        if message not in messages:
            messages.append(message)
    # Do not echo arbitrary model comments: they can contain identifiers or
    # duplicate a no-match explanation. Preserve uncertainty as one plain notice.
    if unknown and not any(f.partition(':')[0] in {'NO_MATCHING_RULE', 'RECOGNIZED_NEEDS_REVIEW', 'LOW_CONFIDENCE'} for f in flags):
        messages.append('추출 정보 중 불명확한 내용이 있어 원본 확인이 필요합니다.')
    return messages


class AnalysisService:
    def __init__(self, provider, ruleset: Ruleset):
        self.provider, self.ruleset = provider, ruleset

    async def analyze(self, context: AnalysisContext, *, text: str | None = None,
                      data: bytes | None = None, mime: str | None = None) -> AnalysisResponse:
        document_hash = hashlib.sha256(data if data is not None else (text or '').encode('utf-8')).hexdigest()
        extraction = await self.provider.extract(text=text, data=data, mime=mime, ruleset=self.ruleset)
        # Plain-text input is already the source of truth; do not validate
        # quotes against a model's paraphrase or accidentally copied rule text.
        if text is not None:
            extraction = extraction.model_copy(update={'extracted_text': text})
        recommendation, flags = evaluate(extraction, context, document_hash, self.ruleset)
        recognized = is_recognized_certificate(extraction, self.ruleset)
        if recognized:
            flags = ['RECOGNIZED_NEEDS_REVIEW' if flag.partition(':')[0] == 'NO_MATCHING_RULE' else flag
                     for flag in flags]
        return AnalysisResponse(
            is_recognized_certificate=recognized,
            document=DocumentSummary(**extraction.model_dump(include={
                'document_type', 'title', 'recipient_name', 'issuer', 'issued_date', 'award'})),
            recommendation=(ScoreSuggestion(score_type=recommendation.score_type,
                                            item=recommendation.item,
                                            points=recommendation.proposed_points,
                                            example_only=recommendation.example_only)
                            if recommendation else None),
            messages=public_messages(flags),
        )
