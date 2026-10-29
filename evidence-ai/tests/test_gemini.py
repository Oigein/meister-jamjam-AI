import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from google import genai
from google.genai import types
from fastapi.testclient import TestClient
from app.main import create_app
from app.providers.base import AnalysisUnavailable
from app.providers.gemini_provider import GeminiProvider
from app.rules import load_rules
from app.settings import Settings
from app.schemas import Extraction


def extraction():
    return Extraction(document_type='CERTIFICATE',title='정보처리기능사',recipient_name='홍길동',
                      issuer='한국산업인력공단',issued_date='2026-01-20',award=None,
                      extracted_text='문서명: 정보처리기능사',candidate_rule_id='BSSM_2026_G2_CERT_FUNCTIONAL',
                      evidence_quote='정보처리기능사',confidence=.9,uncertainties=[])


def response(text=None,finish='STOP'):
    return types.GenerateContentResponse(candidates=[types.Candidate(
        finish_reason=finish,content=types.Content(role='model',parts=[types.Part.from_text(
            text=text if text is not None else extraction().model_dump_json())]))])


def test_gemini_text_pdf_image_inputs():
    settings=Settings(_env_file=None)
    generate=AsyncMock(return_value=response())
    provider=GeminiProvider(settings,client=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate))))
    rules=load_rules(settings.rules_path)
    for text,data,mime in [('정보처리기능사',None,None),(None,b'%PDF-test','application/pdf'),(None,b'png','image/png')]:
        output=asyncio.run(provider.extract(text=text,data=data,mime=mime,ruleset=rules))
        assert output.title == '정보처리기능사'
        call=generate.call_args.kwargs
        assert call['model'] == settings.gemini_model
        assert call['config'].response_mime_type == 'application/json'
        assert call['config'].response_json_schema == Extraction.model_json_schema()
        if data is not None:
            part=call['contents'][0].parts[0]
            assert part.inline_data.mime_type == mime
            assert part.inline_data.data == data
        else:assert call['contents'][0].parts[0].text == text


@pytest.mark.parametrize('bad_response',[
    types.GenerateContentResponse(candidates=[]),
    response(finish='MAX_TOKENS'), response(finish='SAFETY'),
    response(text='not-json'), response(text='{"confidence":2}'),
])
def test_incomplete_blocked_malformed_results_rejected(bad_response):
    settings=Settings(_env_file=None)
    generate=AsyncMock(return_value=bad_response)
    provider=GeminiProvider(settings,client=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate))))
    with pytest.raises(AnalysisUnavailable):
        asyncio.run(provider.extract(text='x',data=None,mime=None,ruleset=load_rules(settings.rules_path)))


def test_missing_key_fails_without_mock_fallback():
    settings=Settings(_env_file=None,ai_provider='gemini',gemini_api_key='')
    with pytest.raises(ValueError,match='GEMINI_API_KEY'):
        with TestClient(create_app(settings)):pass


def test_real_google_sdk_serialization_and_gemini_api_response(png_bytes):
    captured=[]
    def handler(request):
        payload=json.loads(request.content);captured.append(payload)
        assert request.url.host == 'generativelanguage.googleapis.com'
        return httpx.Response(200,json={'candidates':[{'content':{'role':'model','parts':[
            {'text':extraction().model_dump_json()}]},'finishReason':'STOP'}]})
    async def execute():
        client=genai.Client(api_key='test-key-not-real',http_options=types.HttpOptions(
            async_client_args={'transport':httpx.MockTransport(handler)}))
        settings=Settings(_env_file=None,ai_provider='gemini')
        provider=GeminiProvider(settings,client=client)
        try:
            for mime in ['application/pdf','image/png']:
                result=await provider.extract(text=None,data=b'example-bytes',mime=mime,ruleset=load_rules(settings.rules_path))
                assert result.document_type.value == 'CERTIFICATE'
            with TestClient(create_app(settings,provider=provider)) as api:
                result=api.post('/api/v1/analyze/file',files={'file':('test.png',png_bytes,'image/png')},data={'context':'{"expected_name":"홍길동"}'})
                assert result.status_code == 200
                assert result.json()['document']['title'] == '정보처리기능사'
                assert result.json()['recommendation']['points'] == 7
                assert result.json()['requires_teacher_approval'] is True
        finally:await provider.aclose()
    asyncio.run(execute())
    assert captured[0]['generationConfig']['responseMimeType']=='application/json'
    assert 'responseJsonSchema' in captured[0]['generationConfig']
    pdf_part=captured[0]['contents'][0]['parts'][0]['inlineData']
    assert pdf_part.get('mimeType',pdf_part.get('mime_type'))=='application/pdf'
    image_part=captured[1]['contents'][0]['parts'][0]['inlineData']
    assert image_part.get('mimeType',image_part.get('mime_type'))=='image/png'


def test_api_failure_is_redacted(png_bytes):
    settings=Settings(_env_file=None,ai_provider='gemini')
    generate=AsyncMock(side_effect=httpx.ConnectError('credential and document must stay private'))
    provider=GeminiProvider(settings,client=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate))))
    with TestClient(create_app(settings,provider=provider)) as api:
        response=api.post('/api/v1/analyze/file',files={'file':('test.png',png_bytes,'image/png')})
        assert response.status_code == 502
        assert 'credential' not in response.text
