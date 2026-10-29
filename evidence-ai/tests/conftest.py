import asyncio
import io
import pytest
from PIL import Image
from app.providers.mock import MockProvider
from app.rules import load_rules
from app.schemas import AnalysisContext
from app.service import AnalysisService
from app.settings import Settings

@pytest.fixture
def png_bytes():
    output=io.BytesIO()
    Image.new('RGB',(20,20),'white').save(output,format='PNG')
    return output.getvalue()

@pytest.fixture
def analyze():
    """Exercise rule calculation internally without exposing a text API."""
    service=AnalysisService(MockProvider(),load_rules(Settings(_env_file=None).rules_path))
    def run(data):
        context=AnalysisContext(**{k:v for k,v in data.items() if k!='text'})
        return asyncio.run(service.analyze(context,text=data['text'])).model_dump(mode='json')
    return run
