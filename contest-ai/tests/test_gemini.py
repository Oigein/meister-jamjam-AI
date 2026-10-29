import asyncio
import json
import httpx
import pytest
from google import genai
from google.genai import types
from app.provider import GeminiProvider


def test_real_sdk_structured_response_and_stream():
    captured=[]
    def handler(request):
        captured.append(json.loads(request.content))
        if ':streamGenerateContent' in str(request.url):
            events=[{'candidates':[{'content':{'role':'model','parts':[{'text':'준비'}]}}]},
                    {'candidates':[{'content':{'role':'model','parts':[{'text':'하세요'}]},'finishReason':'STOP'}]}]
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=''.join('data: '+json.dumps(e)+'\n\n' for e in events))
        return httpx.Response(200,json={'candidates':[{'content':{'role':'model','parts':[{'text':json.dumps({'recommendations':[{'contestId':42,'recommendType':'VALUE','reason':'이유','teamTip':'조언'}]})}]},'finishReason':'STOP'}]})
    async def run():
        provider=GeminiProvider('test-only-not-real','gemini-3.5-flash')
        await provider.close()
        provider.client=genai.Client(api_key='test-only-not-real',http_options=types.HttpOptions(async_client_args={'transport':httpx.MockTransport(handler)}))
        try:
            result=await provider.recommend({'candidates':[]})
            assert result.recommendations[0].contestId==42
            assert ''.join([chunk async for chunk in provider.stream_chat({})])=='준비하세요'
        finally:
            await provider.close()
    asyncio.run(run())
    assert captured[0]['generationConfig']['responseMimeType']=='application/json'
    assert captured[0]['generationConfig']['responseJsonSchema']


def test_missing_key_rejected():
    with pytest.raises(ValueError,match='GEMINI_API_KEY'):
        GeminiProvider('','gemini-3.5-flash')


def test_provider_schema_omits_decoder_bounds_but_local_validation_keeps_them():
    from app.models import Choices
    from app.provider import generation_schema
    schema=generation_schema(Choices.model_json_schema())
    assert 'maxLength' not in json.dumps(schema)
    assert 'maxItems' not in json.dumps(schema)
    assert '$ref' in json.dumps(schema)
    with pytest.raises(ValueError):
        Choices.model_validate({'recommendations':[{'contestId':42,'recommendType':'VALUE','reason':'a'*2001,'teamTip':''}]})
