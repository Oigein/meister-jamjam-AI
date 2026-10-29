import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.settings import Settings, ROOT
from app.rules import keyword_matches

@pytest.fixture
def school_client():
    with TestClient(create_app(Settings(_env_file=None,ai_provider='mock'))) as client:
        yield client


def request_for(title,issuer='한국산업인력공단',extra=''):
    return {'text':f'문서명: {title}\n성명: 가상학생\n발급기관: {issuer}\n발급일: 2026-07-26\n{extra}', 'expected_name':'가상학생'}


def test_source_metadata_and_real_rules(school_client):
    rules=school_client.get('/api/v1/rules').json()
    assert rules['student_grade']==2
    assert rules['academic_year']==2026
    assert rules['version']=='bssm-2026-grade2-v1'
    assert all(not r['example_only'] for r in rules['rules'])
    assert not any(r['id'].startswith('DEMO_') for r in rules['rules'])
    source=json.loads((ROOT/'config/sources/criteria-2026-grade2.source.json').read_text())
    assert len(source['sha256'])==64


def test_industrial_engineer_is_nine_not_fifteen(analyze):
    result=analyze(request_for('정보처리산업기사',extra='취득방식: 과정평가형'))
    assert result['recommendation']['points']==9
    assert result['recommendation']['score_type']=='MAJOR_SKILL'
    assert result['recommendation']['example_only'] is False
    assert any('내부평가 최대 6점은 별도' in m for m in result['messages'])


def test_missing_course_condition_blocks_industrial_engineer(analyze):
    result=analyze(request_for('정보처리산업기사'))
    assert result['recommendation'] is None
    assert any('필수 조건' in m for m in result['messages'])


@pytest.mark.parametrize(('title','points'),[
    ('정보처리기능사',7),('LPIC',10),('CCNA',10),('CCNP',10),('OCPJ',10),('SCJP',10),
    ('Oracle OCA',10),('Oracle OCP',10),('MCITP',10),('컴퓨터활용능력 2급',5),
    ('리눅스마스터 2급',5),('SQLD',5),('AZ-900',5),('워드프로세서',3),
])
def test_official_fixed_scores(analyze,title,points):
    result=analyze(request_for(title))
    assert result['recommendation'] is not None,result
    assert result['recommendation']['points']==points
    assert result['recommendation']['example_only'] is False
    assert result['requires_teacher_approval'] is True
    assert any('누적 상한 30점' in m for m in result['messages'])


def test_functional_certificate_issuer_requires_check(analyze):
    result=analyze(request_for('정보처리기능사',issuer='관련 없는 기관'))
    assert result['recommendation'] is None
    assert any('발급기관' in m for m in result['messages'])


def test_aliases_do_not_overlap():
    assert keyword_matches('OCP','Oracle OCP')
    assert not keyword_matches('OCP','OCPJ')
    assert not keyword_matches('SQLD','NOSQLD')
    assert keyword_matches('AZ-900','AZ - 900 자격증')


@pytest.mark.parametrize('title',['컴퓨터활용능력 1급','리눅스마스터 1급','TOPCIT 3수준','한국사 심화 1급','TOEIC 800점','교내 소프트웨어 챌린지'])
def test_unimplemented_conditional_rules_never_guess(analyze,title):
    result=analyze(request_for(title))
    assert result['recommendation'] is None


def test_duplicate_and_wrong_name_still_block_school_score(analyze):
    data=request_for('정보처리기능사')
    data['known_document_hashes']=[hashlib.sha256(data['text'].encode()).hexdigest()]
    result=analyze(data)
    assert result['recommendation'] is None
    assert '이미 제출한 파일입니다.' in result['messages']


@pytest.mark.parametrize('title',['정보처리기능사','정보처리산업기사','SQLD','TOPCIT 3수준','한국사 심화 1급','한자 4급','TOEIC 800점','HSK 5급','JLPT N2'])
def test_recognized_certificate_includes_unimplemented_scoring(analyze,title):
    result=analyze(request_for(title))
    assert result['is_recognized_certificate'] is True


@pytest.mark.parametrize('title',['기준에 없는 민간자격증','NOSQLD','교내 소프트웨어 챌린지','한국사교육지도사','정보처리기능사지도사','한자지도사'])
def test_unrecognized_certificate(analyze,title):
    assert analyze(request_for(title))['is_recognized_certificate'] is False


def test_catalog_membership_is_not_score_approval(analyze):
    data=request_for('정보처리기능사')
    data['expected_name']='다른학생'
    result=analyze(data)
    assert result['is_recognized_certificate'] is True
    assert result['recommendation'] is None
    assert result['requires_teacher_approval'] is True


def test_noncertificate_with_known_name_is_not_recognized():
    from app.rules import is_recognized_certificate,load_rules
    from app.schemas import Extraction
    e=Extraction(document_type='AWARD',title='SQLD 성적 우수상',recipient_name=None,issuer=None,
        issued_date=None,award='우수상',extracted_text='',candidate_rule_id=None,
        evidence_quote=None,confidence=.9,uncertainties=[])
    assert not is_recognized_certificate(e,load_rules(Settings(_env_file=None).rules_path))
