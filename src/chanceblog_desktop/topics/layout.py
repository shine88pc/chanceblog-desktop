"""주제 엔진이 사용자 데이터 폴더에 둘 파일의 **이름만** 정한다. 읽고 쓰는 일은 다음 묶음(저장)의 몫이라 여기에는 파일을 열거나 만드는 코드가 없다.

저장소(공개)에는 스키마·틀·예시·규칙만 두고, 실제로 켜 둔 씨앗·고친 채널 프로필·고친 캘린더는 이 PC 의 사용자 데이터 폴더에만 둔다.
백업·복원 범위에는 아래 네 파일이 모두 들어간다(SQLite 파일은 SQLite 백업 방식으로, JSON 파일은 모양을 확인한 뒤 복사). API 키·자격 증명은 어떤 파일에도 없고 백업에도 넣지 않는다.
기존 보관함 `chanceblog.db` 는 건드리지 않는다 — 엔진 후보의 보관함은 새 파일 `topic_engine.db` 다.
"""
CHANNEL_PROFILES_FILE = "channel_profiles.json"
SEEDS_FILE = "seeds.json"
CALENDAR_FILE = "calendar.json"
ENGINE_DB_FILE = "topic_engine.db"

JSON_FILES = (CHANNEL_PROFILES_FILE, SEEDS_FILE, CALENDAR_FILE)
SQLITE_FILES = (ENGINE_DB_FILE,)
USER_DATA_FILES = JSON_FILES + SQLITE_FILES
