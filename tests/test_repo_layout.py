"""저장소 뼈대 시험 — 문서·설정이 서로 어긋나거나 비밀이 새지 않게, 운영자가 정한 범위가 문서에서 빠지지 않게 잡는다. 네트워크·시크릿 없이 돈다.

코드보다 먼저 문서·규칙을 두었으므로 시험이 지키는 것은 다음이다:
  1) 필요한 파일이 있다(AGENTS.md·CLAUDE.md·docs 7개·CI·VERSION·CHANGELOG·.env.example).
  2) 문서 속 상대 링크가 실제 파일을 가리키고, 문서가 부르는 결정 번호(D-nn)가 `docs/DECISIONS.md` 에 있다.
  3) VERSION 이 의미 있는 버전 번호이고 CHANGELOG 맨 위와 같다.
  4) `.gitignore` 가 비밀·사용자 데이터·빌드 산출물을 막고, `.env.example` 에는 변수 이름만 있으며, 추적되는 글에 키 모양 문자열이 없다.
  5) 운영자 결정(2026-10-30)이 문서에 남아 있다 — AI Router 제외·선택 보조 AI 기본 꺼짐·GitHub Models 후보 제외·티스토리 격리·AI 없이 되는 기능 목록·규칙 기반 오류 안내.
  6) 오류 안내 문서(TROUBLESHOOTING)의 오류 코드 표가 올바른 모양이고 코드가 겹치지 않는다.
  7) CI 워크플로가 읽기 전용이고 3.10 과 3.12 를 둘 다 돌린다.
  8) 비밀 모양 검사가 위 여섯 가지(KEY_SHAPES)에 그치지 않는다 — 정본 `vendor/pipeline/secret_patterns.py` 의 패턴 전체로 src·docs·.github·packaging·scripts·최상위 파일을 훑어도 걸리는 것이 없다(F066).
"""
import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ("ARCHITECTURE", "DECISIONS", "MIGRATION", "PLATFORM_POLICY", "RELEASE", "SECURITY", "TROUBLESHOOTING")
TOP = ("README.md", "AGENTS.md", "CLAUDE.md", "CHANGELOG.md", "VERSION", ".gitignore", ".env.example", ".github/workflows/ci.yml")
KEY_SHAPES = (
    r"AIza[0-9A-Za-z_-]{35}",                              # 구글·Gemini 키
    r"(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}",   # GitHub 토큰
    r"[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}",                   # 텔레그램 봇 토큰
    r"GOCSPX-[A-Za-z0-9_-]{20,}",                          # 구글 OAuth 클라이언트 비밀
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",                 # 비공개 키 블록
    r"sk-[A-Za-z0-9]{32,}|gsk_[A-Za-z0-9]{40,}",           # 기타 AI 서비스 키
)
# 정본 패턴 전체(vendor/pipeline/secret_patterns.py)로 훑는 곳(F066). 위 KEY_SHAPES 는 여섯 가지뿐이라 새 구글 키(`AQ.`)·구글 접근 토큰(`ya29.`)·Slack·AWS 키·키/토큰 할당 같은 것을 놓친다.
# tests/ 는 일부러 넣은 가짜 값(`client_secret` 예시·AWS 문서의 예시 키 …)이 있어 이 훑기에서 빼고 위 여섯 가지로만 훑는다(아래 SecretHygieneTest 가 그대로 한다).
# 예외는 파일 하나를 이름·이유와 함께 적는다 — 목록을 늘리려면 이유를 적고, 필요 없어지면 시험이 알려 주니 뺀다(실제 노출을 가리는 넓은 허용 규칙은 두지 않는다).
CANONICAL_SCAN_DIRS = ("src", "docs", ".github", "packaging", "scripts")
CANONICAL_SCAN_EXEMPT = {"scripts/ui_capture.py": "화면 사진용 가짜 연결 값(예시 비밀 문자열)이 든다"}
# 훑는 글 파일의 확장자 — 문서·설정·코드에 더해 html·sh·bat·cfg·ini·csv·xml 까지(스크립트·설정·표 파일에도 키가 붙을 수 있다)
TEXT_SUFFIXES = {".md", ".yml", ".yaml", ".py", ".txt", ".json", ".toml", ".example", ".html", ".sh", ".bat", ".cfg", ".ini", ".csv", ".xml"}
# 운영자가 'AI 없이 반드시 동작해야 한다'고 정한 기능(2026-10-30) — ARCHITECTURE §8 에 모두 적혀 있어야 한다
NO_AI_FEATURES = (
    "콘텐츠 직접 작성·수정", "기존 원고 불러오기", "Markdown·HTML 변환", "플랫폼별 미리보기", "GitHub Pages 게시물 생성·배포", "Blogger 초안 생성·수정",
    "네이버 A/B 발행 패키지 생성", "제목·본문·태그 복사", "네이버 글쓰기 페이지 열기", "이미지 파일과 삽입 위치 관리", "발행 상태와 URL 기록", "예약 작업",
    "배포 성공·실패 감지", "규칙 기반 오류 안내", "작업 로그", "백업·복구", "프로그램 버전 확인·업데이트",
)
# 운영자가 예로 든 규칙 기반 오류 안내 — 오류 코드가 TROUBLESHOOTING 에 있어야 한다
REQUIRED_ERROR_CODES = ("BLOGGER_AUTH_EXPIRED", "GIT_PUSH_AUTH", "GIT_PUSH_NETWORK", "ACTIONS_RUN_FAILED", "FILE_WRITE_FAILED", "API_RATE_LIMITED", "ASSIST_UNAVAILABLE")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def section(text, heading):
    """`heading` 으로 시작하는 `## ` 절의 본문(다음 `## ` 절 앞까지). 절이 없으면 그 자리에서 시험이 실패한다."""
    start = text.find("\n" + heading)
    if start == -1:
        raise AssertionError(f"절이 없다: {heading}")
    body = text[start + 1:]
    end = body.find("\n## ", len(heading))
    return body if end == -1 else body[:end]


def text_files(root=ROOT):
    skip = {".git", "vendor", "__pycache__", ".venv"}
    for path in root.rglob("*"):
        if path.is_file() and not (set(path.relative_to(root).parts) & skip) and path.suffix in TEXT_SUFFIXES:
            yield path


def canonical_secret_patterns():
    """정본 SECRET_PATTERNS 의 [(이름, 패턴)] — vendor 파일은 읽기만 하고 파일 경로로 따로 불러온다(sys.path 와 다른 시험이 쓰는 `pipeline` 모듈을 건드리지 않는다)."""
    spec = importlib.util.spec_from_file_location("_layout_secret_patterns", ROOT / "vendor" / "pipeline" / "secret_patterns.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.SECRET_PATTERNS)


def canonical_hits(root, patterns, exempt=CANONICAL_SCAN_EXEMPT):
    """정본 훑기 대상(최상위 파일과 CANONICAL_SCAN_DIRS 아래, 예외 제외)에서 패턴에 걸리는 곳의 `경로:줄 이름` 목록 — 걸린 값은 담지 않는다(실패 출력에도 비밀이 새지 않게)."""
    found = []
    for path in text_files(root):
        rel = path.relative_to(root).as_posix()
        if ("/" in rel and rel.split("/")[0] not in CANONICAL_SCAN_DIRS) or rel in exempt:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for label, pattern in patterns:
            match = pattern.search(text)
            if match:
                found.append(f"{rel}:{text.count(chr(10), 0, match.start()) + 1} {label}")
    return found


class RequiredFilesTest(unittest.TestCase):
    def test_the_top_level_files_and_the_seven_docs_exist(self):
        missing = [rel for rel in TOP if not (ROOT / rel).is_file()]
        missing += [f"docs/{name}.md" for name in DOCS if not (ROOT / "docs" / f"{name}.md").is_file()]
        self.assertEqual(missing, [])

    def test_claude_md_points_at_agents_md_and_agents_md_names_the_other_repo(self):
        self.assertIn("AGENTS.md", read("CLAUDE.md"))
        agents = read("AGENTS.md")
        self.assertIn("shine88pc/chanceblog", agents)                  # 규칙의 정본과 운영자 호출 채널은 다른 저장소에 있다
        self.assertIn("ai/claude/**", agents)

    def test_readme_lists_every_doc(self):
        readme = read("README.md")
        for name in DOCS:
            self.assertIn(f"docs/{name}.md", readme, name)


class LinkAndDecisionTest(unittest.TestCase):
    LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

    def test_relative_markdown_links_point_at_real_files(self):
        broken = []
        for path in text_files():
            if path.suffix != ".md":
                continue
            for target in self.LINK.findall(path.read_text(encoding="utf-8")):
                if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#") or target.startswith("../"):
                    continue                                              # 주소·같은 문서 안 이동·GitHub 화면 상대 경로(릴리스 등)는 건너뛴다
                resolved = (path.parent / target.split("#", 1)[0]).resolve()
                if not resolved.exists():
                    broken.append(f"{path.relative_to(ROOT)} -> {target}")
        self.assertEqual(broken, [])

    def test_every_decision_number_used_in_docs_is_defined_in_the_decision_log(self):
        defined = set(re.findall(r"^\| (D-\d{2}) \|", read("docs/DECISIONS.md"), re.M))
        self.assertGreaterEqual(len(defined), 19)
        used = set()
        for path in text_files():
            if path.suffix == ".md":
                used |= set(re.findall(r"\bD-\d{2}\b", path.read_text(encoding="utf-8")))
        self.assertEqual(sorted(used - defined), [], "문서가 부르는데 결정 기록에 없는 번호")


class WorkflowPinningTest(unittest.TestCase):
    def test_every_action_in_the_workflows_is_pinned_to_a_full_commit_sha(self):
        """태그(@v4)는 나중에 다른 코드를 가리키게 바뀔 수 있다 — 전체 커밋 SHA 로 고정한다(docs/SECURITY.md §4)."""
        uses = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.M)
        found = 0
        for path in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
            for ref in uses.findall(path.read_text(encoding="utf-8")):
                if ref.startswith("./"):
                    continue
                found += 1
                with self.subTest(file=path.name, action=ref):
                    self.assertRegex(ref, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
        self.assertGreaterEqual(found, 2, "액션을 찾지 못했다 — 이 시험의 찾기 규칙이 깨졌다")

    def test_the_pin_check_rejects_a_tag(self):
        uses = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.M)
        self.assertEqual(uses.findall("      - uses: actions/checkout@v4\n"), ["actions/checkout@v4"])
        self.assertIsNone(re.match(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$", "actions/checkout@v4"))
        self.assertIsNotNone(re.match(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$", "actions/checkout@" + "a" * 40))


class VersionTest(unittest.TestCase):
    SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?$")

    def test_version_is_semver_and_matches_the_top_changelog_entry(self):
        version = read("VERSION").strip()
        self.assertRegex(version, self.SEMVER)
        match = re.search(r"^## \[([^\]]+)\]", read("CHANGELOG.md"), re.M)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), version)


class SecretHygieneTest(unittest.TestCase):
    def test_gitignore_blocks_secrets_user_data_and_build_output(self):
        lines = {line.strip() for line in read(".gitignore").splitlines()}
        for needle in (".env", "*.pem", "*.key", "*.pfx", "client_secret*.json", "token*.json", "*.sqlite", "*.db", "dist/", "build/", ".venv/", "update_signing_key*",
                       ".git-credentials", ".netrc", "secret*.json", "*.jks"):
            self.assertIn(needle, lines, needle)
        self.assertIn("!.env.example", lines)                             # 변수 이름만 있는 예시는 올린다

    def test_env_example_has_only_variable_names_and_no_values(self):
        names = []
        for number, line in enumerate(read(".env.example").splitlines(), 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=", line.strip())
            self.assertIsNotNone(match, f".env.example {number}행에 값이 있거나 형식이 틀립니다: {line[:30]!r}")
            names.append(match.group(1))
        self.assertIn("CHANCEBLOG_LOCAL_REPO", names)                     # 연결할 chanceblog 로컬 저장소 경로
        self.assertIn("GEMINI_API_KEY", names)                            # 선택 기능이지만 이름은 둔다
        self.assertEqual(len(names), len(set(names)))

    def test_no_tracked_text_file_contains_a_key_shaped_string(self):
        pattern = re.compile("|".join(KEY_SHAPES))
        hits = [str(path.relative_to(ROOT)) for path in text_files() if pattern.search(path.read_text(encoding="utf-8", errors="replace"))]
        self.assertEqual(hits, [])

    def test_no_tracked_text_file_contains_a_personal_email_address(self):
        """AGENTS.md 규칙 2 — 개인 이메일을 저장소에 올리지 않는다(GitHub noreply 주소·예시 도메인은 괜찮다)."""
        pattern = re.compile(r"[\w.+-]+@(?:gmail|googlemail|naver|daum|hanmail|kakao|outlook|hotmail|yahoo|icloud)\.[a-z.]+", re.I)
        hits = [str(path.relative_to(ROOT)) for path in text_files() if pattern.search(path.read_text(encoding="utf-8", errors="replace"))]
        self.assertEqual(hits, [])

    def test_the_secret_scan_would_catch_a_planted_key(self):
        """위 검사가 실제로 잡는지 — 가짜 키 모양(조합해서 만든 값이라 저장소에는 키 문자열이 없다)을 넣어 본다."""
        pattern = re.compile("|".join(KEY_SHAPES))
        fake = "AI" + "za" + "A" * 35
        self.assertIsNotNone(pattern.search(f"key = {fake}"))
        self.assertIsNone(pattern.search("key = <여기에 키를 넣지 않는다>"))


class CanonicalSecretScanTest(unittest.TestCase):
    """정본 비밀 패턴(`vendor/pipeline/secret_patterns.py`) 전체로 훑는다(F066) — 위 여섯 가지가 놓치는 새 구글 키·구글 접근 토큰·Slack·AWS 키·키/토큰 할당까지.
    가짜 값은 시험 안에서 조각을 이어 만든 `CANARY_` 로 시작하는 값이라 저장소에는 키 문자열이 없다."""

    @classmethod
    def setUpClass(cls):
        cls.patterns = canonical_secret_patterns()

    def test_the_canonical_patterns_were_loaded_and_are_not_fewer_than_when_this_scan_was_written(self):
        self.assertGreaterEqual(len(self.patterns), 14, "정본의 패턴이 줄었거나 불러오기가 깨졌다 — 아무것도 못 잡는 훑기가 초록이 되면 안 된다")
        for label, pattern in self.patterns:
            self.assertTrue(label and hasattr(pattern, "search"), label)

    def test_no_file_in_the_scanned_places_contains_a_canonical_secret_shape(self):
        self.assertEqual(canonical_hits(ROOT, self.patterns), [], "정본 비밀 모양에 걸린 곳(값은 적지 않는다) — 지우거나, 예시라면 조각을 이어 만든다")

    def test_the_canonical_patterns_catch_planted_values_of_the_kinds_the_six_shapes_miss(self):
        planted = {
            "Google API 키(새 형식)": "CANARY_" + "AQ" + "." + "x" * 45,
            "Google access token": "CANARY_TOKEN=" + "ya" + "29." + "y" * 35,
            "Google refresh token": "CANARY_TOKEN=" + "1/" + "/0" + "z" * 45,
            "Slack 토큰": "CANARY_TOKEN=" + "xo" + "xb-" + "1234567890" * 2,
            "AWS 액세스 키": "CANARY_KEY=" + "AK" + "IA" + "A" * 16,
            "키/토큰 할당": 'CANARY_LINE: api_key = "' + "k" * 30 + '"',
        }
        for label, text in planted.items():
            with self.subTest(kind=label):
                caught = {name for name, pattern in self.patterns if pattern.search(text)}
                self.assertIn(label, caught, f"{label} 모양을 정본 패턴이 못 잡았다(잡은 것: {sorted(caught)})")

    def test_the_scan_reaches_top_level_files_the_listed_folders_and_the_wider_suffixes_but_not_tests_or_the_exempt_file(self):
        fake = "CANARY_" + "AQ" + "." + "x" * 45
        reached = ("README.md", "src/a/b.py", "docs/x.html", "docs/data.csv", "packaging/run.bat", ".github/workflows/w.yml", "scripts/tool.sh", "src/c.xml", "src/d.ini", "src/e.cfg")
        quiet = ("tests/test_x.py", "vendor/pipeline/z.py", "other/x.py", "docs/pic.png", "scripts/ui_capture.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in reached + quiet:
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_text(f"key = {fake}\n", encoding="utf-8")
            hits = canonical_hits(root, self.patterns)
        self.assertEqual(sorted(hit.split(":")[0] for hit in hits), sorted(reached))

    def test_the_hit_report_names_the_place_and_the_kind_but_never_the_value(self):
        fake = "CANARY_" + "AQ" + "." + "x" * 45
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "docs").mkdir()
            (Path(tmp) / "docs" / "a.md").write_text("첫 줄\n둘째 줄 " + fake + "\n", encoding="utf-8")
            hits = canonical_hits(Path(tmp), self.patterns)
        self.assertEqual(hits, ["docs/a.md:2 Google API 키(새 형식)"])
        self.assertNotIn(fake, "".join(hits))

    def test_the_exempt_file_exists_and_still_needs_its_exemption(self):
        scanned = canonical_hits(ROOT, self.patterns, exempt={})
        for rel, reason in CANONICAL_SCAN_EXEMPT.items():
            with self.subTest(file=rel):
                self.assertTrue(reason)
                self.assertTrue((ROOT / rel).is_file(), "예외 파일이 없어졌다 — 목록에서 뺀다")
                self.assertTrue([hit for hit in scanned if hit.startswith(rel + ":")], "예외가 더는 필요 없다(걸리는 값이 사라졌다) — 목록에서 뺀다")


class OperatorDecisionsTest(unittest.TestCase):
    """운영자가 2026-10-30 에 정한 방향이 문서에서 빠지거나 뒤집히지 않게 못 박는다."""

    def test_ai_router_and_multi_provider_switching_are_out_of_scope_and_said_so_in_every_place_that_matters(self):
        decisions, agents, architecture = read("docs/DECISIONS.md"), read("AGENTS.md"), read("docs/ARCHITECTURE.md")
        row = next(line for line in decisions.splitlines() if line.startswith("| D-15 |"))
        for needle in ("AI Router", "제외", "선택 보조", "기본값은 비활성", "최소한의 선택형 인터페이스"):
            self.assertIn(needle, row, needle)
        self.assertIn("AI Router", agents)
        self.assertIn("만들지 않는다", agents)
        self.assertIn("만들지 않는다", architecture)
        self.assertFalse((ROOT / "docs" / "PROVIDERS.md").exists(), "여러 공급자 정책 문서는 범위 밖이다")

    def test_the_four_optional_assist_functions_are_listed_and_off_by_default(self):
        assist = section(read("docs/ARCHITECTURE.md"), "## 7. 선택 보조 AI")
        for needle in ("감시 결과 한 줄 요약", "긴 오류 로그의 간단한 설명", "사용자가 확인할 조치 추천", "주간 운영 결과 요약", "기본 꺼짐", "NullAssistant", "ASSIST_UNAVAILABLE"):
            self.assertIn(needle, assist, needle)
        self.assertIn("기본은 꺼짐", read("AGENTS.md"))

    def test_github_models_is_not_mentioned_as_a_candidate_anywhere_in_the_repository(self):
        hits = [str(path.relative_to(ROOT)) for path in text_files() if path.name != "test_repo_layout.py" and re.search(r"GitHub\s*Models", path.read_text(encoding="utf-8"), re.I)]
        self.assertEqual(hits, [], "GitHub Models 는 후보와 설계에서 완전히 제외한다")

    def test_tistory_is_excluded_and_isolated_in_the_decision_log_and_the_platform_policy(self):
        self.assertIn("제외·격리", next(line for line in read("docs/DECISIONS.md").splitlines() if line.startswith("| D-01 |")))
        policy = read("docs/PLATFORM_POLICY.md")
        row = next(line for line in policy.splitlines() if line.startswith("| **티스토리**"))
        self.assertIn("제외·격리", row)

    def test_the_seventeen_features_that_must_work_without_ai_are_all_listed(self):
        no_ai = section(read("docs/ARCHITECTURE.md"), "## 8. AI 없이 반드시 동작해야 하는 기능")
        missing = [feature for feature in NO_AI_FEATURES if feature not in no_ai]
        self.assertEqual(missing, [])

    def test_pages_publishing_uses_the_linked_local_chanceblog_repository_and_the_existing_deploy_flow(self):
        pages = section(read("docs/ARCHITECTURE.md"), "## 3. GitHub Pages")
        for needle in ("기존 `chanceblog` 로컬 저장소", "pages.yml", "최신 `main` 을 먼저 가져온 뒤", "git push --dry-run"):
            self.assertIn(needle, pages, needle)
        self.assertIn("기존 `chanceblog` 로컬 저장소", read("docs/PLATFORM_POLICY.md"))
        self.assertIn("CHANCEBLOG_LOCAL_REPO", read(".env.example"))

    def test_the_priority_order_of_the_twelve_items_is_recorded(self):
        row = next(line for line in read("docs/DECISIONS.md").splitlines() if line.startswith("| D-12 |"))
        for number, needle in enumerate(("독립적인 데스크톱 프로그램 구조", "개인 PC 이관", "GitHub Pages 자동 발행 유지", "Blogger 초안 저장 유지", "네이버 A/B 독립 프로필",
                                         "제목·본문·이미지·태그 패키지", "반자동", "발행 상태 관리", "버전·변경 이력", "GitHub Releases 설치 파일", "업데이트·백업·복구·로그·오류 관리", "문서"), 1):
            self.assertIn(needle, row, f"{number}번 {needle}")


class TroubleshootingTest(unittest.TestCase):
    ROW = re.compile(r"^\| `([A-Z][A-Z0-9_]+)` \|(.*)\|$", re.M)

    def codes(self):
        return self.ROW.findall(read("docs/TROUBLESHOOTING.md"))

    def test_every_error_code_row_has_five_filled_columns_and_codes_are_unique(self):
        rows = self.codes()
        self.assertGreaterEqual(len(rows), 25)
        names = [code for code, _ in rows]
        self.assertEqual(len(names), len(set(names)), "중복된 오류 코드")
        for code, rest in rows:
            cells = [cell.strip() for cell in rest.split("|")]
            self.assertEqual(len(cells), 4, f"{code}: 언제·사용자 문구·하실 일·재시도 네 칸이어야 한다")
            self.assertTrue(all(cells), f"{code}: 빈 칸이 있다")

    def test_the_codes_the_operator_asked_for_exist_with_their_guidance(self):
        names = {code for code, _ in self.codes()}
        self.assertEqual([code for code in REQUIRED_ERROR_CODES if code not in names], [])
        text = read("docs/TROUBLESHOOTING.md")
        for needle in ("다시 로그인", "저장소에 올릴 권한", "워크플로 이름", "저장 경로", "재시도 가능 시각", "`Retry-After`"):      # 운영자가 예로 든 안내가 실제 문구로 있다
            self.assertIn(needle, text, needle)

    def test_troubleshooting_says_ai_does_not_replace_the_rules(self):
        text = read("docs/TROUBLESHOOTING.md")
        self.assertIn("AI 는 이 안내를 대신하지 않습니다", text)
        self.assertIn("키·토큰", text)


class CiWorkflowTest(unittest.TestCase):
    def test_ci_is_read_only_runs_both_python_versions_and_both_systems(self):
        ci = read(".github/workflows/ci.yml")
        self.assertIn("permissions:\n  contents: read", ci.replace("\r\n", "\n"))
        self.assertNotIn("secrets.", ci)                               # CI 는 시크릿을 쓰지 않는다
        # 의도적 갱신(D-220, 2026-11-07): 전체를 한 번에 돌리던 `unittest discover` 대신 같은 시험을 조각으로 나눠 돌리는 `scripts/ci_shard.py` 를 부른다 —
        # 모든 시험 파일이 조각 하나에만 들어가는지·조각 수가 맞는지는 `tests/test_ci_shard.py` 가 더 엄하게 지킨다(약화 아님).
        for needle in ("'3.10'", "'3.12'", "ubuntu-latest", "windows-latest", "python scripts/ci_shard.py"):
            self.assertIn(needle, ci, needle)

    def test_ci_runs_on_every_push_and_never_again_for_a_pull_request(self):
        # 미리 검사(D-28): 병합 브랜치를 push 하면 그 자리에서 시험이 돌고, PR 을 만들 때는 같은 커밋을 다시 돌리지 않는다.
        # PR 이벤트를 켜면 운영자가 PR 화면 앞에서 Windows 칸 13분을 또 기다린다. push 에 브랜치·경로 필터가 있으면 그 밖의 브랜치는 미리 검사되지 않는다.
        ci = read(".github/workflows/ci.yml").replace("\r\n", "\n")
        block = []
        for line in ci.split("\non:\n", 1)[1].splitlines():
            if line and not line[0].isspace() and not line.startswith("#"):
                break                      # 다음 최상위 키(permissions: …)에서 끝난다 — 사이의 빈 줄은 건너뛴다
            block.append(line)
        lines = [line for line in block if line.strip() and not line.lstrip().startswith("#")]
        self.assertEqual(lines, ["  push:", "  workflow_dispatch:"], "D-28: ci.yml 의 on: 은 push 와 workflow_dispatch 만(docs/DECISIONS.md) — " + repr(lines))
        code = [line for line in ci.splitlines() if not line.lstrip().startswith("#")]
        self.assertFalse(any("pull_request" in line for line in code))

    def test_ci_time_limit_leaves_room_for_the_slowest_cell(self):
        # Windows 칸이 14~15분까지 늘었다(2026-11-03). 20분 한도에 닿아 빨간 칸이 나오면 병합 부탁이 막힌다(D-28).
        # 의도적 갱신(D-176, 2026-11-07): 시험이 늘어 Windows 칸이 21~29분(M013 가지 28분 34초)이라 30분 한도에 1분 반만 남았다 — 40 이상으로 조인다.
        ci = read(".github/workflows/ci.yml")
        found = re.search(r"^\s+timeout-minutes:\s*(\d+)", ci, re.M)
        self.assertIsNotNone(found)
        self.assertGreaterEqual(int(found.group(1)), 40)


if __name__ == "__main__":
    unittest.main()
