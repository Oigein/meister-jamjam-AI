import asyncio
import json
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPBearer
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import ChatRequest, Guidelines, RecommendationRequest
from .provider import GeminiProvider, MockProvider
from .store import Store

KST = ZoneInfo('Asia/Seoul')

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    ai_provider: Literal['mock','gemini'] = 'mock'
    gemini_api_key: str = ''
    gemini_model: str = 'gemini-3.5-flash'
    database_path: str = 'data/contest.sqlite3'
    seed_demo_data: bool = False
    dev_student_token: str = ''
    dev_admin_token: str = ''

class APIError(Exception):
    def __init__(self, status, code, message, headers=None):
        self.status, self.code, self.message, self.headers = status,code,message,headers

@dataclass
class Conversation:
    owner: str
    expires: float
    contest_id: int | None
    history: list = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

class Runtime:
    def __init__(self):
        self.conversations = {}
        self.minute = defaultdict(deque)
        self.daily = {}

    def limit(self, user, now):
        tick = time.monotonic()
        # Bound rate-limit state as identities are supplied by a trusted resolver.
        for key in list(self.daily):
            if self.daily[key][0] != now.date():
                del self.daily[key]
        recent = self.minute[user]
        while recent and recent[0] <= tick-60:
            recent.popleft()
        day, count = self.daily.get(user,(now.date(),0))
        if len(recent) >= 10 or count >= 100:
            retry = max(1,int(60-(tick-recent[0]))+1) if len(recent)>=10 else max(1,int((datetime.combine(now.date()+timedelta(days=1),datetime.min.time(),KST)-now).total_seconds()))
            raise APIError(429,'RATE_LIMITED','요청이 너무 많습니다. 잠시 후 다시 시도하세요.',{'Retry-After':str(retry)})
        recent.append(tick)
        self.daily[user]=(day,count+1)

    def cleanup(self):
        for key in list(self.conversations):
            conv = self.conversations[key]
            if conv.expires <= time.monotonic() and not conv.lock.locked():
                del self.conversations[key]


def local_session(request, settings):
    # Deliberately unavailable unless demo mode is explicitly enabled.
    if not settings.seed_demo_data:
        return None
    auth = request.headers.get('authorization','')
    token = auth[7:] if auth.startswith('Bearer ') else request.cookies.get('SESSION','')
    for expected, identity in [(settings.dev_student_token,{'id':'demo-student','role':'STUDENT'}), (settings.dev_admin_token,{'id':'demo-admin','role':'ADMIN'})]:
        if token and expected and secrets.compare_digest(token,expected):
            return identity
    return None


def warning_list(contest, schedules, buffer):
    start = datetime.fromisoformat(contest['start_at']).astimezone(KST).date()
    end = datetime.fromisoformat(contest['finish_at']).astimezone(KST).date()
    result=[]
    for s in schedules:
        a,b = date.fromisoformat(s['startDate']),date.fromisoformat(s['endDate'])
        overlap = a-timedelta(days=buffer) <= end <= b+timedelta(days=buffer) if s['type']=='EXAM' else start <= b and end >= a
        if overlap:
            result.append({k:v for k,v in s.items() if k!='scheduleId'})
    return result


def create_app(settings=None, provider=None, session_resolver=None, now=None):
    settings = settings or Settings()
    store = Store(settings.database_path)
    clock = now or (lambda:datetime.now(KST))
    if settings.seed_demo_data:
        store.seed(clock().date())
    runtime = Runtime()
    engine = provider or (GeminiProvider(settings.gemini_api_key,settings.gemini_model) if settings.ai_provider=='gemini' else MockProvider())

    @asynccontextmanager
    async def lifespan(app):
        yield
        await engine.close()

    app = FastAPI(title='BSSM 대회 추천 AI',version='1.0.0',lifespan=lifespan)
    app.state.store, app.state.runtime = store, runtime

    @app.exception_handler(APIError)
    async def api_error(request, error):
        return JSONResponse({'code':error.code,'message':error.message},status_code=error.status,headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse({'code':'INVALID_REQUEST','message':'요청 필드와 날짜 형식을 확인하세요.'},status_code=400)

    bearer = HTTPBearer(auto_error=False)

    async def logged_in(request:Request, credentials=Depends(bearer)):
        identity = await session_resolver(request) if session_resolver else local_session(request,settings)
        if not identity:
            raise APIError(401,'UNAUTHORIZED','로그인이 필요합니다.')
        return identity

    async def student(identity=Depends(logged_in)):
        if identity['role']!='STUDENT':
            raise APIError(403,'FORBIDDEN','학생만 사용할 수 있습니다.')
        profile = store.student(identity['id'])
        if not profile:
            raise APIError(404,'NOT_FOUND','학생 정보를 찾지 못했습니다.')
        runtime.limit(identity['id'],clock())
        return identity,profile

    async def admin(identity=Depends(logged_in)):
        if identity['role']!='ADMIN':
            raise APIError(403,'FORBIDDEN','관리자만 사용할 수 있습니다.')
        return identity

    async def upstream(call):
        try:
            return await asyncio.wait_for(call, timeout=30)
        except Exception:
            # Do not expose provider payloads, credentials or student data.
            raise APIError(502,'UPSTREAM_ERROR','추천을 만들지 못했습니다. 다시 시도하세요.') from None

    @app.post('/api/contest-recommendations')
    async def recommend(body:RecommendationRequest, auth=Depends(student)):
        _,profile = auth
        current = clock()
        guideline = store.guidelines()
        schedules = store.schedules()
        candidates=[]
        warnings={}
        for c in store.contests():
            deadline = datetime.fromisoformat(c['finish_at']).astimezone(KST).date()
            if deadline < current.date() or (body.availableUntil and deadline>body.availableUntil):
                continue
            w = warning_list(c,schedules,guideline['examBufferDays'])
            if not body.includeExamPeriod and any(s['type']=='EXAM' for s in w):
                continue
            candidates.append(c)
            warnings[c['contest_id']]=w
        results=[]
        if candidates:
            choices = await upstream(engine.recommend({'student':profile,'request':body.model_dump(mode='json'),'guidelines':guideline,'candidates':candidates}))
            allowed={c['contest_id']:c for c in candidates}
            seen=set()
            for choice in choices.recommendations:
                c=allowed.get(choice.contestId)
                if not c or choice.contestId in seen or choice.recommendType not in body.types:
                    continue
                seen.add(choice.contestId)
                deadline=datetime.fromisoformat(c['finish_at']).astimezone(KST)
                results.append(dict(contestId=c['contest_id'],contestName=c['contest_name'],recommendType=choice.recommendType,
                    scope=c['scope'],tags=c['tags'],expectedScore=c['expected_score'],deadline=deadline.isoformat(),
                    dDay=(deadline.date()-current.date()).days,difficulty=c['difficulty'],prepHours=c['prep_hours'],
                    efficiencyScore=c['expected_score']/c['prep_hours'],reason=choice.reason,teamTip=choice.teamTip,scheduleWarnings=warnings[c['contest_id']]))
        results.sort(key=lambda r:(-r['efficiencyScore'],r['contestId']))
        return {'generatedAt':current.isoformat(),'studentContext':{k:profile[k] for k in ['grade','totalScore','weakestArea']},
                'recommendations':results,'message':None if results else '지금 조건에 맞는 대회가 없습니다.'}

    @app.get('/api/academic-schedules')
    async def schedules(from_:date=Query(alias='from'),to:date=Query(),identity=Depends(logged_in)):
        if from_>to:
            raise APIError(400,'INVALID_REQUEST','조회 시작일은 종료일보다 늦을 수 없습니다.')
        return {'items':[s for s in store.schedules() if s['startDate']<=to.isoformat() and s['endDate']>=from_.isoformat()]}

    @app.get('/api/admin/recommendation-guidelines')
    async def get_guidelines(identity=Depends(admin)):
        return store.guidelines()

    @app.put('/api/admin/recommendation-guidelines')
    async def put_guidelines(body:Guidelines, identity=Depends(admin)):
        result=store.update_guidelines(body)
        if result is None:
            raise APIError(409,'VERSION_CONFLICT','다른 관리자가 수정했습니다. 다시 조회하세요.')
        return result

    @app.post('/api/contest-recommendations/chat')
    async def chat(body:ChatRequest, request:Request, auth=Depends(student)):
        identity,profile=auth
        runtime.cleanup()
        key=str(body.conversationId) if body.conversationId else str(uuid4())
        conv=runtime.conversations.get(key)
        if body.conversationId and (not conv or conv.owner!=identity['id'] or conv.expires<=time.monotonic()):
            raise APIError(404,'NOT_FOUND','대화가 만료되었거나 존재하지 않습니다. 새 대화로 시작하세요.')
        conv=conv or Conversation(identity['id'],time.monotonic()+1800,body.contestId)
        def context():
            if body.conversationId and conv.expires<=time.monotonic():
                raise APIError(404,'NOT_FOUND','대화가 만료되었습니다.')
            contest_id=body.contestId if body.contestId is not None else conv.contest_id
            candidates=[c for c in store.contests() if datetime.fromisoformat(c['finish_at']).astimezone(KST).date()>=clock().date()]
            contest=next((c for c in candidates if c['contest_id']==contest_id),None)
            if contest_id is not None and contest is None:
                raise APIError(404,'NOT_FOUND','검수된 접수 중·예정 대회를 찾지 못했습니다.')
            return contest_id, {'student':profile,'guidelines':store.guidelines(),'candidates':[contest] if contest else candidates,
                'history':conv.history,'message':body.message}

        def commit(reply, contest_id):
            conv.history=(conv.history+[{'role':'user','text':body.message},{'role':'assistant','text':reply}])[-20:]
            conv.contest_id=contest_id
            conv.expires=time.monotonic()+1800
            runtime.conversations[key]=conv
            # Local cache has a bounded size; production uses a shared TTL cache.
            if len(runtime.conversations)>1000:
                for old in list(runtime.conversations):
                    if old!=key and not runtime.conversations[old].lock.locked():
                        del runtime.conversations[old]
                        break

        context()  # Return normal HTTP errors before opening the SSE response.
        if 'text/event-stream' in request.headers.get('accept',''):
            async def events():
                async with conv.lock:
                    try:
                        contest_id,payload=context()
                        chunks=[]
                        async with asyncio.timeout(30):
                            async for chunk in engine.stream_chat(payload):
                                chunks.append(chunk)
                                yield 'event: delta\ndata: '+json.dumps({'text':chunk},ensure_ascii=False)+'\n\n'
                        reply=''.join(chunks)
                        if not reply.strip():
                            raise ValueError('빈 답변')
                        commit(reply,contest_id)
                        yield 'event: done\ndata: '+json.dumps({'conversationId':key,'createdAt':clock().isoformat()})+'\n\n'
                    except Exception:
                        # HTTP status is already 200 once streaming starts. Never commit a partial answer.
                        yield 'event: error\ndata: '+json.dumps({'code':'UPSTREAM_ERROR','message':'추천을 만들지 못했습니다. 다시 시도하세요.'},ensure_ascii=False)+'\n\n'
            return StreamingResponse(events(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
        async with conv.lock:
            contest_id,payload=context()
            reply=await upstream(engine.chat(payload))
            commit(reply,contest_id)
        return {'conversationId':key,'reply':reply,'createdAt':clock().isoformat()}

    return app

app=create_app()
