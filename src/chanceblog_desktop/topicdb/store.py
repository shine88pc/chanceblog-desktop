"""`topic_engine.db` — 주제 엔진의 후보 이력·보류함·점수 스냅샷·관심도 조회 캐시 틀·후보 연결·출처 스냅샷·발행 이력 장부(P3, 계획 4.4·4.6, 결정 D-61·D-62).

기존 보관함 `chanceblog.db`(판 2)와 **다른 파일**이고(이름표 `application_id` 도 다르다) 서로 모른다 — 엔진 후보는 기존 후보 JSON 에 칸을 더하지 않고 여기에만 둔다. 여는 규칙(낯선·더 새로운 파일은 한 바이트도 바꾸지 않고 거절·읽기 전용 열기·
쓰기 잠금 뒤 판 번호를 다시 읽고 사전 사본을 둔 뒤 한 트랜잭션으로 올리기)은 `file.py` 의 `EngineFile` 이 한다. 이 파일은 표와 읽고 쓰기다.
  · 후보 이력(`candidates`): 엔진 후보 JSON(`TopicCandidate.to_dict()`) + 찾기용 칸(번호·채널·작업 상태·추천 구간·최종 점수·만든 시각·`review_expires_at`·`normalized_topic_hash`·씨앗 번호). 새 후보만 더한다
    (`add_candidates` — 읽고 판단하고 쓰는 것이 한 트랜잭션이라 두 창이 동시에 더해도 겹치지 않고, 하나라도 안 되면 하나도 저장되지 않는다). 후보를 지우는 길은 없다(제외·보류는 작업 상태이고 지울지는 운영자가 정한다).
  · 보류함(`hold_box`): 점수 구간 보류(50~64점) 후보의 **머문 기간**. 기한의 기준은 **처음 보류함에 든 때**(`entered_at` + 90일)이고 **다시 평가해도 앞당기거나 미루지 않는다**(`re_evaluate`, 결정 D-62) — 구간 밖으로 나갔다가
    다시 들어오면 그때부터 새로 센다. 기한이 지나도 후보를 지우지 않고 '지났다' 는 표시만 한다(`topics/hold.py`).
  · 점수 스냅샷(`score_snapshots`): 평가할 때마다 한 줄(처음 저장·다시 평가) — 점수가 어떻게 변했는지 남긴다.
  · 관심도 조회 캐시 틀(`trend_cache`): 값이 있는 조회 결과만 키워드·기간·비교 그룹별로 둔다(조회 불가·조회 안 함은 담지 않는다 — 다음에 다시 물을 수 있게). 실제 호출은 P5 다.
  · 후보 연결(`candidate_links`)·출처 스냅샷(`provenance`): 엔진 후보를 기존 후보·초안으로 이어 줄 때 쓴다(`draft_plan_id` 는 정하지 않았고 비어 있다 — 열린 항목 1). 출처 스냅샷은 한 번 담으면 바꾸지 않는다.
  · 발행 이력 장부(`history_ledger`): 블로그(`chanceblog`)는 읽기만 하고 읽은 기록을 여기에 자기 장부로 둔다(결정 F) — 블로그 쪽 글이 나중에 없어져도 장부에는 남는다.
비밀(키·자격 증명)은 어느 표에도 없다. 모든 SQL 은 값을 매개변수로 넘긴다.
"""
from __future__ import annotations

import dataclasses
import json
import re
from datetime import date, datetime
from typing import NamedTuple

from ..content.candidates import STAMP_FORMAT, STATUS_KO, STATUSES, TRANSITIONS, keyword_key, parse_stamp
from ..content.candidates import _invalid as candidate_invalid
from ..errors import AppError
from ..topics import hold, trend
from ..topics.channels import CHANNELS, HOLD_DAYS
from ..topics.expand import stable_id
from ..topics.history import HistoryRecord
from ..topics.link import CandidateLink, Provenance
from ..topics.model import TopicCandidate, check_candidate_expiry
from ..topics.score import BAND_HOLD, BANDS, ScoreCard
from ..topics.slots import normalized_topic_hash
from .file import EngineFile, detail_of

APPLICATION_ID = 0x43425445          # 'CBTE' — 주제 엔진 파일의 표시(기존 보관함 'CBDP' 와 다르다)
SCHEMA_VERSION = 1
DEFAULT_TREND_AGE_DAYS = 7           # 조회 캐시를 믿는 날수(초기값 — 전략 원문 확인 전)
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

_SCHEMA = (
    "CREATE TABLE candidates ("
    " candidate_id TEXT PRIMARY KEY, channel TEXT NOT NULL, work_status TEXT NOT NULL, band TEXT NOT NULL, final_score INTEGER, created_at TEXT NOT NULL,"
    " review_expires_at TEXT, normalized_topic_hash TEXT, seed_id TEXT, saved_at TEXT NOT NULL, data TEXT NOT NULL)",
    "CREATE INDEX candidates_channel ON candidates (channel, work_status, created_at)",
    "CREATE INDEX candidates_topic ON candidates (channel, normalized_topic_hash)",
    "CREATE TABLE hold_box (candidate_id TEXT PRIMARY KEY REFERENCES candidates (candidate_id) ON DELETE CASCADE, entered_at TEXT NOT NULL, expires_at TEXT NOT NULL, left_at TEXT)",
    "CREATE TABLE score_snapshots ("
    " candidate_id TEXT NOT NULL REFERENCES candidates (candidate_id) ON DELETE CASCADE, evaluated_at TEXT NOT NULL, final_score INTEGER, band TEXT NOT NULL, data TEXT NOT NULL,"
    " PRIMARY KEY (candidate_id, evaluated_at))",
    "CREATE TABLE trend_cache ("
    " keyword_key TEXT NOT NULL, period TEXT NOT NULL, compared_hash TEXT NOT NULL, queried_on TEXT NOT NULL, status TEXT NOT NULL, ratio INTEGER, data_status TEXT NOT NULL,"
    " stored_at TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (keyword_key, period, compared_hash))",
    "CREATE TABLE candidate_links ("
    " engine_candidate_id TEXT PRIMARY KEY REFERENCES candidates (candidate_id) ON DELETE CASCADE, legacy_candidate_id TEXT, draft_plan_id TEXT, source_topic_id TEXT, seed_id TEXT,"
    " channel TEXT NOT NULL, saved_at TEXT NOT NULL, data TEXT NOT NULL)",
    "CREATE TABLE provenance ("
    " engine_candidate_id TEXT NOT NULL REFERENCES candidates (candidate_id) ON DELETE CASCADE, taken_at TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (engine_candidate_id, taken_at))",
    "CREATE TABLE history_ledger ("
    " channel TEXT NOT NULL, record_key TEXT NOT NULL, title TEXT NOT NULL, keywords TEXT NOT NULL, date TEXT, url TEXT, language TEXT, topic TEXT, ref TEXT, origin TEXT NOT NULL,"
    " first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, PRIMARY KEY (channel, record_key))",
)
_SHAPES = {1: {
    "candidates": ("candidate_id", "channel", "work_status", "band", "final_score", "created_at", "review_expires_at", "normalized_topic_hash", "seed_id", "saved_at", "data"),
    "hold_box": ("candidate_id", "entered_at", "expires_at", "left_at"),
    "score_snapshots": ("candidate_id", "evaluated_at", "final_score", "band", "data"),
    "trend_cache": ("keyword_key", "period", "compared_hash", "queried_on", "status", "ratio", "data_status", "stored_at", "data"),
    "candidate_links": ("engine_candidate_id", "legacy_candidate_id", "draft_plan_id", "source_topic_id", "seed_id", "channel", "saved_at", "data"),
    "provenance": ("engine_candidate_id", "taken_at", "data"),
    "history_ledger": ("channel", "record_key", "title", "keywords", "date", "url", "language", "topic", "ref", "origin", "first_seen_at", "last_seen_at"),
}}
_INDEXES = {1: {"candidates_channel": ("candidates", ("channel", "work_status", "created_at")), "candidates_topic": ("candidates", ("channel", "normalized_topic_hash"))}}


class HoldStay(NamedTuple):
    candidate_id: str
    entered_at: str                  # 처음 보류함에 든 때(UTC)
    expires_at: str                  # 기한 = entered_at + 90일
    left_at: str | None              # 구간 밖으로 나간 때(아직 머무는 중이면 None)


class ScoreSnapshot(NamedTuple):
    evaluated_at: str
    final_score: int | None
    band: str
    scores: ScoreCard


def _dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _check_id(value, item="후보 번호"):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise candidate_invalid(item, "영문·숫자·밑줄(_)·붙임표(-) 1~64자여야 합니다")
    return value


def _stamp(value, item):
    parse_stamp(value, item)
    return value


def history_key(record):
    """발행 이력 한 건의 장부 열쇠 — 글 번호가 있으면 그것, 없으면 (제목·날짜·주소)의 안정된 해시."""
    return f"ref:{record.ref}" if record.ref else "id:" + stable_id(record.title, record.date or "", record.url or "")


class TopicStore(EngineFile):
    """`with TopicStore.open(경로) as store:` 로 쓴다. 읽기만 하는 도구는 `TopicStore.open(경로, migrate=False)` 로 연다(파일을 만들지도 구조를 올리지도 않는다)."""

    APPLICATION_ID = APPLICATION_ID
    SCHEMA_VERSION = SCHEMA_VERSION
    MIN_SCHEMA_VERSION = 1
    SCHEMA = _SCHEMA
    SHAPES = _SHAPES
    INDEXES = _INDEXES
    MIGRATIONS = {}
    KIND = "주제 엔진 보관함"

    # ---- 후보 읽기 -----------------------------------------------------------------------------------------------------------
    def _decode(self, candidate_id, text):
        try:
            candidate = TopicCandidate.from_dict(json.loads(text))
        except (ValueError, TypeError, RecursionError, AppError) as error:
            reason = detail_of(error.detail) if isinstance(error, AppError) and error.detail else type(error).__name__
            raise AppError("TOPIC_STORE_CORRUPT", {"파일": self.path.name}, detail=f"후보 {candidate_id}: {reason}") from None
        if candidate.candidate_id != candidate_id:
            raise AppError("TOPIC_STORE_CORRUPT", {"파일": self.path.name}, detail=f"후보 {candidate_id}: 자료 속 번호가 다르다")
        return candidate

    def _all(self, db):
        return tuple(self._decode(row[0], row[1]) for row in db.execute("SELECT candidate_id, data FROM candidates ORDER BY rowid").fetchall())

    def load_candidate(self, candidate_id):
        """후보 하나. 없으면 TOPIC_CANDIDATE_NOT_FOUND, 저장된 자료가 올바르지 않으면 TOPIC_STORE_CORRUPT."""
        _check_id(candidate_id)
        rows = self._read("SELECT data FROM candidates WHERE candidate_id = ?", (candidate_id,))
        if not rows:
            raise AppError("TOPIC_CANDIDATE_NOT_FOUND", {"항목": candidate_id})
        return self._decode(candidate_id, rows[0][0])

    def list_candidates(self, *, channel=None, work_status=None, band=None):
        """후보 목록(**저장한 순서** — 행 번호 순. 후보를 지우는 길이 없어 한 번 정해진 순서는 바뀌지 않는다: 같은 날 두 번 저장해도 기존 후보의 순번은 그대로이고 새 후보가 뒤에 붙는다, D-70). `channel`·`work_status`·`band` 로 거를 수 있다(알려진 값이어야 한다). 깨진 후보가 하나라도 걸리면 TOPIC_STORE_CORRUPT 로 멈춘다."""
        clauses, params = [], []
        for name, value, allowed in (("channel", channel, CHANNELS), ("work_status", work_status, STATUSES), ("band", band, BANDS)):
            if value is None:
                continue
            if not isinstance(value, str) or value not in allowed:
                raise candidate_invalid({"channel": "채널", "work_status": "작업 상태", "band": "추천 구간"}[name], "알려진 값이어야 합니다")
            clauses.append(f"{name} = ?")
            params.append(value)
        sql = "SELECT candidate_id, data FROM candidates" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY rowid"
        return [self._decode(row[0], row[1]) for row in self._read(sql, tuple(params))]

    def count(self, channel=None):
        """후보 수(채널을 주면 그 채널만) — 자료를 읽지 않으므로 깨진 후보도 센다."""
        if channel is None:
            return self._read("SELECT COUNT(*) FROM candidates")[0][0]
        return self._read("SELECT COUNT(*) FROM candidates WHERE channel = ?", (channel,))[0][0]

    # ---- 후보 쓰기 -----------------------------------------------------------------------------------------------------------
    def add_candidates(self, plan, *, now, history=()):
        """새 후보들을 **한 트랜잭션**으로 더한다. 쓰기 잠금을 잡은 **뒤** 지금 있는 후보들을 읽어 `plan(후보들)` 에 넘기고, 그것이 돌려준 새 후보들을 모두 저장한다 — 읽고(이미 있는지 보고) 저장하는 사이에 다른 프로세스가 끼어들 수
        없어 같은 후보를 두 곳에서 동시에 더해도 겹치지 않고, 하나라도 안 되면(번호가 이미 있음·값이 틀림·디스크 오류 …) 하나도 저장되지 않는다. `history` 의 발행 이력도 같은 트랜잭션으로 장부에 올린다.
        `plan` 은 순수하게 계산만 한다(안에서 이 저장소를 부르면 안 된다). `now` 는 저장한 시각(UTC 시각 글). 저장한 후보들을 튜플로 돌려준다.
        서비스 밖에서 직접 부르는 쪽 주의: 저장소가 막는 것은 **번호 겹침뿐**이다(`UNEXPECTED_ERROR`) — 채널+주제 해시·채널+씨앗+검색 의도+관점이 같은 후보는 먼저 `slots.find_same` 으로 거르는 것이 부른 쪽 몫이다(D-73)."""
        _stamp(now, "저장한 시각")
        records = tuple(history)
        saved = []

        def work(db):
            existing = self._all(db)
            known = {item.candidate_id for item in existing}
            for candidate in plan(existing):
                if not isinstance(candidate, TopicCandidate):
                    raise candidate_invalid("후보", "엔진 후보(TopicCandidate)여야 합니다")
                check_candidate_expiry(candidate)                            # 보류 구간이면 기한이 있고 아니면 없다 — 어긋난 후보를 파일에 넣지 않는다
                if candidate.candidate_id in known:
                    raise AppError("UNEXPECTED_ERROR", detail=f"같은 번호의 후보가 이미 있다(새 후보만 더할 수 있다): {candidate.candidate_id}")
                known.add(candidate.candidate_id)
                self._insert(db, candidate, now)
                saved.append(candidate)
            self._sync_history(db, records, now)

        self._write(work)
        return tuple(saved)

    @staticmethod
    def _columns(candidate, now):
        card = candidate.scores
        return (candidate.candidate_id, candidate.channel, candidate.work_status, candidate.recommendation_band, card.final, candidate.created_at, candidate.review_expires_at,
                normalized_topic_hash(candidate.topic), candidate.seed_id, now, _dump(candidate.to_dict()))

    def _insert(self, db, candidate, now):
        db.execute("INSERT INTO candidates (candidate_id, channel, work_status, band, final_score, created_at, review_expires_at, normalized_topic_hash, seed_id, saved_at, data)"
                   " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", self._columns(candidate, now))
        if candidate.recommendation_band == BAND_HOLD:
            db.execute("INSERT INTO hold_box (candidate_id, entered_at, expires_at, left_at) VALUES (?, ?, ?, NULL)", (candidate.candidate_id, candidate.created_at, candidate.review_expires_at))
        self._snapshot_scores(db, candidate, candidate.created_at)

    @staticmethod
    def _snapshot_scores(db, candidate, evaluated_at):
        db.execute("INSERT OR IGNORE INTO score_snapshots (candidate_id, evaluated_at, final_score, band, data) VALUES (?, ?, ?, ?, ?)",
                   (candidate.candidate_id, evaluated_at, candidate.scores.final, candidate.recommendation_band, _dump(candidate.scores.to_dict())))

    def set_work_status(self, candidate_id, status):
        """후보의 작업 상태를 `TRANSITIONS` 표대로 옮기고 옮긴 후보를 돌려준다 — 읽고 바꾸고 쓰는 것이 한 트랜잭션이다. 없으면 TOPIC_CANDIDATE_NOT_FOUND, 표에 없는 이동이면 CANDIDATE_TRANSITION_INVALID(저장된 것은 그대로).
        추천 구간·점수·보류 기한은 건드리지 않는다(작업 상태와 추천 구간은 다른 축이다)."""
        _check_id(candidate_id)
        if not isinstance(status, str) or status not in STATUSES:
            raise candidate_invalid("작업 상태", "다음 중 하나여야 합니다: " + ", ".join(STATUS_KO[item] for item in STATUSES))
        moved = []

        def work(db):
            row = db.execute("SELECT data FROM candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
            if row is None:
                raise AppError("TOPIC_CANDIDATE_NOT_FOUND", {"항목": candidate_id})
            old = self._decode(candidate_id, row[0])
            if status != old.work_status and status not in TRANSITIONS.get(old.work_status, ()):
                raise AppError("CANDIDATE_TRANSITION_INVALID", {"현재 상태": STATUS_KO[old.work_status], "요청 상태": STATUS_KO[status]}, detail=f"{old.work_status} → {status} 는 표에 없다")
            new = dataclasses.replace(old, work_status=status)
            db.execute("UPDATE candidates SET work_status = ?, data = ? WHERE candidate_id = ?", (status, _dump(new.to_dict()), candidate_id))
            moved.append(new)

        self._write(work)
        return moved[0]

    def re_evaluate(self, candidate, *, evaluated_at):
        """이미 저장된 후보의 점수·구간·선정 이유를 새 평가로 바꾼다(번호가 같은 후보를 받는다). 만든 시각·작업 상태는 저장된 것을 지키고, **보류 기한은 처음 보류함에 든 때 기준을 지킨다**(결정 D-62):
        이미 머무는 중이면 기한을 앞당기지도 미루지도 않고, 구간 밖으로 나가면 머문 기록을 닫고(기한 없음) 다시 들어오면 그때부터 새로 센다(`evaluated_at` + 90일). 점수 스냅샷이 한 줄 늘고 바뀐 후보를 돌려준다."""
        if not isinstance(candidate, TopicCandidate):
            raise candidate_invalid("후보", "엔진 후보(TopicCandidate)여야 합니다")
        _stamp(evaluated_at, "평가한 시각")
        changed = []

        def work(db):
            row = db.execute("SELECT data, saved_at FROM candidates WHERE candidate_id = ?", (candidate.candidate_id,)).fetchone()
            if row is None:
                raise AppError("TOPIC_CANDIDATE_NOT_FOUND", {"항목": candidate.candidate_id})
            old = self._decode(candidate.candidate_id, row[0])
            if old.channel != candidate.channel:
                raise candidate_invalid("채널", "저장된 후보와 채널이 다릅니다")
            stay = db.execute("SELECT entered_at, expires_at FROM hold_box WHERE candidate_id = ? AND left_at IS NULL", (candidate.candidate_id,)).fetchone()
            expiry = None
            if candidate.recommendation_band == BAND_HOLD:
                if stay is not None:
                    expiry = stay[1]                                                # 이미 머무는 중 — 처음 든 때 기준을 지킨다
                else:
                    expiry = hold.review_expires_at(evaluated_at, HOLD_DAYS)
                    db.execute("INSERT INTO hold_box (candidate_id, entered_at, expires_at, left_at) VALUES (?, ?, ?, NULL)"
                               " ON CONFLICT (candidate_id) DO UPDATE SET entered_at = excluded.entered_at, expires_at = excluded.expires_at, left_at = NULL",
                               (candidate.candidate_id, evaluated_at, expiry))
            elif stay is not None:
                db.execute("UPDATE hold_box SET left_at = ? WHERE candidate_id = ?", (evaluated_at, candidate.candidate_id))
            new = dataclasses.replace(candidate, created_at=old.created_at, work_status=old.work_status, review_expires_at=expiry)
            check_candidate_expiry(new)
            columns = self._columns(new, row[1])
            db.execute("UPDATE candidates SET channel = ?, work_status = ?, band = ?, final_score = ?, review_expires_at = ?, normalized_topic_hash = ?, seed_id = ?, data = ? WHERE candidate_id = ?",
                       (columns[1], columns[2], columns[3], columns[4], columns[6], columns[7], columns[8], columns[10], new.candidate_id))
            self._snapshot_scores(db, new, evaluated_at)
            changed.append(new)

        self._write(work)
        return changed[0]

    # ---- 보류함·점수 스냅샷 ---------------------------------------------------------------------------------------------------
    def hold_stays(self, *, open_only=True):
        """보류함에 머문 기록(기한이 이른 것이 먼저, 같으면 번호 순). 기본은 지금 머무는 것만이다."""
        sql = "SELECT candidate_id, entered_at, expires_at, left_at FROM hold_box" + (" WHERE left_at IS NULL" if open_only else "") + " ORDER BY expires_at, candidate_id"
        return [HoldStay(*row) for row in self._read(sql)]

    def score_history(self, candidate_id):
        """그 후보의 점수 스냅샷들(평가한 시각 순)."""
        _check_id(candidate_id)
        rows = self._read("SELECT evaluated_at, final_score, band, data FROM score_snapshots WHERE candidate_id = ? ORDER BY evaluated_at", (candidate_id,))
        try:
            return [ScoreSnapshot(row[0], row[1], row[2], ScoreCard.from_dict(json.loads(row[3]))) for row in rows]
        except (ValueError, TypeError, RecursionError, AppError):
            raise AppError("TOPIC_STORE_CORRUPT", {"파일": self.path.name}, detail=f"후보 {candidate_id} 의 점수 스냅샷") from None

    # ---- 관심도 조회 캐시 틀 -------------------------------------------------------------------------------------------------------
    @staticmethod
    def _trend_key(keyword, period, compared_group):
        return keyword_key(keyword), period, stable_id(*[keyword_key(word) for word in compared_group])

    def put_trend(self, keyword, reading, *, now):
        """값이 있는(충분·일부) 관심도 조회 결과를 캐시에 둔다 — 같은 키워드·기간·비교 그룹이면 바꿔 쓴다. 조회 불가·조회 안 함·자료 부족은 담지 않고 False 를 돌려준다(다음에 다시 물을 수 있게)."""
        _stamp(now, "저장한 시각")
        checked = trend.check_reading(reading)
        if not checked.queried or checked.trend_ratio is None:
            return False
        key = self._trend_key(keyword, checked.trend_period, checked.trend_compared_group)
        payload = {"queried": True, "trend_status": checked.trend_status, "trend_ratio": checked.trend_ratio, "trend_period": checked.trend_period, "trend_compared_group": list(checked.trend_compared_group),
                   "trend_queried_on": checked.trend_queried_on, "data_status": checked.data_status}
        self._write(lambda db: db.execute(
            "INSERT INTO trend_cache (keyword_key, period, compared_hash, queried_on, status, ratio, data_status, stored_at, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (keyword_key, period, compared_hash) DO UPDATE SET queried_on = excluded.queried_on, status = excluded.status, ratio = excluded.ratio, data_status = excluded.data_status,"
            " stored_at = excluded.stored_at, data = excluded.data",
            (*key, checked.trend_queried_on, checked.trend_status, checked.trend_ratio, checked.data_status, now, _dump(payload))))
        return True

    def get_trend(self, keyword, period, compared_group, *, today, max_age_days=DEFAULT_TREND_AGE_DAYS):
        """캐시에 둔 조회 결과 — 조회일이 `today` 로부터 `max_age_days` 일 안(정확히 그 날수까지 포함)일 때만 돌려주고 오래됐거나 미래 날짜이거나 없으면 None."""
        if isinstance(max_age_days, bool) or not isinstance(max_age_days, int) or not 0 <= max_age_days <= 3650:
            raise ValueError("조회 캐시를 믿는 날수는 0~3650 사이의 정수여야 한다")
        asked = date.fromisoformat(today)                                          # 모양이 틀린 기준일은 ValueError(저장된 자료의 문제가 아니다)
        rows = self._read("SELECT queried_on, data FROM trend_cache WHERE keyword_key = ? AND period = ? AND compared_hash = ?", self._trend_key(keyword, period, compared_group))
        if not rows:
            return None
        try:
            age = (asked - date.fromisoformat(rows[0][0])).days
            data = json.loads(rows[0][1])
            reading = trend.TrendReading(data["queried"], data["trend_status"], data["trend_ratio"], data["trend_period"], tuple(data["trend_compared_group"]), data["trend_queried_on"], data["data_status"])
        except (ValueError, TypeError, KeyError, RecursionError):
            raise AppError("TOPIC_STORE_CORRUPT", {"파일": self.path.name}, detail="관심도 조회 캐시 한 줄") from None
        return reading if 0 <= age <= max_age_days else None

    # ---- 후보 연결·출처 스냅샷 ------------------------------------------------------------------------------------------------
    def save_link(self, link, *, now):
        """엔진 후보와 기존 후보·초안의 연결을 저장한다(후보 하나에 연결 하나 — 있으면 바꿔 쓴다). 연결의 채널·씨앗·원천 주제는 저장된 후보와 같아야 한다."""
        if not isinstance(link, CandidateLink):
            raise candidate_invalid("연결", "연결(CandidateLink)이어야 합니다")
        _stamp(now, "저장한 시각")

        def work(db):
            row = db.execute("SELECT data FROM candidates WHERE candidate_id = ?", (link.engine_candidate_id,)).fetchone()
            if row is None:
                raise AppError("TOPIC_CANDIDATE_NOT_FOUND", {"항목": link.engine_candidate_id})
            candidate = self._decode(link.engine_candidate_id, row[0])
            if (candidate.channel, candidate.seed_id, candidate.source_topic_id) != (link.channel, link.seed_id, link.source_topic_id):
                raise candidate_invalid("연결", "연결의 채널·씨앗 번호·원천 주제 번호가 저장된 후보와 다릅니다")
            db.execute("INSERT INTO candidate_links (engine_candidate_id, legacy_candidate_id, draft_plan_id, source_topic_id, seed_id, channel, saved_at, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                       " ON CONFLICT (engine_candidate_id) DO UPDATE SET legacy_candidate_id = excluded.legacy_candidate_id, draft_plan_id = excluded.draft_plan_id,"
                       " source_topic_id = excluded.source_topic_id, seed_id = excluded.seed_id, channel = excluded.channel, saved_at = excluded.saved_at, data = excluded.data",
                       (link.engine_candidate_id, link.legacy_candidate_id, link.draft_plan_id, link.source_topic_id, link.seed_id, link.channel, now, _dump(link.to_dict())))

        self._write(work)

    def load_link(self, engine_candidate_id):
        """그 후보의 연결(없으면 None)."""
        _check_id(engine_candidate_id)
        rows = self._read("SELECT data FROM candidate_links WHERE engine_candidate_id = ?", (engine_candidate_id,))
        return self._decode_link(engine_candidate_id, rows[0][0]) if rows else None

    def links(self):
        """저장된 연결 모두(엔진 후보 번호 순)."""
        return [self._decode_link(row[0], row[1]) for row in self._read("SELECT engine_candidate_id, data FROM candidate_links ORDER BY engine_candidate_id")]

    def _decode_link(self, candidate_id, text):
        try:
            link = CandidateLink.from_dict(json.loads(text))
        except (ValueError, TypeError, RecursionError, AppError):
            raise AppError("TOPIC_STORE_CORRUPT", {"파일": self.path.name}, detail=f"후보 {candidate_id} 의 연결") from None
        if link.engine_candidate_id != candidate_id:
            raise AppError("TOPIC_STORE_CORRUPT", {"파일": self.path.name}, detail=f"후보 {candidate_id} 의 연결: 자료 속 번호가 다르다")
        return link

    def save_provenance(self, engine_candidate_id, provenance, *, taken_at):
        """출처 스냅샷을 담는다 — 한 번 담으면 바꾸지 않는다(같은 후보·같은 시각이 이미 있으면 처음 것이 남는다). 담았으면 True."""
        _check_id(engine_candidate_id)
        if not isinstance(provenance, Provenance):
            raise candidate_invalid("출처 스냅샷", "출처 스냅샷(Provenance)이어야 합니다")
        _stamp(taken_at, "스냅샷 시각")

        def work(db):
            if db.execute("SELECT 1 FROM candidates WHERE candidate_id = ?", (engine_candidate_id,)).fetchone() is None:
                raise AppError("TOPIC_CANDIDATE_NOT_FOUND", {"항목": engine_candidate_id})
            return db.execute("INSERT OR IGNORE INTO provenance (engine_candidate_id, taken_at, data) VALUES (?, ?, ?)", (engine_candidate_id, taken_at, _dump(provenance.to_dict()))).rowcount == 1

        return self._write(work)

    def provenance_history(self, engine_candidate_id):
        """그 후보의 출처 스냅샷들(담은 시각 순) → [(담은 시각, Provenance)]."""
        _check_id(engine_candidate_id)
        rows = self._read("SELECT taken_at, data FROM provenance WHERE engine_candidate_id = ? ORDER BY taken_at", (engine_candidate_id,))
        try:
            return [(row[0], Provenance.from_dict(json.loads(row[1]))) for row in rows]
        except (ValueError, TypeError, RecursionError, AppError):
            raise AppError("TOPIC_STORE_CORRUPT", {"파일": self.path.name}, detail=f"후보 {engine_candidate_id} 의 출처 스냅샷") from None

    # ---- 발행 이력 장부 ------------------------------------------------------------------------------------------------------
    @staticmethod
    def _sync_history(db, records, now):
        for record in records:
            if not isinstance(record, HistoryRecord):
                raise candidate_invalid("발행 이력", "발행 이력 기록(HistoryRecord)이어야 합니다")
            db.execute(
                "INSERT INTO history_ledger (channel, record_key, title, keywords, date, url, language, topic, ref, origin, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (channel, record_key) DO UPDATE SET title = excluded.title, keywords = excluded.keywords, date = excluded.date, url = excluded.url, language = excluded.language,"
                " topic = excluded.topic, ref = excluded.ref, origin = excluded.origin, last_seen_at = excluded.last_seen_at",
                (record.channel, history_key(record), record.title, _dump(list(record.keywords)), record.date, record.url, record.language, record.topic, record.ref, record.origin, now, now))

    def sync_history(self, records, *, now):
        """읽은 발행 이력을 장부에 올린다(이미 있으면 바꿔 쓰고 처음 본 시각은 지킨다). 올린 기록 수를 돌려준다."""
        _stamp(now, "저장한 시각")
        items = tuple(records)
        self._write(lambda db: self._sync_history(db, items, now))
        return len(items)

    def history_records(self, channel=None):
        """장부의 발행 이력(채널 순서·날짜·글 번호·제목 순 — 같은 장부는 늘 같은 순서). 채널을 주면 그 채널만."""
        if channel is not None and (not isinstance(channel, str) or channel not in CHANNELS):
            raise candidate_invalid("채널", "알려진 값이어야 합니다")
        rows = self._read("SELECT channel, title, keywords, date, url, language, topic, ref, origin FROM history_ledger" + (" WHERE channel = ?" if channel else ""), (channel,) if channel else ())
        made = []
        try:
            for row in rows:
                made.append(HistoryRecord(channel=row[0], title=row[1], keywords=tuple(json.loads(row[2])), date=row[3], url=row[4], language=row[5], topic=row[6], ref=row[7], origin=row[8]))
        except (ValueError, TypeError, RecursionError):
            raise AppError("TOPIC_STORE_CORRUPT", {"파일": self.path.name}, detail="발행 이력 장부 한 줄") from None
        return sorted(made, key=lambda item: (CHANNELS.index(item.channel), item.date or "", item.ref or "", item.title))

    # ---- 점검 ---------------------------------------------------------------------------------------------------------------
    def check(self):
        """전체 점검 — 문제 문장 목록(비어 있으면 이상 없음). 파일 구조(integrity_check)와 후보마다 자료가 올바른지·찾기용 칸과 자료가 같은지·보류함 기록이 후보와 맞는지·점수 스냅샷·연결·출처·장부의 자료가 읽히는지 본다."""
        problems = []
        with self._lock:
            try:
                for row in self._db.execute("PRAGMA integrity_check").fetchall():
                    if row[0] != "ok":
                        problems.append(f"파일 구조: {detail_of(row[0])}")
                for row in self._db.execute("SELECT candidate_id, channel, work_status, band, final_score, created_at, review_expires_at, normalized_topic_hash, seed_id, data FROM candidates ORDER BY candidate_id").fetchall():
                    try:
                        candidate = self._decode(row[0], row[9])
                    except AppError as error:
                        problems.append(f"후보 {row[0]}: {error.detail}")
                        continue
                    wanted = (candidate.channel, candidate.work_status, candidate.recommendation_band, candidate.scores.final, candidate.created_at, candidate.review_expires_at, normalized_topic_hash(candidate.topic), candidate.seed_id)
                    if wanted != tuple(row[1:9]):
                        problems.append(f"후보 {row[0]}: 찾기용 칸과 자료가 다르다")
                    try:
                        check_candidate_expiry(candidate)
                    except AppError:
                        problems.append(f"후보 {row[0]}: 보류 기한이 추천 구간과 맞지 않는다")
                for candidate_id, expires_at in self._db.execute("SELECT candidate_id, expires_at FROM hold_box WHERE left_at IS NULL").fetchall():
                    found = self._db.execute("SELECT band, review_expires_at FROM candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
                    if found is None or found[0] != BAND_HOLD or found[1] != expires_at:
                        problems.append(f"보류함 {candidate_id}: 후보의 구간·기한과 맞지 않는다")
                problems += self._check_side_tables()
            except Exception as error:                                               # 점검은 멈추지 않고 문제로 적는다 — 그래도 원인을 지우지 않는다(오류 이름과 한 줄)
                problems.append(f"점검 중 오류: {type(error).__name__}: {detail_of(error)}")
        return problems

    def _check_side_tables(self):
        problems = []
        for table, decode in (("score_snapshots", lambda data: ScoreCard.from_dict(json.loads(data))), ("provenance", lambda data: Provenance.from_dict(json.loads(data))),
                              ("candidate_links", lambda data: CandidateLink.from_dict(json.loads(data)))):
            for key, data in self._db.execute(f"SELECT {'engine_candidate_id' if table != 'score_snapshots' else 'candidate_id'}, data FROM {table}").fetchall():
                try:
                    decode(data)
                except (ValueError, TypeError, RecursionError, AppError):
                    problems.append(f"{table} {key}: 자료를 읽을 수 없다")
        return problems


def open_for_write(path, *, busy_seconds=None):
    """주제 엔진 보관함을 연다(없으면 폴더와 파일을 만들고 옛 구조는 사본을 남기고 올린다) — 서비스가 부르는 이름이다(`TopicStore.open` 과 같다)."""
    return TopicStore.open(path) if busy_seconds is None else TopicStore.open(path, busy_seconds=busy_seconds)


def open_read_only(path):
    """주제 엔진 보관함을 **읽기 전용**으로 연다 — 파일을 만들지도 구조를 올리지도 않고 한 바이트도 바꾸지 않는다. 파일이 없으면 CONTENT_NOT_FOUND."""
    return TopicStore.open(path, migrate=False)


def utc_stamp(moment):
    """시각(datetime) → `YYYY-MM-DDTHH:MM:SSZ` 글 — 서비스가 시계에서 받은 시각을 저장 모양으로 바꾼다."""
    if not isinstance(moment, datetime):
        raise TypeError("시각(datetime)이어야 한다")
    return moment.strftime(STAMP_FORMAT)


__all__ = ["APPLICATION_ID", "DEFAULT_TREND_AGE_DAYS", "HoldStay", "SCHEMA_VERSION", "ScoreSnapshot", "TopicStore", "history_key", "open_for_write", "open_read_only", "utc_stamp"]
