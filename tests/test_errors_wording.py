"""오류 카드·안내 문구의 말투와 이름 시험(L4 — F028 명령줄 말투·F041 없는 메뉴 이름, 결정 D-544·D-545) — 네트워크·시크릿·Qt 없이 돈다.

지키는 것:
  1) **카드에 개발자 말투가 없다** — 화면 카드에 나가는 글(사용자 문구 + 하실 일의 앞부분 `card_action`)에는 명령·옵션·파일 이름·마크다운 링크·'터미널'·'세부' 같은 말이 없다(지금 있는 코드 전부).
  2) **명령줄 안내는 꼬리로 나뉘어 있다** — `명령줄·개발자 안내:` 앞부분이 늘 있고, 옛 명령은 하나도 사라지지 않았다(명령줄 출력은 전체 `action` 을 그대로 쓴다).
  3) **카드가 꼬리를 싣지 않는다** — `failure_from` 은 `card_action` 을 쓰고, 슬롯 값이 이름표를 흉내 내도 카드 글이 잘리지 않는다.
  4) **문체를 바꾼 행은 '-요' 문체**다(합니다체가 남지 않았다).
  5) **문구가 가리키는 이름이 실제로 있다** — 화살표 길(`설정 → 백업·복원`)·따옴표 이름은 실제 화면 문구 표(`ui/core`)·메뉴·후보 상태 이름에 있거나, 이유가 적힌 예외 목록에 있다. 알려진 틀린 이름은 다시 나오지 않는다.

이 시험이 덮는 코드는 `CARD_CODES`(L4 때의 105개) 고정 목록이다 — 다른 갈래가 나중에 더하는 코드는 병합 뒤에 이 규칙 때문에 빨개지지 않고, 같은 규칙을 지키게 하려면 이 목록에 더한다.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.content import candidates as candidate_content  # noqa: E402
from chanceblog_desktop.errors import CATALOG, CLI_TAIL_LABEL, AppError, card_action, render  # noqa: E402
from chanceblog_desktop.ui import adapters, single_instance  # noqa: E402
from chanceblog_desktop.service import format as service_format  # noqa: E402
from chanceblog_desktop.ui.core import app_state  # noqa: E402
from chanceblog_desktop.ui.core.text import T  # noqa: E402

BS = chr(92)
DOC = (ROOT / "docs" / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
MIGRATION = (ROOT / "docs" / "MIGRATION.md").read_text(encoding="utf-8")

CARD_CODES = frozenset((
    "BLOGGER_AUTH_EXPIRED", "BLOGGER_PERMISSION_DENIED", "BLOGGER_NOT_FOUND", "BLOGGER_SERVER_ERROR", "PAGES_LOCAL_REPO_INVALID",
    "PAGES_LOCAL_REPO_DIRTY", "PAGES_LOCAL_REPO_NOT_MAIN", "PAGES_LOCAL_REPO_DIVERGED", "PAGES_LOCAL_FILE_IN_THE_WAY", "GIT_NOT_INSTALLED",
    "GIT_PUSH_AUTH", "GIT_PUSH_NETWORK", "GIT_IDENTITY_MISSING", "GIT_PUSH_REJECTED", "ACTIONS_RUN_FAILED", "ACTIONS_RUN_PENDING_LONG",
    "PAGES_DEPLOY_NOT_VISIBLE", "FILE_WRITE_FAILED", "FILE_IN_USE", "FILE_PATH_TOO_LONG", "DISK_FULL", "IMAGE_NOT_FOUND", "IMAGE_TOO_LARGE",
    "DATA_DIR_UNSAFE", "SETTINGS_INVALID", "API_RATE_LIMITED", "NETWORK_OFFLINE", "NETWORK_TIMEOUT", "API_SERVER_ERROR", "NAVER_SIMILARITY_HIGH",
    "NAVER_PACKAGE_INCOMPLETE", "NAVER_PUBLISH_URL_INVALID", "PROFILE_INVALID", "NAVER_PROFILE_MISSING", "CHECK_FAILED", "DUPLICATE_SLUG",
    "DUPLICATE_CONTENT", "CONTENT_INVALID", "CONTENT_NOT_FOUND", "CANDIDATE_INVALID", "CANDIDATE_CORRUPT", "CANDIDATE_NOT_FOUND",
    "CANDIDATE_TRANSITION_INVALID", "CANDIDATE_CONFIRM_REQUIRED", "CANDIDATE_AMBIGUOUS", "CANDIDATE_DELETE_NEEDS_NUMBER", "CANDIDATE_CSV_INVALID",
    "DRAFT_OPTION_INVALID", "SUGGESTION_NOT_FOUND", "STATUS_TRANSITION_INVALID", "PUBLISHED_URL_REQUIRED", "PUBLISHED_URL_INVALID",
    "CONFIRMATION_REQUIRED", "PUBLISH_CANCELLED", "PUBLISH_IN_PROGRESS", "PUBLISH_REPO_BUSY", "PUBLISH_ALREADY_PUSHED", "PUBLISH_CONTENT_CHANGED",
    "UPDATE_CHECK_FAILED", "UPDATE_SIGNATURE_INVALID", "UPDATE_DOWNGRADE_BLOCKED", "BACKUP_FAILED", "MIGRATION_FAILED", "MIGRATION_BLOCKED",
    "STORE_CORRUPT", "STORE_LOCKED", "STORE_RECOVERY_PENDING", "STORE_VERSION_UNSUPPORTED", "STORE_CONFLICT", "KEY_STORE_UNAVAILABLE",
    "KEY_TOO_LONG", "KEY_INVALID_SHAPE", "KEY_DUPLICATE", "KEY_ENTRY_LIMIT", "KEY_FAILOVER_TERMS_REQUIRED", "CONNECTION_NOT_FOUND",
    "CONNECTION_DELETE_NEEDS_NUMBER", "CONNECTIONS_FILE_INVALID", "QUOTA_STATE_INVALID", "KEYS_BUSY", "KEY_AUTH_FAILED", "REQUEST_INVALID",
    "REQUEST_BLOCKED", "SECRET_IN_TEXT_BLOCKED", "EXTERNAL_WRITE_DISABLED", "SECRET_SHAPE_FOUND", "ASSIST_UNAVAILABLE", "CORE_CODE_MISMATCH",
    "UNEXPECTED_ERROR", "TOPIC_STORE_CORRUPT", "TOPIC_STORE_VERSION_UNSUPPORTED", "TOPIC_STORE_LOCKED", "TOPIC_STORE_RECOVERY_PENDING",
    "TOPIC_FILE_INVALID", "TOPIC_CANDIDATE_NOT_FOUND", "TOPIC_CANDIDATE_AMBIGUOUS", "TOPIC_BACKUP_INVALID", "TOPIC_BACKUP_BLOCKED",
    "FULL_BACKUP_BLOCKED", "FULL_BACKUP_INVALID", "BACKUP_IN_PROGRESS", "RESTORE_FAILED", "DRAFT_SECRET_FOUND", "DRAFT_LIMIT", "DRAFT_CORRUPT",
))

# 문체를 바꾼 행(F028) — 명령줄 말투가 있던 행은 사용자 문구와 하실 일을 모두 '-요' 문체로 다시 썼다. 이름만 바로잡은 행(F041)은 말투를 그대로 둔다.
RESTYLED = frozenset((
    "PAGES_LOCAL_REPO_INVALID", "PAGES_LOCAL_REPO_DIRTY", "PAGES_LOCAL_REPO_NOT_MAIN", "PAGES_LOCAL_REPO_DIVERGED", "GIT_NOT_INSTALLED",
    "GIT_PUSH_AUTH", "GIT_IDENTITY_MISSING", "ACTIONS_RUN_FAILED", "FILE_WRITE_FAILED", "FILE_IN_USE", "DATA_DIR_UNSAFE", "SETTINGS_INVALID",
    "API_RATE_LIMITED", "PROFILE_INVALID", "NAVER_PROFILE_MISSING", "CHECK_FAILED", "DUPLICATE_SLUG", "DUPLICATE_CONTENT", "CANDIDATE_CORRUPT",
    "CANDIDATE_CONFIRM_REQUIRED", "CANDIDATE_AMBIGUOUS", "CANDIDATE_DELETE_NEEDS_NUMBER", "CANDIDATE_CSV_INVALID", "DRAFT_OPTION_INVALID",
    "SUGGESTION_NOT_FOUND", "STATUS_TRANSITION_INVALID", "CONFIRMATION_REQUIRED", "PUBLISH_CANCELLED", "PUBLISH_IN_PROGRESS", "PUBLISH_REPO_BUSY",
    "PUBLISH_ALREADY_PUSHED", "PUBLISH_CONTENT_CHANGED", "UPDATE_SIGNATURE_INVALID", "UPDATE_DOWNGRADE_BLOCKED", "STORE_RECOVERY_PENDING",
    "KEY_STORE_UNAVAILABLE", "KEY_DUPLICATE", "KEY_ENTRY_LIMIT", "KEY_FAILOVER_TERMS_REQUIRED", "CONNECTION_NOT_FOUND",
    "CONNECTION_DELETE_NEEDS_NUMBER", "CONNECTIONS_FILE_INVALID", "QUOTA_STATE_INVALID", "KEYS_BUSY", "KEY_AUTH_FAILED", "UNEXPECTED_ERROR",
    "TOPIC_STORE_CORRUPT", "TOPIC_STORE_RECOVERY_PENDING", "TOPIC_FILE_INVALID", "TOPIC_CANDIDATE_NOT_FOUND", "TOPIC_BACKUP_INVALID",
    "TOPIC_BACKUP_BLOCKED", "FULL_BACKUP_INVALID", "RESTORE_FAILED",
))

URL = re.compile(r"https?://\S*")
BACKTICK = re.compile(r"`([^`]*)`")
OPTION = re.compile(r"(?<![\w-])--[A-Za-z]")
SUBCOMMANDS = re.compile(r"(?<![\w-])(?:publish-pages|check-deploy|naver-profile|naver-package|naver-done|import-html|doctor|candidates|keys|topics|connect|git)(?![\w-])")
FILE_NAME = re.compile(r"[\w.-]+\.(?:json|bak|md|log|lock|py|db|exe)(?![\w])")
ENV_NAME = re.compile(r"[A-Z]{2,}_[A-Z_]{2,}")
DEV_WORDS = ("명령줄", "프롬프트", "터미널", "python", "세부", "다시 실행", "명령")
ALLOWED_ENGLISH = frozenset((
    "a", "ai", "b", "backups", "blogger", "chanceblog", "csv", "for", "git", "github", "html", "id", "json", "logs", "main", "onedrive", "pc",
    "releases", "utf-8", "vendor", "vpn", "windows",
))
# 따옴표 이름 가운데 화면 이름이 아닌 것과 그 이유(그 밖의 따옴표 이름은 실제 화면 문구 표에 있어야 한다)
QUOTED_NOT_UI = {
    "CSV UTF-8": "엑셀의 저장 형식 이름(외부 프로그램)",
    "CSV(쉼표로 분리)": "엑셀의 저장 형식 이름(외부 프로그램)",
    "건너뜀": "명령줄 제안 결과의 표시 이름(`candidates suggest` 출력) — 화면 이름이 아니다",
    "검색 1위 가능성": "결과를 약속하는 금지 표현의 예(화면 단추가 아니다)",
    "글 올리기(데스크톱 앱):": "앱이 만든 기록(commit)의 제목 모양을 인용한 것",
    "노출 확률": "결과를 약속하는 금지 표현의 예",
    "다른 이름으로 저장": "메모장·윈도 저장 창의 메뉴 이름(외부 프로그램)",
    "만든 초안": "저장 직전 검사가 알려 주는 위치 이름표(`content/saved_draft.py` 의 LABELS)",
    "무시하고 계속": "그런 단추는 없다고 알리는 문장 속 이름",
    "무시하고 저장": "그런 단추는 없다고 알리는 문장 속 이름",
    "번호": "후보 목록(명령줄 목록의 머리글·후보 상세의 '번호 …' 줄)의 칸 이름 — 정확히 같은 이름은 아니다",
    "상위노출 보장": "결과를 약속하는 금지 표현의 예",
    "수익 보장": "결과를 약속하는 금지 표현의 예",
    "올림(PUSHED) 상태인데 발행 기록 파일이 없다": "오류의 세부 줄에 나오는 문장을 인용한 것(명령줄 꼬리)",
}


# '화면'·'메뉴'·'단추'·'버튼'·'카드'·'탭' 이 들어간 말 — 하나하나 읽고 정한 쓰임이다(이름 있는 화면·단추를 가리키는 말이 아니라 '지금 보이는 화면' 같은 보통 말)
SCREEN_WORDS = {
    "화면에서": "DRAFT_SECRET_FOUND — '화면에서 고칠 수 없는 칸'(만든 초안 칸은 화면에서 고칠 수 없다는 사실)",
    "화면을": "CORE_CODE_MISMATCH — '이 화면을 그대로 알려 주세요'(지금 보이는 화면의 글을 알리라는 뜻)",
    "화면의": "STORE_CONFLICT — '지금 화면의 내용'(지금 보이는 화면의 입력 내용)",
}


# 옛 하실 일의 백틱 안 영문 조각(명령·옵션·파일 이름) — 지금도 전체 action(꼬리 포함)에 그대로 있어야 한다(명령줄 시험이 기대는 글)
OLD_COMMANDS = {
    "API_RATE_LIMITED": ["Retry-After"],
    "CANDIDATE_AMBIGUOUS": ["candidates list"],
    "CANDIDATE_CORRUPT": ["candidates delete 번호 --yes"],
    "CANDIDATE_CSV_INVALID": ["--blog"],
    "CANDIDATE_DELETE_NEEDS_NUMBER": ["candidates delete 번호앞8자 --yes", "candidates list", "candidates reject", "restore"],
    "CHECK_FAILED": ["RAW_HTML", "LIQUID", "title"],
    "CONFIRMATION_REQUIRED": ["--yes", "candidates delete 번호 --yes", "publish-pages"],
    "CONNECTIONS_FILE_INVALID": ["connections.json.bak", ".bak", "connections.json", "keys add"],
    "CONNECTION_DELETE_NEEDS_NUMBER": ["keys list", "keys remove 번호 --yes"],
    "CONNECTION_NOT_FOUND": ["keys list"],
    "DATA_DIR_UNSAFE": ["--data-dir", "CHANCEBLOG_DESKTOP_DATA"],
    "DRAFT_OPTION_INVALID": ["https://"],
    "DUPLICATE_CONTENT": ["list"],
    "DUPLICATE_SLUG": ["list", "_posts", "review"],
    "FILE_WRITE_FAILED": [".git", "chanceblog-desktop-publish.lock", "--data-dir"],
    "FULL_BACKUP_INVALID": ["backups"],
    "GIT_IDENTITY_MISSING": ["git config --global user.name \"표시할 이름\"", "git config --global user.email \"GitHub 에 등록한 이메일 또는 noreply 주소\""],
    "GIT_NOT_INSTALLED": ["MIGRATION.md"],
    "GIT_PUSH_AUTH": ["git push"],
    "KEY_AUTH_FAILED": ["keys remove", "keys add"],
    "KEY_DUPLICATE": ["keys list"],
    "KEY_ENTRY_LIMIT": ["keys remove 번호 --yes"],
    "KEY_FAILOVER_TERMS_REQUIRED": ["--i-understand-terms"],
    "KEY_STORE_UNAVAILABLE": ["keys list"],
    "NAVER_PROFILE_MISSING": ["naver-profile set 블로그구분 --name 표시명 --url https://blog.naver.com/블로그아이디", "naver_a", "naver_b"],
    "PAGES_LOCAL_REPO_DIVERGED": ["publish-pages 글번호 --yes", "--cancel --yes", "review", "--data-dir", "doctor"],
    "PAGES_LOCAL_REPO_INVALID": ["git clone https://github.com/shine88pc/chanceblog.git", "git config --global --add safe.directory 그폴더경로"],
    "PAGES_LOCAL_REPO_NOT_MAIN": ["git switch main"],
    "PROFILE_INVALID": ["naver-profile set 블로그구분 --옵션 값", "https://blog.naver.com/블로그아이디"],
    "PUBLISH_ALREADY_PUSHED": ["--cancel", "publish-pages 글번호 --yes", "check-deploy 글번호", "check-deploy", "delete 글번호 --yes"],
    "PUBLISH_CANCELLED": ["review"],
    "PUBLISH_CONTENT_CHANGED": ["publish-pages 글번호 --cancel --yes", "review"],
    "PUBLISH_IN_PROGRESS": ["list"],
    "PUBLISH_REPO_BUSY": ["list"],
    "QUOTA_STATE_INVALID": ["quota_state.json.bak", "keys usage"],
    "RESTORE_FAILED": ["backups/before-restore"],
    "SETTINGS_INVALID": ["check-deploy", "delete 글번호 --yes"],
    "STATUS_TRANSITION_INVALID": ["check-deploy 글번호", "--cancel --yes"],
    "STORE_RECOVERY_PENDING": ["list", "candidates add …", "candidates list", "candidates show", "doctor", "-journal"],
    "SUGGESTION_NOT_FOUND": ["candidates suggest", "--blog", "--count", "--month", "--type", "--add"],
    "TOPIC_BACKUP_BLOCKED": ["topics check", "topics init --yes", "topics status"],
    "TOPIC_BACKUP_INVALID": ["topics backup", "topic-날짜-시각"],
    "TOPIC_CANDIDATE_NOT_FOUND": ["topics list", "topics generate --yes"],
    "TOPIC_FILE_INVALID": ["topics restore", ".bad-…", "topics init --yes"],
    "TOPIC_STORE_CORRUPT": ["topics restore --latest --yes", ".bad-…", "topics init --yes"],
    "TOPIC_STORE_RECOVERY_PENDING": ["topics init --yes", "-journal"],
    "UNEXPECTED_ERROR": ["--debug", "logs/errors.log"],
    "UPDATE_DOWNGRADE_BLOCKED": ["RELEASE.md"],
    "UPDATE_SIGNATURE_INVALID": ["SHA256SUMS"],
}

# 일부러 뺀 조각과 이유는 DECISIONS D-544 에 있다
DROPPED_ON_PURPOSE = {
    "KEYS_BUSY": ["keys"],
}


def card_text(code):
    """화면 카드에 나가는 글(자리표시자는 그대로) — 사용자 문구 + 하실 일의 앞부분."""
    info = CATALOG[code]
    return (info.message + " " + card_action(info.action)).replace("**", "")


def card_problems(text):
    """카드 글에서 개발자 말투를 찾는다 — 없으면 빈 목록."""
    found = []
    for span in BACKTICK.findall(text):
        if re.search("[A-Za-z]", span) and "://" not in span and BS not in span:
            found.append(f"백틱 안의 영문 `{span}`")
    for pattern, name in ((OPTION, "옵션 이름"), (SUBCOMMANDS, "명령 이름"), (FILE_NAME, "파일 이름"), (ENV_NAME, "환경 변수 이름")):
        for hit in pattern.findall(text):
            found.append(f"{name} {hit!r}")
    if "](" in text:
        found.append("마크다운 링크")
    if "%" in text and re.search(r"%[A-Za-z_]+%", text):
        found.append("%환경변수%")
    lowered = text.lower()
    for word in DEV_WORDS:
        if word in lowered:
            found.append(f"개발자 말 {word!r}")
    plain = BACKTICK.sub(lambda match: " " if re.search("[A-Za-z]", match.group(1)) else match.group(0), URL.sub(" ", text))
    for word in re.findall(r"[A-Za-z][A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*", plain):
        if word.lower() not in ALLOWED_ENGLISH:
            found.append(f"허용 목록에 없는 영어 낱말 {word!r}")
    return found


def ui_names():
    """실제 화면에 있는 이름 — 화면 문구 표(T)의 글 전부, 메뉴, 후보 상태 이름."""
    names = {str(value) for value in T.values()}
    names |= {T[label] for _key, label, _icon in app_state.NAV}
    names |= set(candidate_content.STATUS_KO.values())
    return names


class CardsHaveNoDeveloperTalkTest(unittest.TestCase):
    def test_the_fixed_code_list_is_still_in_the_catalog_and_nothing_was_renamed(self):
        self.assertEqual(len(CARD_CODES), 105)
        self.assertLessEqual(CARD_CODES, set(CATALOG), "L4 가 덮는 코드 이름은 바꾸거나 지우지 않는다")
        self.assertLessEqual(RESTYLED, CARD_CODES)

    def test_no_card_text_has_a_command_an_option_a_file_name_or_developer_words(self):
        for code in sorted(CARD_CODES):
            with self.subTest(code=code):
                self.assertEqual(card_problems(card_text(code)), [], f"{code} 카드 글에 개발자 말투가 있다 — 명령줄 안내는 `{CLI_TAIL_LABEL}` 꼬리로 보낸다")

    def test_the_checker_itself_catches_each_kind_of_developer_talk(self):
        cases = {
            "백틱 명령": "지우려면 `keys remove 번호 --yes` 로 지워요.",
            "옵션 이름": "그 명령에 --yes 를 붙여요.",
            "명령 이름": "publish-pages 로 다시 올려요.",
            "파일 이름": "connections.json 을 되돌려요.",
            "환경 변수": "CHANCEBLOG_DESKTOP_DATA 를 바꿔요.",
            "마크다운 링크": "자세한 것은 [안내](MIGRATION.md) 에 있어요.",
            "터미널": "터미널에서 한 번 해 주세요.",
            "세부": "세부에 적힌 대로 해 주세요.",
            "다시 실행": "같은 것을 다시 실행해 주세요.",
            "영어 낱말": "그 폴더에서 foobarbaz 를 켜 주세요.",
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertTrue(card_problems(text), f"{name}: 못 찾았다")
        for fine in ("설정 → 백업·복원에서 되돌려 주세요.", "첫 줄에 `주제`·`핵심 키워드` 같은 열 이름을 두세요.", "https://blog.naver.com/아이디 로 시작해요.", "Windows 자격 증명 관리자에 있어요.", "영문·숫자와 `_ - + / = . ~ :` 만 써요."):
            with self.subTest(fine=fine):
                self.assertEqual(card_problems(fine), [])

    def test_every_tail_is_labelled_comes_after_a_plain_part_and_ends_as_a_sentence(self):
        for code in sorted(CARD_CODES):
            action = CATALOG[code].action
            with self.subTest(code=code):
                self.assertNotIn(CLI_TAIL_LABEL, CATALOG[code].message, "꼬리는 하실 일 칸에만 둔다")
                self.assertLessEqual(action.count(CLI_TAIL_LABEL), 1, "꼬리 이름표는 한 번만")
                head, found, tail = action.partition(CLI_TAIL_LABEL)
                if found:
                    self.assertTrue(head.strip(), "꼬리 앞에 쉬운 안내가 있어야 한다")
                    self.assertTrue(head.endswith(". "), "쉬운 안내는 문장으로 끝나고 이름표 앞에 빈칸 하나")
                    self.assertTrue(tail.startswith(" ") and tail.strip().endswith("."), "꼬리는 이름표 뒤 빈칸으로 시작해 문장으로 끝난다")
                    self.assertEqual(card_action(action), head.rstrip())
                else:
                    self.assertEqual(card_action(action), action)

    def test_the_document_explains_the_label_where_the_table_is_introduced(self):
        intro = DOC.split("\n## 1.")[0]
        self.assertIn(CLI_TAIL_LABEL, intro)
        self.assertIn("화면 카드에는 나오지 않고 명령줄 출력에는 그대로 나옵니다", intro)

    def test_the_old_commands_are_all_still_in_the_command_line_output_text(self):
        """명령은 지우지 않고 꼬리로 옮겼다 — 옛 하실 일의 백틱 안 영문 조각(명령·옵션·파일 이름)이 전체 action 에 그대로 있다(명령줄 시험이 기대는 글)."""
        for code, spans in OLD_COMMANDS.items():
            for span in spans:
                with self.subTest(code=code, span=span):
                    self.assertIn(span, CATALOG[code].action)

    def test_the_commands_that_were_dropped_on_purpose_are_exactly_the_listed_ones(self):
        for code, spans in DROPPED_ON_PURPOSE.items():
            for span in spans:
                with self.subTest(code=code, span=span):
                    self.assertNotIn(span, CATALOG[code].action)


class CardActionTest(unittest.TestCase):
    def test_it_cuts_at_the_label_and_keeps_the_plain_part(self):
        self.assertEqual(card_action(f"앞부분이에요. {CLI_TAIL_LABEL} `x` 로 해요."), "앞부분이에요.")
        self.assertEqual(card_action("꼬리가 없는 글이에요."), "꼬리가 없는 글이에요.")
        self.assertEqual(card_action(f"{CLI_TAIL_LABEL} 앞부분이 없어요."), f"{CLI_TAIL_LABEL} 앞부분이 없어요.", "앞부분이 없으면 빈 안내를 내지 않고 전체를 그대로")
        self.assertEqual(card_action(f"하나. {CLI_TAIL_LABEL} 둘. {CLI_TAIL_LABEL} 셋."), "하나.", "이름표가 둘이면 처음 것에서 자른다")

    def test_render_fills_both_the_full_action_and_the_card_action(self):
        shown = render("KEY_ENTRY_LIMIT", {"용도": "이미지", "개수": 3})
        self.assertEqual(shown.message, "「이미지」에는 키 항목을 「3」개까지만 둘 수 있어요.")
        self.assertEqual(shown.card_action, "쓰지 않는 항목을 지운 뒤 다시 더해 주세요.")
        self.assertTrue(shown.action.startswith(shown.card_action))
        self.assertIn("`keys remove 번호 --yes`", shown.action)
        self.assertNotIn(CLI_TAIL_LABEL, shown.card_action)

    def test_a_slot_value_that_looks_like_the_label_does_not_cut_the_card_text(self):
        """카드용 글은 값을 넣기 **전** 문장에서 자른다 — 값이 이름표를 흉내 내도 카드 글이 중간에서 잘리지 않는다."""
        shown = render("PAGES_LOCAL_REPO_NOT_MAIN", {"브랜치": f"x {CLI_TAIL_LABEL} y"})
        self.assertEqual(shown.card_action, "그 폴더에서 main 브랜치로 바꾼 뒤 다시 시도해 주세요. 앱은 브랜치를 마음대로 바꾸지 않아요.")
        shown = render("DATA_DIR_UNSAFE", {"경로": f"C:{BS}a {CLI_TAIL_LABEL} b"})
        self.assertTrue(shown.card_action.endswith("앱을 다시 열어 주세요."))

    def test_the_command_line_output_prints_the_whole_action_with_the_tail(self):
        """명령줄(`error_lines`)은 카드와 달리 전체 하실 일을 그대로 찍는다 — 카드만 줄이고 명령줄 사용자의 안내는 그대로다."""
        lines = service_format.error_lines(AppError("KEY_ENTRY_LIMIT", {"용도": "이미지", "개수": 3}))
        action = next(line for line in lines if line.startswith("  하실 일: "))
        self.assertIn(CLI_TAIL_LABEL, action)
        self.assertIn("`keys remove 번호 --yes`", action)
        self.assertEqual(action, "  하실 일: " + render("KEY_ENTRY_LIMIT", {"용도": "이미지", "개수": 3}).action)

    def test_every_code_has_a_card_action_and_the_unknown_code_does_too(self):
        for code in CATALOG:
            with self.subTest(code=code):
                shown = render(code)
                self.assertTrue(shown.card_action.strip())
                self.assertIn(shown.card_action[:20], shown.action)
        self.assertEqual(render("NOT_A_CODE").card_action, card_action(CATALOG["UNEXPECTED_ERROR"].action).replace("**", ""))


class TheScreenCardUsesTheCardTextTest(unittest.TestCase):
    def failure(self, code, slots=None):
        return adapters.failure_from(AppError(code, slots))

    def test_the_failure_shown_on_a_card_has_no_tail_and_no_command(self):
        for code in sorted(CARD_CODES - {"FILE_WRITE_FAILED", "FILE_IN_USE"}):          # 앞의 둘은 화면용 문장으로 따로 바꾼다(WRITE_WORDED_CODES)
            with self.subTest(code=code):
                slots = {name: f"{name} 값" for name in CATALOG[code].slots}
                shown = self.failure(code, slots).user_message
                self.assertNotIn(CLI_TAIL_LABEL, shown)
                self.assertEqual(card_problems(re.sub("「[^」]*」", "「값」", shown)), [], shown)

    def test_a_candidate_that_cannot_be_read_is_explained_in_plain_words_and_names_the_real_backup_card(self):
        shown = self.failure("CANDIDATE_CORRUPT", {"번호": "bad00000"}).user_message
        self.assertIn("후보 번호 「bad00000」", shown)
        self.assertIn("설정 → 백업·복원", shown)
        self.assertNotIn("candidates", shown)
        self.assertNotIn("--yes", shown)

    def test_the_command_line_still_gets_everything(self):
        error = AppError("CANDIDATE_CORRUPT", {"번호": "bad00000"})
        full = render(error.code, error.slots).action
        self.assertIn("candidates delete 번호 --yes", full)
        self.assertIn(CLI_TAIL_LABEL, full)


class TheNamesAMessagePointsToExistTest(unittest.TestCase):
    PARTICLES = ("", "에서", "에서는", "에서도", "으로", "로", "에", "에는", "을", "를", "은", "는", "이", "가", "의", "와", "과", "도", "만")

    def references(self, text):
        """문구가 가리키는 이름 — 화살표 길의 마디와 따옴표 이름."""
        arrows = [part.strip() for match in re.finditer(r"([가-힣A-Za-z0-9·]+(?: → [가-힣A-Za-z0-9·]+)+)", text) for part in match.group(1).split(" → ")]
        quoted = [name.strip() for name in re.findall(r"'([^']{1,40})'", text)]
        return arrows, quoted

    def is_real(self, segment, real):
        """화살표 마디(`백업·복원에서`)가 실제 이름(+조사)인가 — `백업·복구에서` 가 `백업` 이름 하나만으로 통과하지 않게, 이름 뒤에는 조사만 올 수 있다."""
        return any(segment.startswith(name) and segment[len(name):] in self.PARTICLES for name in real if name)

    def test_every_arrow_path_and_quoted_name_is_a_real_screen_name_or_a_listed_exception(self):
        real = ui_names()
        seen = 0
        for code in sorted(CARD_CODES):
            info = CATALOG[code]
            arrows, quoted = self.references(info.message + " " + info.action)
            for name in arrows:
                seen += 1
                with self.subTest(code=code, arrow=name):
                    self.assertTrue(self.is_real(name, real), f"{code}: 화살표 길의 '{name}' 이 실제 화면에 없다")
            for name in quoted:
                seen += 1
                with self.subTest(code=code, quoted=name):
                    self.assertTrue(name in real or name in QUOTED_NOT_UI, f"{code}: '{name}' 이 실제 화면 문구에도 예외 목록에도 없다")
        self.assertGreaterEqual(seen, 25, "이름을 찾는 규칙이 깨졌다 — 이름을 한 개도 못 찾았다")

    def test_the_exception_list_has_no_stale_entry_and_no_real_screen_name(self):
        real = ui_names()
        text = " ".join(info.message + " " + info.action for info in CATALOG.values())
        for name, reason in QUOTED_NOT_UI.items():
            with self.subTest(name=name):
                self.assertIn(f"'{name}'", text, "더는 문구에 없는 예외다 — 목록에서 뺀다")
                self.assertTrue(reason.strip())
                self.assertNotIn(name, real, "실제 화면 이름이 됐다 — 예외가 아니다")

    def test_the_real_names_the_texts_rely_on_are_in_the_screen_text_table(self):
        """화면 쪽 이름이 바뀌면 문구도 같이 고치게 한다 — 문구가 기대는 이름의 정본."""
        expected = {
            "설정": T["nav_settings"], "백업·복원": T["backup_title"], "연결 관리": T["conn_title"], "블로그 관리": T["nav_blogs"],
            "다시 시도": T["retry"], "진단 정보 보기": T["diag_show"], "복원 직전 사본": T["backup_kind_safety"],
            "연결 확인 필요": T["status_needs_check"], "인증 정보 오류": T["status_auth_error"], "표시 이름": T["bf_label_display_name"], "블로그 ID 또는 주소": T["bf_label_blog_ref"],
            "저장": T["drf_save"], "저장한 초안": T["drf_saved_title"], "다시 만들기": T["drf_remake"], "초안 작성": T["nav_draft"], "열기": T["drf_saved_open"], "지우기": T["drf_saved_delete"],
            "ChanceBlog Desktop": T["window_title"],
        }
        for name, shown in expected.items():
            with self.subTest(name=name):
                self.assertEqual(name, shown)
        self.assertEqual(set(candidate_content.STATUS_KO.values()), {"새 후보", "검토 중", "선택됨", "보류", "제외"})
        self.assertIn(single_instance.ALREADY_OPEN_TEXT.split("\n")[0].split("{name} 이 ")[1].rstrip("."), DOC, "문서 14절이 인용한 안내 상자 글이 실제 글과 다르다")

    def test_the_known_wrong_names_do_not_come_back(self):
        wrong = ("설정 → 백업·복구", "Blogger 연결", "설정의 블로그 선택", "글 쓰기 화면", "직접 승인**을 눌러", "직접 승인을 눌러", "설정에서 chanceblog 를 받아 둔 폴더", "'chanceblog 로컬 저장소' 칸", "화면의 세부", "화면의 링크")
        catalog_text = "\n".join(" ".join((info.when, info.message, info.action)) for info in CATALOG.values())
        for name in wrong:
            with self.subTest(name=name):
                self.assertNotIn(name, catalog_text)
                self.assertNotIn(name, DOC)
                self.assertNotIn(name, MIGRATION)

    def test_every_word_that_points_at_a_screen_part_is_a_vetted_plain_use(self):
        """'화면'·'메뉴'·'단추'·'카드'·'탭' 이 든 말은 사람이 읽고 정한 쓰임뿐이다 — 새 말이 생기면 이유와 함께 목록에 더한다(없는 단추·화면을 가리키는 말이 조용히 늘지 않게)."""
        found = {}
        for code in sorted(CARD_CODES):
            info = CATALOG[code]
            for token in re.findall(r"[^\s()·,.]*(?:화면|메뉴|단추|버튼|카드|탭)[^\s()·,.]*", (info.message + " " + info.action).replace("**", "")):
                found.setdefault(token, []).append(code)
        self.assertEqual(set(found), set(SCREEN_WORDS), "새로 생기거나 사라진 화면 낱말이 있다 — 읽어 보고 SCREEN_WORDS 를 고친다")
        for token, reason in SCREEN_WORDS.items():
            self.assertTrue(reason.strip() and found[token][0] in reason, token)

    def test_the_card_refers_to_the_diagnostic_info_by_its_real_button_name(self):
        self.assertIn(f"'{T['diag_show']}'", CATALOG["UNEXPECTED_ERROR"].message + CATALOG["UNEXPECTED_ERROR"].action)


class RestyledRowsAreInPoliteStyleTest(unittest.TestCase):
    def test_a_restyled_row_has_no_formal_endings_left_in_the_message_or_the_action(self):
        for code in sorted(RESTYLED):
            info = CATALOG[code]
            with self.subTest(code=code):
                text = (info.message + " " + info.action).replace("**", "")
                self.assertNotIn("니다", text, f"{code}: 합니다체가 남았다")
                self.assertNotRegex(text, r"(?:하세요|십시오)\b", f"{code}: 명령조가 남았다")

    def test_the_terms_notice_in_the_code_is_in_the_same_style_as_its_row(self):
        from chanceblog_desktop.service import connections
        self.assertNotIn("니다", connections.TERMS_NOTICE)
        self.assertIn(connections.TERMS_NOTICE, CATALOG["KEY_FAILOVER_TERMS_REQUIRED"].action)


if __name__ == "__main__":
    unittest.main()
