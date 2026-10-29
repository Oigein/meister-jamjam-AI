# BSSM 증빙자료 분석 AI

Gemini로 PDF·PNG·JPG를 읽고, 학교 기준에 맞는 평가 항목과 점수를 제안하는 별도 서비스입니다. 최종 승인은 교사가 담당하며 학생 점수나 DB를 자동으로 수정하지 않습니다.

## 실행

Python 3.11 이상을 사용합니다. 가상환경이 준비돼 있다면 다음 명령만 실행하세요.

```sh
cd evidence-ai
source .venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

접속: <http://localhost:8001/docs>

처음 설치할 때만 가상환경과 의존성을 설치합니다.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
```

`.env`가 없다면 `.env.example`을 복사해 설정하세요. 기존 `.env`에는 API 키가 있으므로 덮어쓰지 마세요.

```dotenv
AI_PROVIDER=gemini
GEMINI_API_KEY=발급받은_키
GEMINI_MODEL=gemini-3.5-flash
```

설정을 바꾼 뒤에는 서버를 재시작합니다. 키는 [Google AI Studio](https://aistudio.google.com/apikey)에서 발급받습니다. 실제 분석에서는 문서가 Google Gemini API로 전송되며 사용량·요금·할당량은 해당 계정에 따릅니다.

`AI_PROVIDER=mock`으로 바꾸면 외부 요청 없이 파일 검증과 API 동작을 테스트합니다. 모의 모드는 이미지·PDF의 글자를 판독하지 않습니다.

## 사용

API 문서에서 `POST /api/v1/analyze/file` → **Try it out** → 파일 선택 → `context` 입력 → **Execute** 순서로 실행합니다.

```json
{"expected_name":"문서에 적힌 학생 이름"}
```

파일은 10MB 이하의 PDF·PNG·JPG, PDF는 최대 20페이지입니다. 문서 유형·발급일·원문 근거·학생 이름 등을 검사하고 불명확하면 점수 제안을 보류합니다.

응답은 다음 항목을 반환합니다.

- `is_recognized_certificate`: 등록된 기준의 자격증 명칭과 일치하면 true, 확인되지 않으면 false. 점수 승인 여부와는 별개입니다.
- `document`: 문서 종류·명칭·이름·발급기관·발급일·수상내역
- `recommendation`: `score_type`, `item`, `points`, `example_only`. 판단할 수 없으면 `null`
- `messages`: 교사가 확인할 조건과 보류 사유
- `requires_teacher_approval`: 항상 `true`

원문 전체·자격번호·생년월일·내부 규칙 ID·신뢰도는 응답에 포함하지 않습니다. 모델의 판독이 문서의 진위를 보증하지는 않습니다.

## 적용 기준

사용자가 제공한 **2026학년도 마이스터 역량 인증제 세부 기준(2학년)**에서 배점이 명확한 자격증 규칙 12개를 적용합니다. 다른 학년·학년도에 일반화하지 않습니다.

- 과정평가형 정보처리산업기사 외부평가 **9점**. 내부평가 최대 6점은 별도입니다.
- 정보처리기능사 **7점**. 한국산업인력공단 발급 여부와 인정 분야를 확인합니다.
- LPIC·CCNA·CCNP·OCPJ·SCJP·OCA·OCP·MCITP **10점**.
- 컴퓨터활용 2급·리눅스마스터 2급·SQLD·AZ-900 **5점**, 워드프로세서 **3점**.

재학 중 취득 여부, 중복 인정, 전공 자격증 누적 상한 30점은 교사가 확인해야 합니다. 기존 DB 내역은 연결하지 않았으므로 추가 인정 가능한 점수를 확정하지 않습니다.

TOPCIT·한국사·한자·외국어 성적의 등급 계산, 대회 참가·입상 가산점, 봉사·출결·학기별 평가는 아직 자동 계산하지 않습니다. 원문에 그린마일리지 최대 4점/표 5점, 한자 5급 인정/5급 이하 제외 표현이 겹쳐 담당 부서 확인이 필요합니다.

규칙은 `config/rules.json`에서 수정합니다. 원문 추출본과 파일 해시는 `config/sources/`에 보관합니다. 원본 HWPX는 수정하지 않았습니다.

## API와 웹 연결

- `GET /health`: 서버 상태
- `GET /api/v1/rules`: 적용 기준
- `POST /api/v1/analyze/file`: multipart 파일과 `context` JSON 문자열 분석

오류는 `code`, `message`로 반환합니다. 검증 400, 인증 401, 용량 413, 형식 415, AI 실패 502입니다.

학교 백엔드가 분석을 요청하고 교사 검토 화면에 결과를 전달하는 방식으로 연결합니다. `SERVICE_API_KEY`를 설정했다면 호출 시 `X-Service-Key` 헤더를 보내야 합니다. 이 키는 학교 사용자 인증을 대신하지 않습니다.

첨부 ERD에 맞춰 추천 `score_type`은 `JOB_BASIC`, `MAJOR_SKILL`, `CHARACTER_JOB_ETHIC`, `HUMANITIES_LITERACY`, `FOREIGN_LANGUAGE`만 허용합니다. 교사 승인 후 백엔드에서 `MeisterScoreDetails`의 학생·교사 UUID, 영역 코드, 50자 이내 요약, 확정 점수, 서버 처리 시각을 저장해야 합니다. 문서 발급일과 DB 처리 시각은 별개입니다. 내역과 영역별 누적 점수는 같은 트랜잭션에서 갱신해야 하며, `total_merit_points`는 상벌점 합계이므로 마이스터 점수로 갱신하지 않습니다.

DB 저장과 기존 웹 연결은 구현하지 않았습니다. 원본·결과를 영구 저장하지 않으며 업로드 처리 중 임시 파일은 요청 후 닫습니다. 외부 배포 전 학교 인증·권한·요청 제한·HTTPS·보존 정책이 필요합니다.

## 파일과 테스트

- `app/`: API, Gemini·모의 분석, 파일 검증, 규칙 계산
- `config/`: 학교 기준 및 원문 근거
- `tests/fixtures/`: 내부 규칙 테스트용 가상 문서
- `tests/`: 분석·Gemini 요청 계약·학교 배점 테스트
- `scripts/extract_hwpx.py`: HWPX 원문 추출 도구
- `requirements.txt`: 의존성 범위 / `requirements.lock`: 검증한 버전

```sh
python -m pytest -q
```

테스트는 실제 Gemini 호출 없이 수행합니다. 이전에 가상 텍스트·이미지의 실제 분석과 산업기사 9점 제안도 확인했지만, 실제 학교 자료 전체의 정확도 평가를 완료한 것은 아닙니다.

공식 문서: [문서 입력](https://ai.google.dev/gemini-api/docs/generate-content/document-processing), [구조화 출력](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).


`is_recognized_certificate`는 AI가 읽은 문서 종류와 명칭을 서버의 기준 목록에 대조한 결과입니다. 모델이 선택한 규칙 ID나 `recommendation` 유무만으로 결정하지 않습니다. 따라서 이름 불일치·중복 제출·필수 조건 누락으로 점수를 보류해도, 목록에 있는 자격증이면 true일 수 있습니다. TOPCIT·한국사·한자·외국어 시험처럼 기준에는 있지만 점수 자동 계산을 구현하지 않은 항목도 true로 구분합니다.

false는 현재 등록 목록에서 명칭을 확인하지 못했다는 뜻이며, 문서 진위나 학교의 최종 불인정을 의미하지 않습니다. 원문에서 포괄적으로 정한 전공 기능사 중 미등록 명칭은 목록 보완과 교사 확인이 필요합니다. 판독 실패·명칭 누락·자격증 이외 문서는 false입니다.
