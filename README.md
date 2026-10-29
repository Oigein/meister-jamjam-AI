# meister-jamjam-AI

BSSM 마이스터 역량 서비스를 위한 Gemini 기반 AI API입니다. Python 3.11 이상을 사용하며 각 서비스는 독립적으로 실행합니다.

- [evidence-ai](evidence-ai/README.md): 증빙자료 PDF·이미지에서 정보를 추출하고 학교 기준에 맞는 자격증 여부와 예상 점수를 제안합니다. 교사의 최종 승인이 필요합니다.
- [contest-ai](contest-ai/README.md): 학생의 점수·전공·기술 스택을 참고한 대회 추천, 후속 채팅, 학사 일정 조회와 관리자 추천 지침을 제공합니다.

## 설치

사용할 서비스 폴더에서 실행합니다.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
cp .env.example .env
```

`.env`에 Gemini API 키 등 설정을 입력합니다. API 키, 개발 토큰, 로컬 DB와 가상환경은 저장소에 포함하지 않습니다. 실제 Gemini 호출 없이 확인하려면 `AI_PROVIDER=mock`을 사용합니다.

## 실행

증빙자료 분석:

```sh
cd evidence-ai
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

대회 추천:

```sh
cd contest-ai
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8002
```

각 서버의 `/docs`에서 요청을 실행할 수 있습니다. 대회 추천의 개발 인증 토큰 설정과 요청 예시는 해당 서비스 README를 참고하세요.

## 테스트

각 서비스 폴더에서 실행합니다. 테스트는 실제 Gemini를 호출하지 않습니다.

```sh
python -m pytest -q -p no:cacheprovider
```

현재 학교 로그인·운영 DB·웹 화면과의 연결은 구현하지 않았습니다. 대회 추천은 로컬 가상 데이터를 사용하고, 증빙자료 분석 기준은 2026학년도 2학년 자료를 기준으로 합니다.
