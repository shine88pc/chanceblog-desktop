"""릴리스 사전 점검 — 릴리스를 만들기 전에 '이 실행이 정말 만들어도 되는가' 를 여섯 가지로 확인한다(RELEASE 설계서 3-3 `build` 잡 단계 2·서명 잡 단계 2, V1REL12·R-2).

쓰는 법(저장소 맨 위 폴더에서, GitHub Actions 실행 안에서): `python -X utf8 scripts/release_preflight.py [--root 폴더]`. 환경은 실행기가 주는 변수만 읽는다 —
`GITHUB_EVENT_NAME`·`GITHUB_REF`·`GITHUB_SHA`·`GITHUB_REPOSITORY`. GitHub 에 묻는 일은 `gh api` 읽기 요청뿐이고(`gh` 가 `GH_TOKEN` 환경 변수를 스스로 읽는다 — 이 도구는 토큰을 읽지도 보이지도 않는다) 시험은 가짜 `gh` 를 끼운다.

확인(번호는 설계서와 같다 — 하나라도 어긋나면 종료 코드 1, 모두 점검한 뒤 어긋난 것을 모두 보인다):
  1 실행 이벤트가 `workflow_dispatch`(1a)이고 ref 가 `refs/heads/main`(1b)이며 실행 커밋이 main 끝과 같다(1c)
  2 `VERSION` 모양이 정식(`X.Y.Z`)이나 후보(`X.Y.Z-rc.N`)뿐이다 — 다른 사전판 글자는 거절
  3 태그 `v<버전>` 이 **없고**(3a) 그 태그의 릴리스(초안 포함)도 없다(3b)
  4 `CHANGELOG.md` 맨 위 절 = `VERSION` 이고 릴리스 노트(그 절)가 모양에 맞다(`docs/RELEASE.md` 릴리스 노트 규칙 — 요약·자세히·이관 노트, 요약 3–10줄·500글자 이하)
  5 이 커밋의 `ci.yml` push 실행이 모두 성공이다 — 실행이 없거나 아직 도는 중이거나 하나라도 성공이 아니면 거절
  6 작업 트리가 깨끗하고 작업 폴더의 커밋이 실행 커밋과 같다
**의심스러우면 거절한다**: `gh` 를 못 찾거나 호출이 실패하거나 응답을 읽을 수 없으면 그 확인은 실패다(통과로 치지 않는다). 이 도구가 보이는 글은 고정 문장·번호·태그·버전·종료 코드뿐이고 `gh` 의 오류 글은 보이지 않는다.
태그(3a)·릴리스(3b) 목록은 `--jq` 없이 **원시 JSON 응답을 엄격히** 읽는다(재작업 1·S-3): 맨 위 값이 모두 JSON 목록이고 모든 항목이 모양에 맞을 때만 '있다·없다' 를 가린다 — 빈 글·공백뿐인 글·`null`·객체·모양이 다른 항목·HTML·잘린 글·남는 글자는
'없음' 이 아니라 **실패**다(빈 응답이 정상인 '없음' 과 구별되지 않던 틈을 닫았다). 정상적인 빈 목록은 정확히 `[]` 다.
한계: 읽기 전용 토큰(`contents: read`)으로는 초안 릴리스가 목록에 안 보일 수 있다 — 초안 확인(3b)은 쓰기 권한이 있는 서명 잡에서 다시 돌 때 완전하다(설계서의 서명 잡 단계 2).
종료 코드: 0 모두 통과 · 1 하나라도 어긋남 · 2 사용법 오류.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import types
from collections import namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "packaging") not in sys.path:
    sys.path.insert(0, str(ROOT / "packaging"))

import release_chain as rc  # noqa: E402

Result = namedtuple("Result", "number name ok detail")
EXPECTED_EVENT = "workflow_dispatch"
EXPECTED_REF = "refs/heads/main"
GH_TIMEOUT = 60
GIT_TIMEOUT = 60
EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
_COMMIT = re.compile(r"[0-9a-f]{40}", re.ASCII)
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", re.ASCII)

NAME_EVENT = "실행 이벤트가 workflow_dispatch 다"
NAME_REF = "ref 가 refs/heads/main 이다"
NAME_TIP = "실행 커밋이 main 끝과 같다"
NAME_VERSION = "VERSION 이 정식 또는 후보(-rc.N) 모양이다"
NAME_TAG = "태그가 아직 없다"
NAME_RELEASE = "그 태그의 릴리스(초안 포함)가 아직 없다"
MSG_TAGS_SHAPE = "태그 목록의 응답을 읽을 수 없다(JSON 목록이 아니거나 모양이 다르다)"
MSG_RELEASES_SHAPE = "릴리스 목록의 응답을 읽을 수 없다(JSON 목록이 아니거나 모양이 다르다)"
NAME_CHANGELOG = "변경 이력 맨 위 절이 VERSION 이고 릴리스 노트 모양이 맞다"
NAME_CI = "이 커밋의 ci.yml push 실행이 모두 성공이다"
NAME_TREE = "작업 트리가 깨끗하고 작업 폴더의 커밋이 실행 커밋이다"
SKIPPED = "건너뜀 — VERSION 이 올바르지 않아 확인할 수 없다"
GH_FAILED = "gh 호출이 실패했다(종료 코드 %d)"
USAGE = "사용법 오류: --root 폴더 만 쓴다."


def _ok(number, name, detail=""):
    return Result(number, name, True, detail)


def _fail(number, name, detail):
    return Result(number, name, False, detail)


def _plain(text, limit=80):
    shown = "".join(char if char.isprintable() else "?" for char in str(text))
    return shown if len(shown) <= limit else shown[:limit - 1] + "…"


def run_gh(args, *, run=subprocess.run):
    """`gh` 를 고정 인자 목록으로 부른다(셸 없음) → 결과 코드·표준 출력이 든 객체. 못 찾거나 시간이 넘으면 결과 코드 127 로 돌려준다."""
    try:
        return run(["gh", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=GH_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return types.SimpleNamespace(returncode=127, stdout="", stderr="")


def _lines(text):
    """`gh` 표준 출력 → 줄들(앞뒤 공백·감싼 따옴표를 걷는다)."""
    return [line.strip().strip('"') for line in (text or "").splitlines() if line.strip()]


def _repo_ok(repo):
    """`소유자/이름` 모양이고 두 조각 모두 점으로만 이루어지지 않았다(`..`·`.` 은 `repos/<이름>/…` 경로를 다른 곳으로 바꾼다)."""
    return isinstance(repo, str) and _REPO.fullmatch(repo) is not None and all(part.strip(".") for part in repo.split("/"))


def _json_arrays(text):
    """`gh api` 의 원시 응답 글 → 맨 위 값이 모두 JSON 목록인 조각들(목록의 목록) 또는 None. 빈 글·공백뿐인 글·JSON 이 아닌 글·목록이 아닌 값(`null`·객체·글·숫자)·
    조각 사이나 뒤에 남는 글자·너무 깊은 겹침은 None(의심스러우면 거절 — 빈 응답은 '없음' 이 아니다). 쪽마다 목록이 따로 붙어 오는 모양(`[...][...]`)도 읽는다."""
    if not isinstance(text, str):
        return None
    decoder, index, parts = json.JSONDecoder(), 0, []
    try:
        while True:
            while index < len(text) and text[index] in " \t\r\n":
                index += 1
            if index >= len(text):
                break
            value, index = decoder.raw_decode(text, index)
            if not isinstance(value, list):
                return None
            parts.append(value)
    except (ValueError, RecursionError):
        return None
    return parts or None


def _items(text, key, accept, *, single):
    """원시 응답 글 → 항목의 `key` 값들 또는 None. 목록이 정확히 하나여야 하면(`single`) 둘 이상 붙어 오는 것은 모양이 다르다. 모든 항목이 객체이고 `key` 가 `accept` 를 만족하는 글이어야 한다."""
    parts = _json_arrays(text)
    if parts is None or (single and len(parts) != 1):
        return None
    values = []
    for part in parts:
        for item in part:
            value = item.get(key) if isinstance(item, dict) else None
            if not isinstance(value, str) or not accept(value):
                return None
            values.append(value)
    return values


# ---- 확인 하나씩(순수 부품 — 가짜 환경·가짜 `gh` 로 시험한다) -------------------------------------------------------------------------------------------
def check_event(environ):
    value = environ.get("GITHUB_EVENT_NAME", "")
    return _ok("1a", NAME_EVENT) if value == EXPECTED_EVENT else _fail("1a", NAME_EVENT, "실행 이벤트가 " + (_plain(value, 40) or "없음"))


def check_ref(environ):
    value = environ.get("GITHUB_REF", "")
    return _ok("1b", NAME_REF) if value == EXPECTED_REF else _fail("1b", NAME_REF, "ref 가 " + (_plain(value, 60) or "없음"))


def check_main_tip(gh, repo, sha):
    if not isinstance(sha, str) or _COMMIT.fullmatch(sha) is None:
        return _fail("1c", NAME_TIP, "실행 커밋(GITHUB_SHA)이 40자리 소문자 16진수가 아니다")
    if not _repo_ok(repo):
        return _fail("1c", NAME_TIP, "저장소 이름(GITHUB_REPOSITORY)을 알 수 없다")
    done = gh(["api", f"repos/{repo}/git/ref/heads/main", "--jq", ".object.sha"])
    if done.returncode != 0:
        return _fail("1c", NAME_TIP, GH_FAILED % done.returncode)
    tips = _lines(done.stdout)
    if len(tips) != 1 or _COMMIT.fullmatch(tips[0]) is None:
        return _fail("1c", NAME_TIP, "main 끝의 응답을 읽을 수 없다")
    return _ok("1c", NAME_TIP) if tips[0] == sha else _fail("1c", NAME_TIP, "main 끝이 실행 커밋과 다르다 — 그 사이 main 이 바뀌었다")


def check_version(raw):
    """`VERSION` 파일 내용 → (결과, 버전 또는 None)."""
    version = rc.read_version_file(raw) if isinstance(raw, str) else None
    if version is None:
        return _fail("2", NAME_VERSION, "VERSION 을 읽지 못했거나 정식(X.Y.Z)·후보(X.Y.Z-rc.N) 모양이 아니다"), None
    return _ok("2", NAME_VERSION, version), version


def check_tag_absent(gh, repo, version):
    tag = rc.tag_of(version)
    if not _repo_ok(repo):
        return _fail("3a", NAME_TAG, "저장소 이름(GITHUB_REPOSITORY)을 알 수 없다")
    done = gh(["api", f"repos/{repo}/git/matching-refs/tags/{tag}"])
    if done.returncode != 0:
        return _fail("3a", NAME_TAG, GH_FAILED % done.returncode)
    refs = _items(done.stdout, "ref", lambda value: value.startswith("refs/tags/"), single=True)
    if refs is None:
        return _fail("3a", NAME_TAG, MSG_TAGS_SHAPE)
    if "refs/tags/" + tag in refs:
        return _fail("3a", NAME_TAG, f"태그 {tag} 가 이미 있다")
    return _ok("3a", NAME_TAG, tag)


def check_release_absent(gh, repo, version):
    tag = rc.tag_of(version)
    if not _repo_ok(repo):
        return _fail("3b", NAME_RELEASE, "저장소 이름(GITHUB_REPOSITORY)을 알 수 없다")
    done = gh(["api", f"repos/{repo}/releases", "--paginate"])
    if done.returncode != 0:
        return _fail("3b", NAME_RELEASE, GH_FAILED % done.returncode)
    tags = _items(done.stdout, "tag_name", bool, single=False)
    if tags is None:
        return _fail("3b", NAME_RELEASE, MSG_RELEASES_SHAPE)
    if tag in tags:
        return _fail("3b", NAME_RELEASE, f"태그 {tag} 의 릴리스(초안 포함)가 이미 있다")
    return _ok("3b", NAME_RELEASE, tag)


def check_changelog(changelog, version):
    if not isinstance(changelog, str):
        return _fail("4", NAME_CHANGELOG, "변경 이력 파일을 읽지 못했다")
    top = rc.top_changelog_version(changelog)
    if top != version:
        return _fail("4", NAME_CHANGELOG, f"변경 이력 맨 위 절이 {_plain(top or '없음', 40)} 이다(VERSION 은 {version})")
    try:
        heading, notes = rc.notes_section(changelog, version)
    except rc.NotesError:
        return _fail("4", NAME_CHANGELOG, "변경 이력에서 그 버전의 절을 정확히 하나 찾지 못했다")
    problems = rc.notes_problems(heading, notes, version)
    if problems:
        return _fail("4", NAME_CHANGELOG, "릴리스 노트 모양이 틀리다: " + ", ".join(rc.describe(item) for item in problems[:6]))
    return _ok("4", NAME_CHANGELOG, version)


def check_ci(gh, repo, sha):
    if not isinstance(sha, str) or _COMMIT.fullmatch(sha) is None or not _repo_ok(repo):
        return _fail("5", NAME_CI, "저장소 이름이나 실행 커밋을 알 수 없다")
    done = gh(["api", f"repos/{repo}/actions/workflows/ci.yml/runs?head_sha={sha}&per_page=100", "--jq",
               '.workflow_runs[] | [.event, .status, (.conclusion // ""), .head_sha] | @tsv'])
    if done.returncode != 0:
        return _fail("5", NAME_CI, GH_FAILED % done.returncode)
    rows = []
    for line in _lines(done.stdout):
        parts = line.split("\t")
        if len(parts) != 4:
            return _fail("5", NAME_CI, "ci.yml 실행 목록의 응답을 읽을 수 없다")
        rows.append(parts)
    runs = [row for row in rows if row[3] == sha and row[0] == "push"]
    if not runs:
        return _fail("5", NAME_CI, "이 커밋의 ci.yml push 실행이 없다")
    if any(row[1] != "completed" for row in runs):
        return _fail("5", NAME_CI, "이 커밋의 ci.yml 실행이 아직 끝나지 않았다")
    bad = [row for row in runs if row[2] != "success"]
    if bad:
        return _fail("5", NAME_CI, f"이 커밋의 ci.yml 실행 {len(bad)}건이 성공이 아니다(결과 {_plain(bad[0][2] or '없음', 20)})")
    return _ok("5", NAME_CI, f"{len(runs)}건 성공")


def check_tree(run, root, sha):
    def git(*args):
        try:
            return run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            return types.SimpleNamespace(returncode=127, stdout="", stderr="")
    status = git("status", "--porcelain")
    if status.returncode != 0:
        return _fail("6", NAME_TREE, "git 상태를 읽지 못했다")
    if (status.stdout or "").strip():
        return _fail("6", NAME_TREE, "작업 트리가 깨끗하지 않다")
    head = git("rev-parse", "HEAD")
    if head.returncode != 0 or (head.stdout or "").strip() != sha:
        return _fail("6", NAME_TREE, "작업 폴더의 커밋이 실행 커밋과 다르다")
    return _ok("6", NAME_TREE)


def run_checks(root, environ, *, gh, run):
    """여섯 가지를 모두 점검한다 → [Result](한 가지가 어긋나도 나머지는 계속 본다)."""
    root = Path(root)
    repo, sha = environ.get("GITHUB_REPOSITORY", ""), environ.get("GITHUB_SHA", "")
    results = [check_event(environ), check_ref(environ), check_main_tip(gh, repo, sha)]
    try:
        raw = (root / "VERSION").read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raw = None
    result, version = check_version(raw)
    results.append(result)
    if version is None:
        results += [_fail("3a", NAME_TAG, SKIPPED), _fail("3b", NAME_RELEASE, SKIPPED), _fail("4", NAME_CHANGELOG, SKIPPED)]
    else:
        results.append(check_tag_absent(gh, repo, version))
        results.append(check_release_absent(gh, repo, version))
        try:
            changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            changelog = None
        results.append(check_changelog(changelog, version))
    results.append(check_ci(gh, repo, sha))
    results.append(check_tree(run, root, sha))
    return results


# ---- 명령줄 -----------------------------------------------------------------------------------------------------------------------------------------
class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _UsageError()


def main(argv=None, *, environ=None, run=subprocess.run, gh=None, stdout=None, stderr=None):
    """명령줄 진입점. 시험이 `environ`(가짜 실행 환경)·`run`(git 호출)·`gh`(인자 목록 → 결과)·`stdout`·`stderr` 를 바꿔 끼운다."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    env = os.environ if environ is None else environ
    parser = _Parser(add_help=False, allow_abbrev=False)
    parser.add_argument("--root", default=str(ROOT))
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    except _UsageError:
        err.write(USAGE + "\n")
        return EXIT_USAGE
    runner = gh if gh is not None else (lambda call: run_gh(call, run=run))
    results = run_checks(args.root, env, gh=runner, run=run)
    for item in results:
        out.write(("[통과] " if item.ok else "[실패] ") + f"{item.number} {item.name}" + (f": {item.detail}" if item.detail else "") + "\n")
    failed = [item for item in results if not item.ok]
    if failed:
        err.write(f"사전 점검 실패: {len(failed)}건 — 릴리스를 만들지 않는다.\n")
        return EXIT_FAILED
    out.write("사전 점검 통과: 모두 맞다.\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
