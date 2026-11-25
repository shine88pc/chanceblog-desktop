"""비교 링크(PR 을 만드는 GitHub 화면 주소) — 글자로만 보여 주고 앱은 열지 않는다(PUBPR 설계서 3.8, PT-30–32). 외부 접속 0: 주소를 **만들기만** 한다.

지키는 것:
  1) 주소 모양(소유자·저장소는 상수에서·기준 `main`·머리 = 가지·`quick_pull=1&title=` 만) · 제목의 모든 특수 문자는 퍼센트 부호로 · 제목 120자 · 전체 1,500자 이하 · 본문(`body`) 매개변수는 없다 — 주입 문자열 열여덟 가지에도.
  2) 앱의 어느 열기 함수도 이 주소를 열지 않는다: 이 주소를 다루는 소스에는 열기 호출이 없고, 화면의 주소 허용 규칙(`ui/core/attribution.check_url`)은 이 주소를 거절한다. 보여 주는 쪽(`format`)은 '앱은 열지 않는다' 를 같이 적는다.
  3) PR 만들기·병합 API 를 부르는 코드가 소스에 없다(`api.github.com`·`/pulls`·`gh pr`·병합 매개변수).
"""
import ast
import sys
import types
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, quote, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.publish import gitrepo, pages  # noqa: E402
from chanceblog_desktop.service import format as fmt  # noqa: E402
from chanceblog_desktop.service import pages_flow  # noqa: E402
from chanceblog_desktop.ui.core.attribution import CreditError, check_url  # noqa: E402

SRC = ss.ROOT / "src" / "chanceblog_desktop"
OWNER, REPO = gitrepo.EXPECTED_OWNER, gitrepo.EXPECTED_REPO
BRANCH = "desktop/post-20261102-103012-3bf91f62"
HEAD = f"https://github.com/{OWNER}/{REPO}/compare/main...{BRANCH}?quick_pull=1&title="
INJECTIONS = ["제목&body=스팸", "제목#fragment", "제목?x=1", "제목\n&body=x", "제목%0A%26body%3Dx", '제목"><script>alert(1)</script>', "제목' onclick='x", "../../etc/passwd", "제목\\..\\x",
              "javascript:alert(1)", "\u202e위장", "제목\x00NUL", "제목 \t\r\n 공백", "😀 이모지", "%", "%zz", "a" * 500, "한" * 500, "&title=두번째&quick_pull=0", "제목+더하기=같음"]


def parsed(link):
    parts = urlsplit(link)
    return parts, parse_qs(parts.query, keep_blank_values=True)


class ShapeTest(unittest.TestCase):
    def test_compare_link_shape_and_encoding_and_length(self):
        """PT-30 — 소유자·저장소 상수 · 기준 main · 머리 가지 · `quick_pull=1&title=` 만 · 제목 퍼센트 부호 · 120자 · 1,500자 이하 · 본문 없음."""
        self.assertEqual(pages.compare_link(BRANCH), HEAD)
        self.assertEqual(pages.compare_link(BRANCH, "에너지 절약 습관"), HEAD + quote("에너지 절약 습관", safe=""))
        for title in INJECTIONS:
            with self.subTest(title=title[:24]):
                link = pages.compare_link(BRANCH, title)
                self.assertTrue(link.isascii(), "퍼센트 부호로 바꿔 ASCII 뿐이다")
                self.assertNotRegex(link, r"[\s\x00-\x1f\x7f\"'<>\\^`{|}]")
                self.assertLessEqual(len(link), pages.COMPARE_MAX_CHARS)
                parts, query = parsed(link)
                self.assertEqual((parts.scheme, parts.netloc, parts.fragment, parts.path), ("https", "github.com", "", f"/{OWNER}/{REPO}/compare/main...{BRANCH}"))
                self.assertEqual(sorted(query), ["quick_pull", "title"], "다른 매개변수가 끼어들지 않았다(본문·두 번째 제목·`quick_pull` 덮어쓰기)")
                self.assertEqual(query["quick_pull"], ["1"])
                self.assertEqual(query["title"], [" ".join(title.split())[:pages.COMPARE_TITLE_CHARS]], "제목은 공백을 정리해 120자까지, 글자 그대로 돌아온다")
                self.assertNotIn("body", query)
                self.assertEqual(link.count("?"), 1)
                self.assertNotIn("#", link)

    def test_the_title_is_cut_further_so_the_whole_address_stays_under_the_limit(self):
        with mock.patch.object(pages, "COMPARE_MAX_CHARS", 300):
            link = pages.compare_link(BRANCH, "한" * 120)
        self.assertLessEqual(len(link), 300)
        _parts, query = parsed(link)
        self.assertTrue(link.startswith(HEAD))
        self.assertTrue(("한" * 120).startswith(query["title"][0]) and 0 < len(query["title"][0]) < 120, "제목만 줄고 앞부분은 그대로다")
        with mock.patch.object(pages, "COMPARE_MAX_CHARS", len(HEAD) - 1):
            self.assertEqual(pages.compare_link(BRANCH, "한" * 120), HEAD, "머리만 남아도 주소는 올바른 모양이다")

    def test_only_this_apps_branch_names_are_accepted(self):
        for bad in ("main", "refs/heads/main", "desktop/post-1", BRANCH + "\n", BRANCH + "/x", BRANCH.upper(), "desktop/check-01234567", "ai/claude/M123-x", "", None, 5, b"x"):
            with self.subTest(bad=repr(bad)):
                self.assertEqual(ss.code_of(pages.compare_link, bad, "제목").code, "PAGES_PUSH_REFUSED")

    def test_the_owner_and_repository_come_from_the_constants_not_from_the_connected_folder(self):
        with mock.patch.object(pages, "EXPECTED_OWNER", "otherowner"), mock.patch.object(pages, "EXPECTED_REPO", "otherrepo"):
            self.assertTrue(pages.compare_link(BRANCH).startswith("https://github.com/otherowner/otherrepo/compare/main..."))
        tree = ast.parse((SRC / "publish" / "pages.py").read_text(encoding="utf-8"))
        func = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "compare_link")
        names = {node.id for node in ast.walk(func) if isinstance(node, ast.Name)}
        self.assertLessEqual({"EXPECTED_OWNER", "EXPECTED_REPO", "MAIN"}, names)
        self.assertFalse({"git", "run_git", "inspect_repo", "origin"} & names, "연결한 폴더의 origin 글자를 읽지 않는다")


class NeverOpenedTest(unittest.TestCase):
    OPENERS = frozenset({"openUrl", "open_new", "open_new_tab", "startfile", "qt_open_url", "_url_opener", "_opener", "url_opener", "open_url"})

    def test_compare_link_is_shown_and_copied_but_never_opened(self):
        """PT-31 — 화면의 주소 허용 규칙은 이 주소를 거절하고(열기 함수가 쓰는 규칙), 보여 주는 글은 '앱은 이 주소를 열지 않는다' 고 적으며, 이 주소를 다루는 소스에는 열기 호출이 없다."""
        link = pages.compare_link(BRANCH, "제목")
        with self.assertRaises(CreditError):
            check_url(link)
        plan = types.SimpleNamespace(title="글", status=st.MERGE_PENDING, path="_posts/x/2026-11-02-KR-103012.md", size_bytes=10, category="경제·일", lang="ko", repo="C:/repo", expected_url="", gates=None, actions=())
        report = pages_flow.PublishReport("p" * 32, False, plan, st.MERGE_PENDING, ("올렸습니다",), "", False, True, (), (), link, BRANCH)
        text = "\n".join(fmt.publish_report_lines(report))
        self.assertIn(link, text)
        self.assertIn("앱은 이 주소를 열지 않습니다", text)
        self.assertEqual(sum(1 for line in text.splitlines() if link in line), 1, "한 번만 보여 준다(복사해 쓴다)")

    def test_no_source_file_both_handles_the_link_and_calls_an_opener(self):
        uses, opens = {}, {}
        for path in sorted(SRC.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            rel = path.relative_to(SRC).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == "compare_link" or isinstance(node, ast.Attribute) and node.attr in ("compare_link", "link"):
                    uses.setdefault(rel, node.lineno)
                if isinstance(node, ast.Call):
                    func = node.func
                    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
                    if name in self.OPENERS or (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "webbrowser"):
                        opens.setdefault(rel, node.lineno)
        self.assertTrue(uses, "주소를 다루는 곳이 있어야 이 시험이 빈 시험이 아니다")
        self.assertTrue(opens, "열기 호출이 있는 곳이 있어야 이 시험이 빈 시험이 아니다(지금은 네이버 글쓰기 주소와 사진 출처뿐)")
        self.assertEqual(sorted(set(uses) & set(opens)), [], f"링크를 다루는 파일이 열기 함수도 부른다: {uses} {opens}")
        self.assertNotIn("service/pages_flow.py", opens)
        self.assertNotIn("publish/pages.py", opens)


class NoPullRequestApiTest(unittest.TestCase):
    NEEDLES = ("api.github.com", "/pulls", "gh pr", "pulls?", "merge_method", "graphql", "/git/refs", "createPullRequest", "mergePullRequest")

    def strings(self):
        for path in sorted(SRC.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docs = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                    first = node.body[0]
                    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                        docs.add(first.value)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in docs:
                    yield path.relative_to(SRC).as_posix(), node.lineno, node.value

    def test_no_pr_or_merge_api_call_exists(self):
        """PT-32 — 소스(설명 글은 뺀다)에 PR 만들기·병합 API 의 주소·명령·매개변수 글이 없다. 앱은 PR 을 만들지도 병합하지도 않는다."""
        found = [(rel, line, needle) for rel, line, value in self.strings() for needle in self.NEEDLES if needle in value]
        self.assertEqual(found, [])
        imports = []
        for path in sorted(SRC.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                imports += [(path.name, name) for name in names if name.split(".")[0].lower() in ("github", "pygithub", "ghapi", "gidgethub", "octokit")]
        self.assertEqual(imports, [])
        self.assertTrue(any("compare" in value for _rel, _line, value in self.strings()), "빈 시험이 아니다 — 비교 주소를 만드는 글은 있다")


if __name__ == "__main__":
    unittest.main()
