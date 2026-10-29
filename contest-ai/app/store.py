import json
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

AREAS = ['JOB_BASIC', 'MAJOR_SKILL', 'CHARACTER_JOB_ETHIC', 'HUMANITIES_LITERACY', 'FOREIGN_LANGUAGE']

class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS students (user_id TEXT PRIMARY KEY, grade INTEGER NOT NULL, scores TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS contests (
              contest_id INTEGER PRIMARY KEY, contest_name TEXT NOT NULL, scope TEXT NOT NULL,
              tags TEXT NOT NULL, start_at TEXT NOT NULL, finish_at TEXT NOT NULL,
              expected_score INTEGER NOT NULL CHECK(expected_score >= 0),
              difficulty INTEGER NOT NULL CHECK(difficulty BETWEEN 1 AND 5),
              prep_hours REAL NOT NULL CHECK(prep_hours > 0), is_verified INTEGER NOT NULL CHECK(is_verified IN (0,1)));
            CREATE TABLE IF NOT EXISTS academic_schedules (
              schedule_id INTEGER PRIMARY KEY, type TEXT NOT NULL CHECK(type IN ('EXAM','PROJECT','EVENT')),
              title TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL CHECK(end_date >= start_date));
            CREATE TABLE IF NOT EXISTS recommendation_guidelines (
              id INTEGER PRIMARY KEY CHECK(id=1), prompt_guideline TEXT NOT NULL,
              exam_buffer_days INTEGER NOT NULL CHECK(exam_buffer_days >= 0), version INTEGER NOT NULL);
            INSERT OR IGNORE INTO recommendation_guidelines VALUES (1, '검수된 후보만 추천하고 예상 점수는 확정 취득 점수가 아님을 안내하세요.', 7, 1);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def seed(self, today):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO students VALUES (?,?,?)', ('demo-student', 2, json.dumps(dict(zip(AREAS, [70,110,65,50,25])))))
            for i, name, score, hours, offset, tags in [
                (42,'[가상] 부산 SW 해커톤',5,20,16,['백엔드','AI']),
                (43,'[가상] 교내 앱 아이디어 대회',3,8,22,['앱','프론트엔드']),
                (44,'[가상] 임베디드 프로젝트 경진대회',10,60,40,['임베디드']),
            ]:
                start = (today + timedelta(days=1)).isoformat() + 'T09:00:00+09:00'
                end = (today + timedelta(days=offset)).isoformat() + 'T18:00:00+09:00'
                db.execute('INSERT OR IGNORE INTO contests VALUES (?,?,?,?,?,?,?,?,?,?)', (i,name,'OUT_SCHOOL',json.dumps(tags),start,end,score,3,hours,1))
            db.execute('INSERT OR IGNORE INTO academic_schedules VALUES (?,?,?,?,?)',
                       (1,'EXAM','[가상] 기말고사',(today+timedelta(days=40)).isoformat(),(today+timedelta(days=43)).isoformat()))

    def student(self, user_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM students WHERE user_id=?', (user_id,)).fetchone()
        if row is None:
            return None
        scores = json.loads(row['scores'])
        return {'grade':row['grade'], 'scores':scores, 'totalScore':sum(scores.values()), 'weakestArea':min(scores,key=scores.get)}

    def contests(self):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM contests WHERE is_verified=1 ORDER BY contest_id').fetchall()
        return [dict(r) | {'tags':json.loads(r['tags'])} for r in rows]

    def schedules(self):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM academic_schedules ORDER BY start_date, schedule_id').fetchall()
        return [{'scheduleId':r['schedule_id'],'type':r['type'],'title':r['title'],'startDate':r['start_date'],'endDate':r['end_date']} for r in rows]

    def guidelines(self):
        with self.connect() as db:
            r = db.execute('SELECT * FROM recommendation_guidelines WHERE id=1').fetchone()
        return {'promptGuideline':r['prompt_guideline'],'examBufferDays':r['exam_buffer_days'],'version':r['version']}

    def update_guidelines(self, value):
        with self.connect() as db:
            changed = db.execute('UPDATE recommendation_guidelines SET prompt_guideline=?, exam_buffer_days=?, version=version+1 WHERE id=1 AND version=?',
                                 (value.promptGuideline,value.examBufferDays,value.version)).rowcount
        return (value.model_dump() | {'version':value.version+1}) if changed else None
