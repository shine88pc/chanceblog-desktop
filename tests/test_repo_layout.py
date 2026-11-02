"""저장소 뼈대 시험 — 문서·설정이 서로 어긋나거나 비밀이 새지 않게, 운영자가 정한 범위가 문서에서 빠지지 않게 잡는다. 네트워크·시크릿 없이 돈다.

코드보다 먼저 문서·규칙을 두었으므로 시험이 지키는 것은 다음이다:
  1) 필요한 파일이 있다(AGENTS.md·CLAUDE.md·docs 7개·CI·VERSION·CHANGELOG·.env.example).
  2) 문서 속 상대 링크가 실제 파일을 가리키고, 문서가 부르는 결정 번호(D-nn)가 `docs/DECISIONS.md` 에 있다.
  3) VERSION 이 의미 있는 버전 번호이고 CHANGELOG 맨 위와 같다.
  4) `.gitignore` 가 비밀·사용자 데이터·빌드 산출물을 막고, `.env.example` 에는 변수 이름만 있으며, 추적되는 글에 키 모양 문자열이 없다.
  5) 운영자 결정(2026-10-30)이 문서에 남아 있다 — AI Router 제외·선택 보조 AI 기본 꺼짐·GitHub Models 후보 제외·티스토리 격리·AI 없이 되는 기능 목록·규칙 기반 오류 안내.
  6) 오류 안내 문서(TROUBLESHOOTING)의 오류 코드 표가 올바른 모양이고 코드가 겹치지 않는다.
  7) CI 워크플로가 읽기 전용이고 3.10 과 3.12 를 둘 다 돌린다.
"""
import re
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


def text_files():
    skip = {".git", "vendor", "__pycache__", ".venv"}
    for path in ROOT.rglob("*"):
        if path.is_file() and not (set(path.relative_to(ROOT).parts) & skip) and path.suffix in {".md", ".yml", ".yaml", ".py", ".txt", ".json", ".toml", ".example"}:
            yield path


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
        for needle in ("'3.10'", "'3.12'", "ubuntu-latest", "windows-latest", "python -m unittest discover -s tests"):
            self.assertIn(needle, ci, needle)


if __name__ == "__main__":
    unittest.main()
