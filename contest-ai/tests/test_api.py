import asyncio
import json
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import KST, Settings, create_app
from app.models import Choices
from app.provider import MockProvider

NOW=datetime(2026,10,30,12,tzinfo=KST)
STUDENT={'Authorization':'Bearer student-test'}
ADMIN={'Authorization':'Bearer admin-test'}

class RecordingProvider(MockProvider):
    def __init__(self):
        self.contexts=[]
        self.error=False

    async def recommend(self, context):
        self.contexts.append(context)
        if self.error:
            raise TimeoutError()
        result=await super().recommend(context)
        return Choices.model_validate({'recommendations':[r.model_dump() | {'expectedScore':9999,'deadline':'2099-01-01'} for r in result.recommendations]+[
            {'contestId':99999,'recommendType':'VALUE','reason':'없는 대회','teamTip':''}]})

    async def chat(self, context):
        self.contexts.append(context)
        if self.error:
            raise TimeoutError()
        return await super().chat(context)

    async def stream_chat(self, context):
        yield '첫 부분'
        if self.error:
            raise TimeoutError()
        yield '두 번째 부분'

@pytest.fixture
def setup(tmp_path):
    engine=RecordingProvider()
    settings=Settings(_env_file=None,database_path=str(tmp_path/'test.db'),seed_demo_data=True,
                      dev_student_token='student-test',dev_admin_token='admin-test')
    async def resolver(request):
        token=request.headers.get('authorization','')
        return {'Bearer student-test':{'id':'demo-student','role':'STUDENT'},
                'Bearer admin-test':{'id':'admin','role':'ADMIN'},
                'Bearer other-test':{'id':'other','role':'STUDENT'},
                'Bearer teacher-test':{'id':'teacher','role':'TEACHER'}}.get(token)
    app=create_app(settings,engine,session_resolver=resolver,now=lambda:NOW)
    with app.state.store.connect() as db:
        db.execute("INSERT INTO students SELECT 'other', grade, scores FROM students WHERE user_id='demo-student'")
    with TestClient(app) as client:
        yield client,app,engine


def test_server_authority_sorting_exam_filter(setup):
    client,app,engine=setup
    response=client.post('/api/contest-recommendations',json={},headers=STUDENT)
    assert response.status_code==200
    body=response.json()
    assert body['studentContext']=={'grade':2,'totalScore':320,'weakestArea':'FOREIGN_LANGUAGE'}
    assert body['generatedAt'].endswith('+09:00')
    rows=body['recommendations']
    assert [r['contestId'] for r in rows]==[43,42]
    assert rows[1]['expectedScore']==5 and rows[1]['dDay']==16
    assert rows[1]['deadline'].startswith('2026-11-15')
    assert engine.contexts[0]['student']['scores']['MAJOR_SKILL']==110
    assert engine.contexts[0]['guidelines']['version']==1


def test_exam_warnings_and_available_until(setup):
    c,app,p=setup
    body=c.post('/api/contest-recommendations',json={'includeExamPeriod':True},headers=STUDENT).json()
    assert next(r for r in body['recommendations'] if r['contestId']==44)['scheduleWarnings'][0]['type']=='EXAM'
    body=c.post('/api/contest-recommendations',json={'availableUntil':'2026-11-15'},headers=STUDENT).json()
    assert [r['contestId'] for r in body['recommendations']]==[42]

@pytest.mark.parametrize('offset,excluded',[(33,True),(32,False),(50,True),(51,False)])
def test_exam_buffer_inclusive_boundaries(setup,offset,excluded):
    from datetime import timedelta
    c,app,p=setup
    with app.state.store.connect() as db:
        db.execute('UPDATE contests SET finish_at=? WHERE contest_id=42',((NOW.date()+timedelta(days=offset)).isoformat()+'T18:00:00+09:00',))
    rows=c.post('/api/contest-recommendations',json={},headers=STUDENT).json()['recommendations']
    assert (42 not in [r['contestId'] for r in rows])==excluded


def test_empty_no_model_call_and_unverified_expired(setup):
    c,app,p=setup
    with app.state.store.connect() as db:
        db.execute('UPDATE contests SET is_verified=0 WHERE contest_id=42')
        db.execute("UPDATE contests SET finish_at='2026-10-29T18:00:00+09:00' WHERE contest_id=43")
    body=c.post('/api/contest-recommendations',json={},headers=STUDENT).json()
    assert body['recommendations']==[] and body['message']
    assert not p.contexts

@pytest.mark.parametrize('payload',[{'studentContext':{'grade':3}},{'techStack':['a']*11},{'techStack':['a'*31]},
    {'goal':{'targetScore':0}},{'goal':{'description':'a'*101}},{'major':'HACK'},{'types':[]},{'availableUntil':'bad'}])
def test_validation_and_score_injection(setup,payload):
    assert setup[0].post('/api/contest-recommendations',json=payload,headers=STUDENT).status_code==400


def test_auth_and_roles(setup):
    c,app,p=setup
    assert c.post('/api/contest-recommendations',json={}).status_code==401
    assert c.post('/api/contest-recommendations',json={},headers={'X-Role':'STUDENT'}).status_code==401
    assert c.post('/api/contest-recommendations',json={},headers=ADMIN).status_code==403
    assert c.get('/api/admin/recommendation-guidelines',headers=STUDENT).status_code==403
    assert c.get('/api/academic-schedules?from=2026-10-01&to=2027-01-01',headers={'Authorization':'Bearer teacher-test'}).status_code==200


def test_guideline_conflict_and_immediate_effect(setup):
    c,app,p=setup
    old=c.get('/api/admin/recommendation-guidelines',headers=ADMIN).json()
    new=old | {'examBufferDays':0,'promptGuideline':'새 기준'}
    assert c.put('/api/admin/recommendation-guidelines',json=new,headers=ADMIN).json()['version']==2
    assert c.put('/api/admin/recommendation-guidelines',json=new,headers=ADMIN).status_code==409
    c.post('/api/contest-recommendations',json={},headers=STUDENT)
    assert p.contexts[-1]['guidelines']['promptGuideline']=='새 기준'


def test_schedule_overlap_and_order(setup):
    c,app,p=setup
    assert len(c.get('/api/academic-schedules?from=2026-12-10&to=2026-12-11',headers=STUDENT).json()['items'])==1
    assert c.get('/api/academic-schedules?from=2026-12-11&to=2026-12-10',headers=STUDENT).status_code==400


def test_rate_limit_minute_day_and_upstream(setup):
    c,app,p=setup
    p.error=True
    assert c.post('/api/contest-recommendations',json={},headers=STUDENT).status_code==502
    for _ in range(9):
        c.post('/api/contest-recommendations',json={'availableUntil':'2020-01-01'},headers=STUDENT)
    response=c.post('/api/contest-recommendations',json={},headers=STUDENT)
    assert response.status_code==429 and int(response.headers['retry-after'])>0
    app.state.runtime.minute.clear()
    app.state.runtime.daily['demo-student']=(NOW.date(),100)
    assert c.post('/api/contest-recommendations',json={},headers=STUDENT).status_code==429


def test_chat_history_owner_expiration_and_unknown_contest(setup):
    c,app,p=setup
    r=c.post('/api/contest-recommendations/chat',json={'contestId':42,'message':'준비 방법'},headers=STUDENT)
    assert r.status_code==200
    key=r.json()['conversationId']
    assert c.post('/api/contest-recommendations/chat',json={'conversationId':key,'message':'다음 단계'},headers=STUDENT).status_code==200
    assert len(p.contexts[-1]['history'])==2
    assert c.post('/api/contest-recommendations/chat',json={'conversationId':key,'message':'훔치기'},headers={'Authorization':'Bearer other-test'}).status_code==404
    app.state.runtime.conversations[key].expires=time.monotonic()-1
    assert c.post('/api/contest-recommendations/chat',json={'conversationId':key,'message':'만료'},headers=STUDENT).status_code==404
    assert c.post('/api/contest-recommendations/chat',json={'contestId':999,'message':'없는 대회'},headers=STUDENT).status_code==404


def test_streaming_success_and_failed_partial_not_saved(setup):
    c,app,p=setup
    headers=STUDENT | {'Accept':'text/event-stream'}
    r=c.post('/api/contest-recommendations/chat',json={'message':'질문'},headers=headers)
    assert r.status_code==200 and r.text.count('event: delta')==2 and 'event: done' in r.text
    before=len(app.state.runtime.conversations)
    p.error=True
    r=c.post('/api/contest-recommendations/chat',json={'message':'실패'},headers=headers)
    assert 'event: error' in r.text and 'event: done' not in r.text
    assert len(app.state.runtime.conversations)==before


def test_sql_constraints(setup):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError), setup[1].state.store.connect() as db:
        db.execute('UPDATE contests SET prep_hours=0')


def test_rate_minute_window_survives_kst_midnight(setup):
    from datetime import timedelta
    from app.main import APIError
    runtime=setup[1].state.runtime
    for _ in range(10):
        runtime.limit('night-user',NOW)
    with pytest.raises(APIError) as error:
        runtime.limit('night-user',NOW+timedelta(days=1))
    assert error.value.status==429
