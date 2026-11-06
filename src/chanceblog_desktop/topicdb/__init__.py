"""주제 엔진의 저장 계층(P3, 계획 3.2·4.4·4.5, 결정 D-59·D-61) — 별도 SQLite 파일 `topic_engine.db` 와 그 백업·복원.

`topics/`(순수 계산)와 `service/`(읽기 전용이 기본인 서비스) 사이에 있고, `content/store.py` 와 같은 층이다: **파일을 쓰는 일은 이 패키지 안에서만** 하고(서비스는 `context.write_json` 만 부른다)
어디서 어떤 함수가 파일을 쓰는지는 시험(`test_topicdb_rules`)이 (파일, 함수) 단위로 못박는다. 불러올 때 아무 일도 하지 않으므로 이 파일은 아무것도 가져오지 않는다.
  file    — 한 SQLite 파일을 안전하게 여는 기계 장치(`content/store.py` 의 열기 규칙과 같은 모양: 이름표·판 확인, 낯선·더 새로운 파일은 한 바이트도 바꾸지 않고 거절, 읽기 전용 열기,
            쓰기 잠금 뒤 판 번호를 다시 읽고 사전 사본을 둔 뒤 한 트랜잭션으로 올리기, 실패하면 원래대로)
  store   — `topic_engine.db` 의 표(후보 이력·보류함·점수 스냅샷·관심도 조회 캐시 틀·후보 연결·출처 스냅샷·발행 이력 장부)와 그 읽고 쓰기
  backup  — `topic_engine.db` 와 JSON 셋(`channel_profiles.json`·`seeds.json`·`calendar.json`)의 점검한 백업·복원(키·자격 증명은 어디에도 없다)
기존 보관함 `chanceblog.db`(판 2)와 그 구조(`SCHEMA_VERSION`·`MIGRATIONS`)는 건드리지 않는다 — 두 파일은 서로 모른다.
"""
