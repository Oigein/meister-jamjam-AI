from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    ai_provider: Literal['mock', 'gemini'] = 'mock'
    gemini_api_key: SecretStr = SecretStr('')
    gemini_model: str = 'gemini-3.5-flash'
    service_api_key: SecretStr = SecretStr('')
    max_upload_mb: int = Field(10, ge=1, le=10)
    max_pdf_pages: int = Field(20, ge=1, le=50)
    rules_path: Path = ROOT / 'config' / 'rules.json'
