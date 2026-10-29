from pathlib import Path
import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError
from .base import AnalysisUnavailable
from ..schemas import Extraction, Ruleset
from ..settings import Settings


class GeminiProvider:
    name = 'gemini'

    def __init__(self, settings: Settings, client=None):
        key = settings.gemini_api_key.get_secret_value()
        if not key and client is None:
            raise ValueError('GEMINI_API_KEY is required in gemini mode')
        self.client = client or genai.Client(
            api_key=key,
            http_options=types.HttpOptions(timeout=60000, retry_options=types.HttpRetryOptions(attempts=1)),
        )
        self.model = settings.gemini_model
        self.prompt = (Path(__file__).resolve().parents[1] / 'prompts' / 'extract.txt').read_text()

    async def extract(self, *, text: str | None, data: bytes | None, mime: str | None,
                      ruleset: Ruleset) -> Extraction:
        if text is not None:
            parts = [types.Part.from_text(text=text)]
        elif data is not None and mime in {'application/pdf', 'image/png', 'image/jpeg'}:
            parts = [types.Part.from_bytes(data=data, mime_type=mime),
                     types.Part.from_text(text='이 증빙자료에서 실제로 보이는 사실만 추출하세요.')]
        else:
            raise AnalysisUnavailable('분석할 텍스트 또는 파일이 없습니다.')
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=[types.Content(role='user', parts=parts)],
                config=types.GenerateContentConfig(
                    system_instruction=self.prompt + '\nRULES_JSON\n' + ruleset.model_dump_json(),
                    response_mime_type='application/json',
                    response_json_schema=Extraction.model_json_schema(),
                    max_output_tokens=8192,
                    candidate_count=1,
                    thinking_config=(types.ThinkingConfig(thinking_level='low')
                                     if self.model.startswith('gemini-3') else None),
                ),
            )
            candidates = response.candidates or []
            if len(candidates) != 1:
                raise AnalysisUnavailable('AI가 분석 결과를 반환하지 않았습니다.')
            finish = candidates[0].finish_reason
            if getattr(finish, 'value', finish) != 'STOP':
                raise AnalysisUnavailable('AI가 완료된 분석 결과를 반환하지 않았습니다.')
            if not response.text:
                raise AnalysisUnavailable('AI 응답에 분석 결과가 없습니다.')
            return Extraction.model_validate_json(response.text)
        except (errors.APIError, httpx.HTTPError, ValidationError, ValueError):
            raise AnalysisUnavailable('Gemini 분석을 완료하지 못했습니다.') from None

    async def aclose(self):
        await self.client.aio.aclose()
        self.client.close()
