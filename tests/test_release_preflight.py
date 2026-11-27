"""`scripts/release_preflight.py`(릴리스 사전 점검, RELEASE 설계서 3-3 단계 2, V1REL12·R-2) 시험 — 가짜 실행 환경·가짜 `gh`·가짜 git 호출로 여섯 가지 확인을 본다(접속 0).

지키는 것:
  1) 모든 것이 맞으면 통과하고, 어긋나는 것을 **하나씩** 만들면 그 번호만 실패한다 — 1a 이벤트가 `workflow_dispatch` 가 아님·1b ref 가 main 이 아님·1c 실행 커밋이 main 끝과 다름·
     2 `VERSION` 모양(정식·`-rc.N` 외 거절)·3a 태그가 이미 있음(앞부분만 같은 다른 태그는 아님)·3b 그 태그의 릴리스(초안 포함)가 이미 있음·4 변경 이력 맨 위 절·릴리스 노트 모양·5 `ci.yml` 실행이 없거나 도는 중이거나 성공이 아님·6 작업 트리가 더럽거나 커밋이 다름.
  2) **의심스러우면 거절**: `gh` 를 못 찾거나 호출이 실패하거나 응답이 이상하면 통과가 아니라 실패다.
  3) `gh` 는 고정 인자 목록으로만 부르고(셸 없음) 읽기 요청만 한다. 출력에는 고정 문장·번호·태그·버전·종료 코드뿐이고 토큰·`gh` 오류 글이 나오지 않는다. 한 가지가 어긋나도 나머지를 모두 보인다.
  4) 3a·3b 는 `--jq` 없이 원시 JSON 응답을 엄격히 읽는다 — 정확히 JSON 목록이고 모든 항목의 모양이 맞을 때만 '있다·없다' 를 가리고, 빈 응답·HTML·`null`·`{}`·모양이 다른 항목·잘린 응답은 실패다(재작업 1·S-3).
     저장소 이름의 점으로만 된 조각(`..`)은 `gh` 를 부르기 전에 거절한다(참고 N-2).
네트워크 없이 돈다(가짜 `gh`만).
"""
import ast
import json
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import release_tools_support as rts

import release_chain as rc
import release_preflight as rp

ROOT = rts.ROOT
SCRIPT = ROOT / "scripts" / "release_preflight.py"
SHA = rts.FAKE_COMMIT
REPO = "owner/repo"
TOKEN = "CANARY_" + "token-" + "x" * 20


def good_env(**changes):
    env = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": SHA, "GITHUB_REPOSITORY": REPO, "GH_TOKEN": TOKEN}
    env.update(changes)
    return {key: value for key, value in env.items() if value is not None}


def ci_row(event="push", status="completed", conclusion="success", sha=SHA):
    return f"{event}\t{status}\t{conclusion}\t{sha}\n"


def tags_json(*refs):
    """`gh api repos/.../git/matching-refs/tags/<태그>` 가 돌려주는 원시 JSON 목록 글."""
    kind = {"type": "commit"}
    return json.dumps([dict(ref=ref, object=kind) for ref in refs])


def releases_json(*tags):
    """`gh api repos/.../releases --paginate` 가 돌려주는 원시 JSON 목록 글(항목의 다른 칸은 시험에 필요 없다)."""
    return json.dumps([{"tag_name": tag, "draft": False} for tag in tags])


def good_gh(**overrides):
    """모두 맞는 세계의 가짜 `gh` — 경로 낱말로 응답을 고른다(`overrides` 로 한 가지씩 바꾼다)."""
    routes = {"git/ref/heads/main": (0, SHA + "\n", ""), "matching-refs/tags/": (0, "[]", ""), "/releases": (0, releases_json("v0.9.0"), ""), "actions/workflows/ci.yml/runs": (0, ci_row(), "")}
    routes.update(overrides)
    return rts.FakeGh(list(routes.items()))


def git_run(*, status="", head=SHA, status_code=0, head_code=0):
    calls = []

    def run(command, **kwargs):
        calls.append(list(command))
        if "status" in command:
            return types.SimpleNamespace(returncode=status_code, stdout=status, stderr="")
        return types.SimpleNamespace(returncode=head_code, stdout=head + "\n", stderr="")
    run.calls = calls
    return run


class World:
    def __init__(self, case, version="1.0.0", *, changelog=None):
        holder = rts.temp_dir()
        case.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        rts.write(self.root / "VERSION", version + "\n")
        rts.write(self.root / "CHANGELOG.md", changelog if changelog is not None else rts.changelog_text(version))

    def run(self, *, environ=None, gh=None, run=None):
        out, err = [], []
        stdout, stderr = _Sink(out), _Sink(err)
        env = good_env() if environ is None else environ
        code = rp.main(["--root", str(self.root)], environ=env, gh=gh if gh is not None else good_gh(), run=run if run is not None else git_run(), stdout=stdout, stderr=stderr)
        return code, "".join(out), "".join(err)


class _Sink:
    def __init__(self, parts):
        self.parts = parts

    def write(self, text):
        self.parts.append(text)


def failed_numbers(out):
    return sorted(line.split()[1] for line in out.splitlines() if line.startswith("[실패]"))


class AllGoodTest(unittest.TestCase):
    def test_everything_right_passes_with_one_line_per_check_and_exit_zero(self):
        for version in ("1.0.0", "1.0.0-rc.1"):
            with self.subTest(version=version):
                world = World(self, version)
                code, out, err = world.run()
                self.assertEqual((code, err), (0, ""))
                lines = out.splitlines()
                self.assertEqual([line.split()[1] for line in lines[:-1]], ["1a", "1b", "1c", "2", "3a", "3b", "4", "5", "6"])
                self.assertTrue(all(line.startswith("[통과] ") for line in lines[:-1]), out)
                self.assertEqual(lines[-1], "사전 점검 통과: 모두 맞다.")

    def test_the_gh_calls_are_exactly_these_read_only_requests_in_a_fixed_argument_list(self):
        world = World(self)
        gh = good_gh()
        world.run(gh=gh)
        self.assertEqual(gh.calls, [
            ["api", "repos/owner/repo/git/ref/heads/main", "--jq", ".object.sha"],
            ["api", "repos/owner/repo/git/matching-refs/tags/v1.0.0"],
            ["api", "repos/owner/repo/releases", "--paginate"],
            ["api", f"repos/owner/repo/actions/workflows/ci.yml/runs?head_sha={SHA}&per_page=100", "--jq", '.workflow_runs[] | [.event, .status, (.conclusion // ""), .head_sha] | @tsv'],
        ])
        for call in gh.calls:
            self.assertEqual(call[0], "api")
            self.assertNotIn("-X", call)
            self.assertNotIn("--method", call)
            self.assertNotIn("POST", call)

    def test_the_git_calls_are_a_status_and_a_head_read_in_the_given_folder(self):
        world = World(self)
        run = git_run()
        world.run(run=run)
        self.assertEqual(run.calls, [["git", "-C", str(world.root), "status", "--porcelain"], ["git", "-C", str(world.root), "rev-parse", "HEAD"]])

    def test_the_output_never_contains_the_token_or_environment_values(self):
        world = World(self)
        code, out, err = world.run()
        for text in (out, err):
            self.assertNotIn(TOKEN, text)
            self.assertNotIn("CANARY_", text)
            self.assertNotIn(str(world.root), text, "폴더 경로를 보이지 않는다")


class EventAndRefTest(unittest.TestCase):
    def test_only_a_manual_run_passes_1a(self):
        for event in ("push", "pull_request", "pull_request_target", "schedule", "workflow_run", "release", "issue_comment", "Workflow_Dispatch", "workflow_dispatch ", "", None):
            with self.subTest(event=event):
                code, out, err = World(self).run(environ=good_env(GITHUB_EVENT_NAME=event))
                self.assertEqual((code, failed_numbers(out)), (1, ["1a"]))
                self.assertIn("사전 점검 실패: 1건 — 릴리스를 만들지 않는다.", err)

    def test_only_the_main_branch_passes_1b(self):
        for ref in ("refs/heads/dev", "refs/heads/main2", "refs/heads/Main", "refs/tags/v1.0.0", "refs/pull/1/merge", "main", "refs/heads/main ", "", None):
            with self.subTest(ref=ref):
                code, out, _err = World(self).run(environ=good_env(GITHUB_REF=ref))
                self.assertEqual((code, failed_numbers(out)), (1, ["1b"]))

    def test_the_run_commit_must_be_the_tip_of_main(self):
        other = "f" * 40
        code, out, _err = World(self).run(gh=good_gh(**{"git/ref/heads/main": (0, other + "\n", "")}))
        self.assertEqual((code, failed_numbers(out)), (1, ["1c"]))
        self.assertIn("main 끝이 실행 커밋과 다르다 — 그 사이 main 이 바뀌었다", out)

    def test_a_missing_or_malformed_run_commit_or_repository_fails_1c(self):
        cases = (("short sha", {"GITHUB_SHA": "abc"}), ("upper sha", {"GITHUB_SHA": SHA.upper()}), ("no sha", {"GITHUB_SHA": None}), ("no repo", {"GITHUB_REPOSITORY": None}),
                 ("bad repo", {"GITHUB_REPOSITORY": "no-slash"}), ("repo with space", {"GITHUB_REPOSITORY": "a b/c"}))
        for label, change in cases:
            with self.subTest(label=label):
                gh = good_gh()
                code, out, _err = World(self).run(environ=good_env(**change), gh=gh)
                self.assertEqual(code, 1)
                self.assertIn("1c", failed_numbers(out))
                for call in gh.calls:
                    self.assertNotIn("repos/no-slash", " ".join(call))

    def test_a_repository_name_made_of_dots_cannot_climb_out_of_the_repos_path(self):
        """재작업 1(참고 N-2) — `../..`·`./.`·`a/..` 같은 점 조각 이름은 gh 인자(`repos/<이름>/…`)를 다른 경로로 바꾼다 — 모든 GitHub 확인이 실패하고 gh 는 부르지도 않는다."""
        for repo in ("../..", "./.", "a/..", "../b", "./b", "a/.", "...//..", "a/...", ".../b"):
            with self.subTest(repo=repo):
                gh = good_gh()
                code, out, _err = World(self).run(environ=good_env(GITHUB_REPOSITORY=repo), gh=gh)
                self.assertEqual(code, 1)
                self.assertEqual(sorted(set(failed_numbers(out)) & {"1c", "3a", "3b", "5"}), ["1c", "3a", "3b", "5"], repo)
                self.assertEqual(gh.calls, [], "이상한 저장소 이름으로는 gh 를 부르지 않는다")
        for repo in ("owner/repo", "o-w_n.er/re.po-name", ".github/x", "a/.github", "a.b/c.d"):
            with self.subTest(good_repo=repo):
                code, out, _err = World(self).run(environ=good_env(GITHUB_REPOSITORY=repo))
                self.assertEqual((code, failed_numbers(out)), (0, []))

    def test_the_main_tip_answer_must_be_one_commit_and_a_failed_call_fails(self):
        for label, reply in {"gh error": (1, "", "boom"), "empty": (0, "", ""), "two lines": (0, SHA + "\n" + SHA + "\n", ""), "not a commit": (0, "not-a-sha\n", ""), "html": (0, "<html>", "")}.items():
            with self.subTest(label=label):
                code, out, err = World(self).run(gh=good_gh(**{"git/ref/heads/main": reply}))
                self.assertEqual((code, failed_numbers(out)), (1, ["1c"]))
                self.assertNotIn("boom", out + err, "gh 의 오류 글은 보이지 않는다")

    def test_the_tip_answer_may_come_with_surrounding_quotes_and_blank_lines(self):
        code, out, _err = World(self).run(gh=good_gh(**{"git/ref/heads/main": (0, f'\n"{SHA}"\n\n', "")}))
        self.assertEqual((code, failed_numbers(out)), (0, []))


class VersionTest(unittest.TestCase):
    def test_only_a_release_or_a_numbered_candidate_passes_2_and_the_dependent_checks_are_marked_unchecked(self):
        for text in ("1.0.0-preview.1", "0.1.0-preview.1", "1.0", "v1.0.0", "1.0.0-rc.0", "1.0.0-rc.01", "1.0.0-beta.2", "1.0.0+3", "", "\n"):
            with self.subTest(version=text):
                world = World(self)
                rts.write(world.root / "VERSION", text + "\n")
                code, out, _err = world.run()
                self.assertEqual(code, 1)
                self.assertEqual(failed_numbers(out), ["2", "3a", "3b", "4"])
                self.assertEqual(out.count("건너뜀 — VERSION 이 올바르지 않아 확인할 수 없다"), 3)

    def test_a_missing_version_file_fails_2(self):
        world = World(self)
        (world.root / "VERSION").unlink()
        self.assertEqual(failed_numbers(world.run()[1]), ["2", "3a", "3b", "4"])

    def test_a_bom_and_crlf_in_the_version_file_are_tolerated_like_the_package_tools_do(self):
        world = World(self)
        (world.root / "VERSION").write_bytes(b"\xef\xbb\xbf1.0.0\r\n")
        self.assertEqual(world.run()[0], 0)


class TagAndReleaseTest(unittest.TestCase):
    def test_a_tag_that_already_exists_stops_the_release(self):
        code, out, _err = World(self).run(gh=good_gh(**{"matching-refs/tags/": (0, tags_json("refs/tags/v1.0.0"), "")}))
        self.assertEqual((code, failed_numbers(out)), (1, ["3a"]))
        self.assertIn("태그 v1.0.0 가 이미 있다", out)

    def test_other_tags_that_merely_start_with_the_same_text_are_not_this_tag(self):
        reply = tags_json("refs/tags/v1.0.0-rc.1", "refs/tags/v1.0.0-rc.2", "refs/tags/v1.0.01", "refs/tags/v1.0.0x", "refs/tags/xv1.0.0")
        code, out, _err = World(self).run(gh=good_gh(**{"matching-refs/tags/": (0, reply, "")}))
        self.assertEqual((code, failed_numbers(out)), (0, []))

    def test_a_candidate_tag_is_checked_by_its_own_name(self):
        world = World(self, "1.0.0-rc.1")
        gh = good_gh(**{"matching-refs/tags/": (0, tags_json("refs/tags/v1.0.0-rc.1"), "")})
        code, out, _err = world.run(gh=gh)
        self.assertEqual((code, failed_numbers(out)), (1, ["3a"]))
        self.assertIn("repos/owner/repo/git/matching-refs/tags/v1.0.0-rc.1", " ".join(gh.calls[1]))

    def test_a_release_for_the_tag_even_a_draft_stops_the_release(self):
        two_pages = releases_json("v0.9.0") + "\n" + releases_json("v1.0.0")                    # 쪽마다 목록이 따로 나오는 모양도 읽는다
        for listing in (releases_json("v1.0.0"), releases_json("v0.9.0", "v1.0.0", "v0.8.0"), "  " + releases_json("v1.0.0") + "  \n", json.dumps([{"tag_name": "v1.0.0"}], indent=2), two_pages):
            with self.subTest(listing=listing):
                code, out, _err = World(self).run(gh=good_gh(**{"/releases": (0, listing, "")}))
                self.assertEqual((code, failed_numbers(out)), (1, ["3b"]))
                self.assertIn("태그 v1.0.0 의 릴리스(초안 포함)가 이미 있다", out)

    def test_releases_of_other_tags_or_an_empty_list_pass(self):
        for listing in ("[]", " [] \n", "[][]", releases_json("v0.9.0"), releases_json("v1.0.0-rc.1", "v1.0.1", "v1.0.00")):
            with self.subTest(listing=listing):
                self.assertEqual(World(self).run(gh=good_gh(**{"/releases": (0, listing, "")}))[0], 0)

    def test_a_failed_listing_never_counts_as_nothing_found(self):
        for key, number in (("matching-refs/tags/", "3a"), ("/releases", "3b")):
            for label, reply in {"error": (1, "", "x"), "network": (127, "", ""), "rate limit": (1, "", "API rate limit exceeded")}.items():
                with self.subTest(call=number, label=label):
                    code, out, err = World(self).run(gh=good_gh(**{key: reply}))
                    self.assertEqual((code, failed_numbers(out)), (1, [number]))
                    self.assertNotIn("rate limit", out + err)

    def test_a_failed_call_is_a_failure_even_if_it_printed_an_empty_list_and_it_says_so(self):
        """종료 코드를 먼저 본다 — 실패한 호출이 우연히 정상 모양(`[]`)을 찍었어도 '없음' 이 아니고, 실패 문장(종료 코드)이 보인다(모양 오류 문장이 아니라)."""
        for key, number in (("matching-refs/tags/", "3a"), ("/releases", "3b")):
            for code_number in (1, 2, 127):
                with self.subTest(call=number, exit_code=code_number):
                    code, out, _err = World(self).run(gh=good_gh(**{key: (code_number, "[]", "boom")}))
                    self.assertEqual((code, failed_numbers(out)), (1, [number]))
                    self.assertIn(f"gh 호출이 실패했다(종료 코드 {code_number})", out)
                    self.assertNotIn("응답을 읽을 수 없다", out, "실패한 호출의 글은 읽지도 않는다")
                    self.assertNotIn("boom", out)

    def test_an_answer_that_is_not_exactly_a_json_list_of_the_right_shape_never_counts_as_nothing_found(self):
        """재작업 1(S-3) — 정확히 JSON 목록일 때만 '없음' 이다: 빈 글·공백·`null`·객체·모양이 다른 항목·HTML·잘린 글·남는 글자·너무 깊은 겹침은 모두 실패(의심스러우면 거절)."""
        samples = {
            "empty text": "", "blank": "  \n\t ", "null": "null", "empty object": "{}", "object with message": '{"message": "Not Found"}', "list of empty object": "[{}]",
            "html": "<html><body><h1>502 Bad Gateway</h1></body></html>", "long text": "x" * 100000, "truncated": '[{"ref": "refs/tags/v1.0', "garbage after list": "[] trailing",
            "garbage between lists": "[] x []", "bare string": '"v1.0.0"', "list of numbers": "[1, 2]", "nested list": "[[]]", "number": "5", "true": "true",
            "ref is a number": '[{"ref": 5, "tag_name": 5}]', "ref of a branch": '[{"ref": "refs/heads/main", "tag_name": null}]', "no ref and no tag_name": '[{"name": "v1.0.0"}]',
            "deeply nested": "[" * 100000 + "]" * 100000, "nul inside": "[]\x00", "list then null": "[] null", "object then list": "{} []", "list then string": '[] "x"',
        }
        for key, number in (("matching-refs/tags/", "3a"), ("/releases", "3b")):
            for label, reply in samples.items():
                with self.subTest(call=number, sample=label):
                    code, out, err = World(self).run(gh=good_gh(**{key: (0, reply, "")}))
                    self.assertEqual((code, failed_numbers(out)), (1, [number]))
                    shown = out + err
                    for word in ("html", "Bad Gateway", "Not Found", "trailing", "xxxx"):
                        self.assertNotIn(word, shown, "응답 글을 되풀이해 보이지 않는다")
                    self.assertIn("응답을 읽을 수 없다", out)

    def test_a_list_with_an_item_of_the_wrong_shape_is_refused_even_next_to_good_items(self):
        for key, number, good in (("matching-refs/tags/", "3a", {"ref": "refs/tags/v0.9.0"}), ("/releases", "3b", {"tag_name": "v0.9.0"})):
            for label, bad in {"empty object": {}, "number": 5, "string": "v1.0.0", "null": None, "list": []}.items():
                with self.subTest(call=number, bad_item=label):
                    code, out, _err = World(self).run(gh=good_gh(**{key: (0, json.dumps([good, bad, good]), "")}))
                    self.assertEqual((code, failed_numbers(out)), (1, [number]))

    def test_the_tag_list_must_be_one_list_and_the_release_list_may_come_in_pages(self):
        for text in ("[][]", tags_json("refs/tags/v0.9.0") + tags_json("refs/tags/v0.8.0")):
            with self.subTest(text=text[:20]):
                code, out, _err = World(self).run(gh=good_gh(**{"matching-refs/tags/": (0, text, "")}))
                self.assertEqual((code, failed_numbers(out)), (1, ["3a"]), "태그 목록은 한 쪽이다 — 여러 목록이 붙어 오면 모양을 알 수 없다")
        code, out, _err = World(self).run(gh=good_gh(**{"/releases": (0, "[][]", "")}))
        self.assertEqual((code, failed_numbers(out)), (0, []), "쪽마다 빈 목록이 와도 '없음'")
        code, out, _err = World(self).run(gh=good_gh(**{"/releases": (0, "[]\n" + releases_json("v1.0.0"), "")}))
        self.assertEqual((code, failed_numbers(out)), (1, ["3b"]), "둘째 쪽에 이 태그의 릴리스가 있다")

    def test_a_real_empty_list_and_lists_of_other_tags_pass_with_whitespace_around(self):
        for reply in ("[]", "\n[]\n", " \t[ ]\r\n"):
            with self.subTest(reply=reply):
                code, out, _err = World(self).run(gh=good_gh(**{"matching-refs/tags/": (0, reply, ""), "/releases": (0, reply, "")}))
                self.assertEqual((code, failed_numbers(out)), (0, []))

    def test_when_the_gh_program_is_missing_every_github_check_fails(self):
        def missing(command, **kwargs):
            raise FileNotFoundError("gh")
        out, err = [], []
        world = World(self)
        code = rp.main(["--root", str(world.root)], environ=good_env(), run=lambda command, **kwargs: missing(command) if command[0] == "gh" else git_run()(command), stdout=_Sink(out), stderr=_Sink(err))
        self.assertEqual(code, 1)
        self.assertEqual(failed_numbers("".join(out)), ["1c", "3a", "3b", "5"])
        self.assertIn("gh 호출이 실패했다(종료 코드 127)", "".join(out))


class ChangelogTest(unittest.TestCase):
    def test_the_top_section_must_be_the_version_and_the_note_well_formed(self):
        for label, text in {"another top": rts.changelog_text("1.0.1"), "no section": "# 변경 이력\n\n- 아무것도 없다\n"}.items():
            with self.subTest(label=label):
                code, out, _err = World(self, changelog=text).run()
                self.assertEqual((code, failed_numbers(out)), (1, ["4"]))

    def test_a_bad_note_names_its_problems_with_fixed_codes(self):
        world = World(self, changelog=rts.changelog_text("1.0.0", summary=("- 하나",)))
        code, out, _err = world.run()
        self.assertEqual((code, failed_numbers(out)), (1, ["4"]))
        self.assertIn("릴리스 노트 모양이 틀리다: summary_lines — 1", out)
        old_shape = "# 변경 이력\n\n## [1.0.0] — 2026-12-10 (옛 모양)\n\n- 옛 줄\n"
        code, out, _err = World(self, changelog=old_shape).run()
        self.assertEqual(failed_numbers(out), ["4"])
        self.assertIn("notes_heading", out)

    def test_the_version_must_be_the_top_section_not_just_somewhere_in_the_file(self):
        """VERSION 의 절이 파일 어딘가에 있어도 맨 위가 다른 버전이면 거절한다(맨 위 절 확인이 따로 있다)."""
        higher = rts.changelog_text("1.1.0").replace("## [0.1.0-preview.1]", rts.notes_section("1.0.0") + "\n## [0.1.0-preview.1]")
        self.assertEqual(rc.notes_problems(*rc.notes_section(higher, "1.0.0"), "1.0.0"), [], "대조: 1.0.0 절은 모양이 맞고 파일에 있다")
        code, out, _err = World(self, changelog=higher).run()
        self.assertEqual((code, failed_numbers(out)), (1, ["4"]))
        self.assertIn("변경 이력 맨 위 절이 1.1.0 이다(VERSION 은 1.0.0)", out)

    def test_a_missing_changelog_file_fails_4(self):
        world = World(self)
        (world.root / "CHANGELOG.md").unlink()
        self.assertEqual(failed_numbers(world.run()[1]), ["4"])

    def test_the_standard_note_for_a_candidate_passes(self):
        self.assertEqual(World(self, "1.0.0-rc.2").run()[0], 0)

    def test_the_real_repository_changelog_is_old_shape_so_a_real_run_would_stop_at_4_until_real_notes_exist(self):
        """지금 실제 저장소의 변경 이력 맨 위 절은 옛 모양(`0.1.0-preview.1`)이고 `VERSION` 도 사전판이라 사전 점검은 2 에서 멈춘다 — 정식 릴리스 때 사람이 새 절을 쓰고 `VERSION` 을 올린다(이 시험은 그 사실을 문서화하되 상태를 못박지 않는다)."""
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        result, parsed = rp.check_version(version + "\n")
        self.assertEqual(result.ok, parsed is not None)
        self.assertEqual(rc.top_changelog_version((ROOT / "CHANGELOG.md").read_text(encoding="utf-8")), version)


class CiTest(unittest.TestCase):
    def test_a_missing_running_or_not_successful_run_stops_the_release(self):
        cases = {
            "no runs": "", "in progress": ci_row(status="in_progress", conclusion=""), "queued": ci_row(status="queued", conclusion=""), "failure": ci_row(conclusion="failure"),
            "cancelled": ci_row(conclusion="cancelled"), "skipped": ci_row(conclusion="skipped"), "timed out": ci_row(conclusion="timed_out"), "only a pull request run": ci_row(event="pull_request"),
            "run of another commit": ci_row(sha="e" * 40), "success plus failure": ci_row() + ci_row(conclusion="failure"), "success plus still running": ci_row() + ci_row(status="in_progress", conclusion=""),
            "completed without result": ci_row(conclusion=""),
        }
        for label, reply in cases.items():
            with self.subTest(label=label):
                code, out, _err = World(self).run(gh=good_gh(**{"actions/workflows/ci.yml/runs": (0, reply, "")}))
                self.assertEqual((code, failed_numbers(out)), (1, ["5"]), out)
                if label in ("in progress", "queued", "success plus still running"):
                    self.assertIn("아직 끝나지 않았다", out, "도는 중인 것은 '성공이 아니다' 가 아니라 '아직 끝나지 않았다' 로 알린다")
                if label in ("failure", "cancelled", "skipped", "timed out", "success plus failure", "completed without result"):
                    self.assertIn("성공이 아니다", out)
                if label in ("no runs", "only a pull request run", "run of another commit"):
                    self.assertIn("push 실행이 없다", out)

    def test_runs_that_are_all_successful_pass_and_other_events_or_commits_are_ignored(self):
        reply = ci_row() + ci_row() + ci_row(event="pull_request", conclusion="failure") + ci_row(sha="e" * 40, conclusion="failure") + ci_row(event="workflow_dispatch", conclusion="failure")
        code, out, _err = World(self).run(gh=good_gh(**{"actions/workflows/ci.yml/runs": (0, reply, "")}))
        self.assertEqual((code, failed_numbers(out)), (0, []))
        self.assertIn("2건 성공", out)

    def test_a_failed_call_or_an_unreadable_answer_is_a_failure(self):
        for label, reply in {"error": (1, "", "x"), "short row": (0, "push\tcompleted\n", ""), "five columns": (0, "push\tcompleted\tsuccess\t" + SHA + "\textra\n", ""), "html": (0, "<html>", "")}.items():
            with self.subTest(label=label):
                code, out, _err = World(self).run(gh=good_gh(**{"actions/workflows/ci.yml/runs": reply}))
                self.assertEqual((code, failed_numbers(out)), (1, ["5"]))


class TreeTest(unittest.TestCase):
    def test_a_dirty_tree_a_different_commit_or_a_failed_git_call_stops_the_release(self):
        for label, run in {"dirty": git_run(status=" M file.txt\n"), "untracked": git_run(status="?? new.txt\n"), "other commit": git_run(head="d" * 40), "status error": git_run(status_code=128),
                           "head error": git_run(head_code=128)}.items():
            with self.subTest(label=label):
                code, out, _err = World(self).run(run=run)
                self.assertEqual((code, failed_numbers(out)), (1, ["6"]))

    def test_a_git_program_that_cannot_start_is_a_failure(self):
        def broken(command, **kwargs):
            raise OSError("no git")
        code, out, _err = World(self).run(run=broken)
        self.assertEqual((code, failed_numbers(out)), (1, ["6"]))


class SeveralFailuresTest(unittest.TestCase):
    def test_every_failure_is_shown_not_just_the_first(self):
        gh = good_gh(**{"matching-refs/tags/": (0, tags_json("refs/tags/v1.0.0"), ""), "actions/workflows/ci.yml/runs": (0, ci_row(conclusion="failure"), "")})
        code, out, err = World(self).run(environ=good_env(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/dev"), gh=gh, run=git_run(status=" M x\n"))
        self.assertEqual((code, failed_numbers(out)), (1, ["1a", "1b", "3a", "5", "6"]))
        self.assertIn("사전 점검 실패: 5건 — 릴리스를 만들지 않는다.", err)


class UsageAndSourceTest(unittest.TestCase):
    def test_arguments_other_than_root_are_refused_without_echo(self):
        for argv in (["--bogus"], ["--root"], ["x"], ["--root", "a", "b"], ["--token=" + TOKEN]):
            out, err = [], []
            code = rp.main(argv, environ=good_env(), gh=good_gh(), run=git_run(), stdout=_Sink(out), stderr=_Sink(err))
            self.assertEqual((code, "".join(out), "".join(err)), (2, "", "사용법 오류: --root 폴더 만 쓴다.\n"))

    def test_without_the_root_argument_the_repository_root_is_what_is_checked(self):
        """R7(Q) — R-3 워크플로가 `python scripts/release_preflight.py` 를 인자 없이 부르는 길: `--root` 기본값이 저장소 맨 위 폴더이고, 그 폴더의 `VERSION`·`CHANGELOG.md`·git 으로 점검한다(기본값의 글자 하나가 틀리면 빨개진다)."""
        world = World(self)
        run = git_run()
        out, err = [], []
        with mock.patch.object(rp, "ROOT", world.root):
            code = rp.main([], environ=good_env(), gh=good_gh(), run=run, stdout=_Sink(out), stderr=_Sink(err))
        self.assertEqual((code, "".join(err)), (0, ""), "".join(out))
        self.assertEqual(run.calls[0][:3], ["git", "-C", str(world.root)], "git 도 그 폴더에서 읽는다")
        self.assertEqual(rp.ROOT, Path(rp.__file__).resolve().parents[1], "기본 폴더는 이 스크립트의 위 폴더(저장소 맨 위)다")

    def test_run_gh_uses_a_fixed_argument_list_and_turns_missing_programs_and_timeouts_into_127(self):
        seen = []

        def fake(command, **kwargs):
            seen.append((list(command), dict(kwargs)))
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")
        done = rp.run_gh(["api", "x"], run=fake)
        self.assertEqual(done.stdout, "ok")
        self.assertEqual(seen[0][0], ["gh", "api", "x"])
        self.assertNotIn("shell", seen[0][1])
        self.assertEqual(seen[0][1]["timeout"], rp.GH_TIMEOUT)
        for error in (FileNotFoundError("gh"), subprocess.TimeoutExpired("gh", 1), PermissionError("x")):
            def broken(command, **kwargs):
                raise error
            self.assertEqual(rp.run_gh(["api", "x"], run=broken).returncode, 127)

    def test_the_source_reads_no_token_opens_no_connection_and_runs_only_gh_and_git(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        code = ast.Module(body=tree.body[1:], type_ignores=[])                   # 첫 문장(머리글)은 빼고 코드만 본다
        shown = ast.unparse(code)
        for word in ("GH_TOKEN", "GITHUB_TOKEN", "Authorization", "shell=True", "os.system", "Popen", "environ[", "getenv"):
            self.assertNotIn(word, shown.replace("environ.get(", ""), word)
        imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertFalse(imported & {"socket", "urllib", "http", "ssl", "requests", "logging"}, imported)
        self.assertNotIn("print", [ast.unparse(node.func) for node in ast.walk(code) if isinstance(node, ast.Call)])
        for node in ast.walk(code):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for banned in ("gh " + "variable", "actions/" + "variables", "PIPELINE" + "_PAUSE", "release create", "release edit", "release delete", "--method", "-X", "POST", "PATCH", "DELETE"):
                    self.assertNotIn(banned, node.value, "읽기 전용이어야 한다")
        env_reads = [ast.unparse(node.args[0]) for node in ast.walk(code) if isinstance(node, ast.Call) and ast.unparse(node.func) == "environ.get"]
        self.assertEqual(sorted(set(env_reads)), ["'GITHUB_EVENT_NAME'", "'GITHUB_REF'", "'GITHUB_REPOSITORY'", "'GITHUB_SHA'"], "읽는 환경 변수는 이 넷뿐이다")

    def test_the_script_file_runs_as_a_program_and_stops_without_a_github_environment(self):
        world = World(self)
        environ = {key: value for key, value in os.environ.items() if not key.startswith("GITHUB_")}
        environ.pop("PYTHONPATH", None)
        environ["PYTHONUTF8"] = "1"
        environ["PYTHONIOENCODING"] = "utf-8"            # 부모 환경(예: cp949)에 흔들리지 않게 자식의 입출력 인코딩을 못박는다(Q 의 R3)
        environ["PATH"] = str(world.root)                         # gh 도 git 도 찾을 수 없게 — 접속 0
        done = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "--root", str(world.root)], capture_output=True, env=environ, timeout=300)
        out = done.stdout.decode("utf-8").replace("\r\n", "\n")
        self.assertEqual(done.returncode, 1)
        self.assertIn("[실패] 1a", out)
        self.assertIn("[실패] 1b", out)
        self.assertNotIn(b"Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
