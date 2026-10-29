from contextlib import asynccontextmanager
import secrets
from typing import Annotated
from fastapi import Depends, FastAPI, File, Form, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from .files import InvalidUpload, validate_document
from .providers.mock import MockProvider
from .providers.base import AnalysisUnavailable
from .providers.gemini_provider import GeminiProvider
from .rules import load_rules
from .schemas import AnalysisContext, AnalysisResponse
from .service import AnalysisService
from .settings import Settings


def create_app(settings: Settings | None = None, provider=None) -> FastAPI:
    settings = settings or Settings()
    ruleset = load_rules(settings.rules_path)

    @asynccontextmanager
    async def lifespan(app):
        factory = {'mock': lambda: MockProvider(), 'gemini': lambda: GeminiProvider(settings)}
        engine = provider or factory[settings.ai_provider]()
        app.state.service = AnalysisService(engine, ruleset)
        try:
            yield
        finally:
            if provider is None and isinstance(engine, GeminiProvider):
                await engine.aclose()

    api = FastAPI(title='BSSM Evidence AI', version='0.4.0', lifespan=lifespan,
                  description='증빙 사실 추출과 평가항목 제안. 최종 승인은 교사가 담당합니다. 기본 모드는 mock입니다.')

    def authorized(key: Annotated[str | None, Header(alias='X-Service-Key')] = None):
        expected = settings.service_api_key.get_secret_value()
        if expected and (key is None or not secrets.compare_digest(key.encode('utf-8'), expected.encode('utf-8'))):
            raise InvalidUpload(401, 'UNAUTHORIZED', '서비스 인증이 필요합니다.')

    @api.exception_handler(InvalidUpload)
    async def upload_error(request, exc):
        return JSONResponse(status_code=exc.status, content={'code':exc.code, 'message':exc.message})

    @api.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo submitted document text, file bytes or API keys in errors.
        return JSONResponse(status_code=400, content={'code':'VALIDATION_FAILED','message':'입력 형식을 확인하세요.'})

    @api.exception_handler(AnalysisUnavailable)
    async def provider_error(request, exc):
        return JSONResponse(status_code=502, content={'code':'AI_UNAVAILABLE','message':'AI 분석을 완료하지 못했습니다. 다시 시도하세요.'})

    @api.get('/health')
    async def health():
        return {'status':'ok','provider':settings.ai_provider,'rulesVersion':ruleset.version}

    @api.get('/api/v1/rules', dependencies=[Depends(authorized)])
    async def rules():
        return ruleset

    @api.post('/api/v1/analyze/file', response_model=AnalysisResponse, dependencies=[Depends(authorized)])
    async def analyze_file(request: Request, file: Annotated[UploadFile, File()],
                           context: Annotated[str, Form()] = '{}'):
        try:
            try:
                parsed = AnalysisContext.model_validate_json(context)
            except ValidationError:
                raise InvalidUpload(400, 'INVALID_CONTEXT', 'context는 올바른 분석 조건 JSON이어야 합니다.') from None
            data = bytearray()
            limit = settings.max_upload_mb * 1024 * 1024
            while chunk := await file.read(65536):
                data.extend(chunk)
                if len(data) > limit:
                    raise InvalidUpload(413, 'FILE_TOO_LARGE', '파일은 10MB 이하로 선택하세요.')
            raw = bytes(data)
            mime = validate_document(file.filename or '', raw, settings)
            if file.content_type and file.content_type not in {mime,'application/octet-stream'}:
                raise InvalidUpload(415, 'INVALID_FILE', '전송한 파일 유형이 실제 내용과 다릅니다.')
            return await request.app.state.service.analyze(parsed, data=raw, mime=mime)
        finally:
            await file.close()

    return api

app = create_app()
