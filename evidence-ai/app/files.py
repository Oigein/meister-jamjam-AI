import io
import warnings
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from .settings import Settings

class InvalidUpload(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def validate_document(filename: str, data: bytes, settings: Settings) -> str:
    if not data:
        raise InvalidUpload(400, 'EMPTY_FILE', '빈 파일은 분석할 수 없습니다.')
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise InvalidUpload(413, 'FILE_TOO_LARGE', '파일은 10MB 이하로 선택하세요.')
    suffix = Path(filename).suffix.lower()
    if suffix == '.pdf':
        if not data.startswith(b'%PDF-'):
            raise InvalidUpload(415, 'INVALID_FILE', '올바른 PDF 파일이 아닙니다.')
        try:
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise InvalidUpload(400, 'ENCRYPTED_PDF', '암호화된 PDF는 지원하지 않습니다.')
            pages = len(reader.pages)
            if pages < 1 or pages > settings.max_pdf_pages:
                raise InvalidUpload(400, 'PDF_PAGE_LIMIT', f'PDF는 1~{settings.max_pdf_pages}페이지만 허용합니다.')
        except InvalidUpload:
            raise
        except Exception:
            raise InvalidUpload(415, 'INVALID_FILE', 'PDF를 읽을 수 없습니다.') from None
        return 'application/pdf'
    if suffix not in {'.png', '.jpg', '.jpeg'}:
        raise InvalidUpload(415, 'UNSUPPORTED_FILE_TYPE', 'PDF·PNG·JPG만 지원합니다.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                expected = 'PNG' if suffix == '.png' else 'JPEG'
                if image.format != expected:
                    raise InvalidUpload(415, 'INVALID_FILE', '확장자와 파일 형식이 다릅니다.')
                if image.width * image.height > 20_000_000:
                    raise InvalidUpload(413, 'IMAGE_TOO_LARGE', '이미지는 2,000만 픽셀 이하로 선택하세요.')
                image.verify()
    except InvalidUpload:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise InvalidUpload(415, 'INVALID_FILE', '이미지를 읽을 수 없습니다.') from None
    return 'image/png' if suffix == '.png' else 'image/jpeg'
