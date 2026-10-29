# BSSM 대회 추천 AI

학생의 역량 점수와 검수된 대회 DB를 참고하는 Gemini 추천 API입니다. `evidence-ai`와 독립적으로 실행합니다.

## 실행

```sh
cd ~/AI마털도사/contest-ai
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8002
```

API 문서: http://127.0.0.1:8002/docs

처음 설치하는 환경에서는 `python3 -m venv .venv` → `source .venv/bin/activate` → `pip install -r requirements.lock`을 실행하고 `.env.example`을 `.env`로 복사합니다. Gemini를 사용하려면 `AI_PROVIDER=gemini`, `GEMINI_API_KEY`, `GEMINI_MODEL`을 설정하세요. `mock`은 API 호출 없이 가상 문구를 반환합니다.

## 인증과 데이터

현재는 **로컬 개발용 SQLite·가상 학생·가상 대회**입니다. 실제 학교 로그인/DB와 연결된 상태는 아닙니다. `SEED_DEMO_DATA=true`일 때만 개발 인증이 활성화됩니다. `.env`의 `DEV_STUDENT_TOKEN`과 `DEV_ADMIN_TOKEN`을 각각 `Authorization: Bearer <토큰>` 또는 `SESSION` 쿠키로 전달합니다. 서로 다른 충분히 긴 임의 문자열을 사용하세요. 토큰을 URL이나 Git에 넣지 마세요.

Swagger에서 요청 헤더 입력을 사용할 수 있도록 상단 **Authorize**에 학생/관리자 토큰을 입력합니다. 운영 인증은 `create_app(session_resolver=...)`에 비동기 학교 세션 검증 함수를 주입합니다. 검증 결과는 `{"id": "서버의 사용자 ID", "role": "STUDENT|ADMIN|TEACHER"}`입니다. 학생 학년과 점수는 요청 본문이 아닌 DB에서 읽습니다.

가상 데이터는 첫 생성 날짜 기준 미래 일정이며 이름에 `[가상]`이 붙습니다. 서버를 다시 켜도 덮어쓰지 않습니다. 초기화하려면 서버 종료 후 `data/contest.sqlite3`을 삭제하세요.

## API

- `POST /api/contest-recommendations`: 학생 전용. 요청 필드는 제공된 명세와 동일하며 `{}`도 가능합니다.
- `POST /api/contest-recommendations/chat`: 학생 전용. `message` 필수, `conversationId`·`contestId` 선택.
- `GET /api/academic-schedules?from=2026-11-01&to=2026-12-31`: 로그인 사용자.
- `GET /api/admin/recommendation-guidelines`: 관리자 전용.
- `PUT /api/admin/recommendation-guidelines`: 마지막 조회한 `version`을 포함해 수정. 성공 시 버전 증가, 충돌 시 409.

예시 추천 본문:

```json
{"major":"BACKEND","techStack":["Spring","Python"],"goal":{"targetScore":20},"types":["VALUE","HIGH_SCORE","SHORT_TERM"],"includeExamPeriod":false}
```

추천은 검수 완료·마감일이 오늘 이후인 DB 대회만 사용합니다. `availableUntil`은 마감일 상한입니다. 시험 시작 전~종료 후 `examBufferDays`(기본 7일) 이내 **마감** 대회는 기본 제외합니다. 포함 옵션을 켜면 경고를 반환합니다. 프로젝트·행사 경고는 대회 기간과의 겹침으로 판단합니다. `finish_at`을 명세대로 접수 마감일로 취급하므로 실제 대회 진행일 경고가 필요하면 별도 진행 기간 컬럼이 필요합니다.

모델은 추천 분류·이유·팀 조언만 작성합니다. 응답 지연을 줄이도록 프롬프트에서 최대 6개와 짧은 설명을 요청합니다. 후보에 없는 ID·중복 ID·요청하지 않은 분류는 제거하며 이름·태그·점수·마감·난이도·준비 시간은 DB 값으로 구성합니다. 결과는 `expectedScore / prepHours` 내림차순입니다. 예상 점수는 실제 인정/취득을 보장하지 않습니다.

`Accept: text/event-stream` 요청은 Gemini가 생성하는 청크를 즉시 `delta` 이벤트(`{"text":"..."}`)로 보냅니다. 완료 시 `done`에 대화 ID·생성 시각이 포함됩니다. 스트림 시작 후 실패하면 HTTP 상태는 200이며 `error` 이벤트를 반환하고 부분 답변을 대화에 저장하지 않습니다. 일반 요청은 30초 초과/모델 실패 시 502입니다.

대화는 소유자별 메모리 캐시에 보관하며 성공한 대화마다 30분 TTL이 갱신됩니다. 최근 20개 메시지와 최대 1,000개 대화를 보관합니다. 재시작하면 대화는 사라집니다. 추천·채팅 요청 제한은 사용자별 합산 분당 10회, KST 자정 기준 하루 100회입니다. 초과 시 429와 `Retry-After`를 반환합니다.

## 실제 연동 시 교체할 부분

- `app/store.py`: SQLite 조회를 기존 `Students`, `Contests`, 태그 및 학사 일정 DB에 연결. 현재 태그는 로컬 JSON 컬럼입니다.
- `app/main.py`의 `session_resolver`: 학교 서버에서 검증한 세션/권한으로 교체. 개발 토큰은 운영 인증이 아닙니다.
- 대화·요청 제한: 현재 한 프로세스 기준입니다. 여러 서버/워커에서는 Redis 등 공유 캐시로 교체해야 합니다.
- 대회 수정 API는 기존 서비스 담당이며 이 폴더에는 추가하지 않았습니다. 로컬 스키마의 `expected_score`, `difficulty`, `prep_hours`, `is_verified`에 해당 값을 공급해야 합니다.

가이드라인은 다음 요청부터 반영됩니다. 가이드라인 텍스트를 바꾸어도 대회별 DB 예상 점수는 자동 변경되지 않습니다.

## 테스트

```sh
python -m pytest -q -p no:cacheprovider
```

테스트는 가상 provider와 임시 DB를 사용하며 Gemini를 호출하지 않습니다. 비밀 키와 로컬 DB는 Git에서 제외합니다.

Gemini의 구조화 응답 스키마는 생성용 제약과 서버 검증을 분리했습니다. 길이 제한은 서버 Pydantic 검증으로 유지하며, 추론량 설정은 [Google 공식 가이드](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.5)를 참고했습니다.
