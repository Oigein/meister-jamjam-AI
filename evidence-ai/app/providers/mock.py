import re
from ..rules import keyword_matches, certificate_title_matches
from ..schemas import DocumentType, Extraction, Ruleset

class MockProvider:
    name = 'mock'

    async def extract(self, *, text: str | None, data: bytes | None, mime: str | None,
                      ruleset: Ruleset) -> Extraction:
        if text is None:
            return Extraction(document_type=DocumentType.UNKNOWN, title=None, recipient_name=None,
                              issuer=None, issued_date=None, award=None, extracted_text='',
                              candidate_rule_id=None, evidence_quote=None, confidence=0,
                              uncertainties=['MOCK_NO_OCR: 모의 모드는 파일의 글자를 판독하지 않습니다. 텍스트 예제로 테스트하세요.'])
        def field(label):
            match = re.search(rf'^{label}\s*[:：]\s*(.+)$', text, re.MULTILINE)
            return match.group(1).strip() if match else None
        title = field('문서명')
        rule = next((r for r in ruleset.rules if title and any(keyword_matches(k, title) for k in r.title_keywords)), None)
        recognized = certificate_title_matches(title or '', ruleset)
        return Extraction(document_type=rule.document_type if rule else (DocumentType.CERTIFICATE if recognized else DocumentType.UNKNOWN),
                          title=title, recipient_name=field('성명'), issuer=field('발급기관'),
                          issued_date=field('발급일'), award=field('수상내역'), extracted_text=text,
                          candidate_rule_id=rule.id if rule else None, evidence_quote=title,
                          confidence=0.95 if recognized else 0.2,
                          uncertainties=['MOCK_RESULT: 정해진 필드를 읽는 테스트 파서이며 실제 AI 분석이 아닙니다.'])
