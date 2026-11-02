"""명령줄 — `python -m chanceblog_desktop <명령>`. 글 만들기·검토·승인·미리 보기·GitHub Pages 올리기·네이버 복사 패키지·점검·백업을 한 곳에서 한다(화면(GUI)은 아직 없다).

규칙:
  · **확인 없이는 올리지 않는다** — `publish-pages` 는 기본이 미리 보기(dry run, 아무것도 안 함)이고 `--yes` 가 있어야 실제로 기록(commit)하고 올린다(push). 글 지우기·백업으로 되돌리기(`restore`)도 `--yes` 가 있어야 한다.
  · 종료 코드: 0 정상 · 1 처리된 오류(오류 코드·원인·하실 일을 보여 준다 — 예상한 오류에 스택 추적을 보이지 않는다) · 2 사용법 오류.
  · 화면에 나가는 모든 글(오류·JSON 포함)은 `security.mask` 를 거친다. 키·토큰을 읽거나 보이지 않는다(환경 변수는 데이터 폴더·저장소 폴더 위치만 읽는다).
  · `--json` 은 기계가 읽는 출력이다: 정상이면 `{"ok": true, "command": …, "data": …}`, 오류면 `{"ok": false, "command": …, "error": {…}}`.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..content import status as st
from ..errors import AppError
from ..security.mask import MAX_MASK_INPUT, mask
from . import format as fmt
from . import naver_flow, pages_flow, projects, review
from .context import make_context
from .doctor import doctor_ok, run_doctor
from .naver_flow import NaverOptions
from .previews import PagesParams, preview_naver, preview_pages

PROG = "python -m chanceblog_desktop"
MAX_WAIT_SECONDS = 6 * 3600                  # --wait 의 상한
MAX_INPUT_FILE_BYTES = 5 * 1024 * 1024        # 원고·HTML·본문 파일의 최대 크기(원고 자체는 projects.MAX_MANUSCRIPT_BYTES)
PLATFORM_ALIAS = {"pages": "github_pages", "github_pages": "github_pages", "naver_a": "naver_a", "naver_b": "naver_b"}
PROFILE_FIELDS = (("name", "display_name"), ("url", "blog_url"), ("topic", "topic"), ("audience", "audience"), ("tone", "tone"), ("image_spec", "image_spec"),
                  ("publish_cycle", "publish_cycle"), ("disclosure", "disclosure"))
_USAGE_TRANSLATIONS = (
    (re.compile(r"the following arguments are required: (.+)"), "빠진 항목이 있습니다: {0}"),
    (re.compile(r"unrecognized arguments: (.+)"), "알 수 없는 항목입니다: {0}"),
    (re.compile(r"expected one argument"), "값이 필요합니다"),
    (re.compile(r"argument (.+?): invalid choice: (.+?) \(choose from (.+)\)"), "{0} 에 쓸 수 없는 값 {1} 입니다. 다음 중에서 고릅니다: {2}"),
    (re.compile(r"argument (.+?): invalid (?:int|float) value: (.+)"), "{0} 에는 숫자를 써야 합니다(받은 값 {1})"),
    (re.compile(r"argument (.+?): (.+)"), "{0}: {1}"),                      # 우리가 정한 값 검사(예: --wait 의 범위)의 말
)


class UsageError(Exception):
    """사용법 오류(종료 코드 2) — 명령이나 항목을 잘못 썼다."""


@dataclass
class Output:
    lines: list
    data: dict = field(default_factory=dict)
    code: int = 0


class KoreanHelpFormatter(argparse.RawDescriptionHelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, "사용법: " if prefix is None else prefix)


class KoreanParser(argparse.ArgumentParser):
    """한국어 도움말·사용법 오류를 내고, 옵션 이름을 줄여 쓰는 것(`--y` → `--yes`)을 받지 않는다 — 줄임말이 실제로 올리는 명령을 일으키지 못하게."""

    def __init__(self, *args, **kwargs):
        kwargs["allow_abbrev"] = False
        kwargs["add_help"] = False                      # argparse 의 영어 도움말 항목을 쓰지 않고 아래에서 한국어로 직접 더한다
        kwargs.setdefault("formatter_class", KoreanHelpFormatter)
        super().__init__(*args, **kwargs)
        self.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="이 도움말을 보여 주고 끝냅니다")
        for attribute, title in (("_positionals", "위치 인자"), ("_optionals", "옵션")):          # 영어 제목('positional arguments'·'options')을 바꾼다
            group = getattr(self, attribute, None)
            if group is not None:
                group.title = title

    def error(self, message):
        for pattern, template in _USAGE_TRANSLATIONS:
            found = pattern.search(message)
            if found:
                message = template.format(*found.groups())
                break
        raise UsageError(message)


# ---- 입력 읽기 ----------------------------------------------------------------------------------------------------------------
def read_text_file(path):
    """UTF-8(BOM 있어도) 또는 cp949(예전 메모장)로 저장한 글 파일을 읽는다(최대 5MB). 못 읽으면 CONTENT_INVALID."""
    try:
        target = Path(path)
        too_big = target.stat().st_size > MAX_INPUT_FILE_BYTES          # 거대한 파일을 통째로 메모리에 올리지 않는다
        data = b"" if too_big else target.read_bytes()
    except OSError as error:
        raise AppError("CONTENT_INVALID", {"항목": "원고 파일"}, detail=f"{type(error).__name__}: 파일을 읽을 수 없다") from None
    if too_big:
        raise AppError("CONTENT_INVALID", {"항목": "원고 파일"}, detail=f"파일이 너무 크다(최대 {MAX_INPUT_FILE_BYTES // (1024 * 1024)}MB)")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AppError("CONTENT_INVALID", {"항목": "원고 파일의 글자 모양"}, detail="UTF-8 이나 cp949 로 읽을 수 없다")


def read_input(file, text, what):
    if (file is None) == (text is None):
        raise UsageError(f"{what}은(는) --file(파일)과 --text(직접 입력) 중 하나만 써야 합니다.")
    return read_text_file(file) if file is not None else text


def wait_seconds(text):
    """`--wait` 값 — 0 이상 6시간(21600초) 이하의 정수. 끝없이 기다리는 값은 받지 않는다."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"숫자를 써야 합니다(받은 값 {text})") from None
    if not 0 <= value <= MAX_WAIT_SECONDS:
        raise argparse.ArgumentTypeError(f"0 이상 {MAX_WAIT_SECONDS} 이하의 초를 써야 합니다(받은 값 {value})")
    return value


def split_list(value):
    return tuple(item.strip() for item in (value or "").split(",") if item.strip())


def pages_params(args):
    if not (args.category and args.lang and args.image_url):
        raise UsageError("GitHub Pages 글은 --category(분야), --lang(ko 또는 en), --image-url(https 대표 이미지 주소)이 모두 필요합니다.")
    source = None
    if args.source_name or args.source_url:
        if not (args.source_name and args.source_url):
            raise UsageError("출처를 적으려면 --source-name 과 --source-url 을 함께 써야 합니다.")
        source = {"name": args.source_name, "url": args.source_url}
        if args.source_title:
            source["title"] = args.source_title
    return PagesParams(args.category, args.lang, args.image_url, split_list(args.tags), args.description, source)


def naver_options(args):
    body = read_text_file(args.body_file) if args.body_file else None
    return NaverOptions(args.title, body, split_list(args.tags), args.category or "", not args.no_ai_disclosure)


def references_and_images(args):
    refs = tuple(args.ref) if getattr(args, "ref", None) else None
    images = tuple(projects.parse_asset(item) for item in args.image) if getattr(args, "image", None) else None
    return refs, images


# ---- 명령 ----------------------------------------------------------------------------------------------------------------------
def cmd_doctor(ctx, args):
    results = run_doctor(ctx, online=args.online)
    return Output(fmt.doctor_lines(results), {"checks": [item.to_dict() for item in results]}, 0 if doctor_ok(results) else 1)


def cmd_connect(ctx, args):
    folder = Path(os.path.abspath(os.path.expanduser(args.folder)))
    info = ctx.backend.inspect(folder)                       # 올바른 chanceblog 저장소가 아니면 여기서 오류 코드로 멈춘다(설정을 바꾸지 않는다)
    ctx.settings.save_repo_path(folder)
    lines = [f"연결했습니다: {folder}", f"  origin: {info.origin}   브랜치: {info.branch}", "  이 폴더 위치는 사용자 데이터 폴더의 설정 파일에만 기억합니다(저장소에는 올라가지 않습니다).",
             f"  올리기 권한은 `{PROG} doctor --online` 으로 점검합니다."]
    return Output(lines, {"repo": str(folder), "origin": info.origin, "branch": info.branch})


def cmd_new(ctx, args):
    refs, images = references_and_images(args)
    view = projects.new_project(ctx, args.title, read_input(args.file, args.text, "원고"), references=refs or (), assets=images or ())
    return Output(["글을 만들었습니다.", *fmt.project_lines(view)], {"project": view.to_dict()})


def cmd_import_html(ctx, args):
    refs, images = references_and_images(args)
    view = projects.import_html(ctx, args.title, read_input(args.file, args.text, "HTML 글"), references=refs or (), assets=images or ())
    return Output(["기존 글(HTML)을 Markdown 으로 바꿔 불러왔습니다(허용 태그만 남고 스크립트·속성은 사라집니다).", *fmt.project_lines(view)], {"project": view.to_dict()})


def cmd_list(ctx, args):
    rows = projects.list_projects(ctx)
    return Output(fmt.project_row_lines(rows), {"projects": [row.to_dict() for row in rows]})


def cmd_show(ctx, args):
    view = projects.show_project(ctx, args.id)
    return Output(fmt.project_lines(view, full=args.full), {"project": view.to_dict(with_text=args.full)})


def cmd_edit(ctx, args):
    markdown = None if args.file is None and args.text is None else read_input(args.file, args.text, "원고")
    refs, images = references_and_images(args)
    result = projects.edit_project(ctx, args.id, title=args.title, markdown=markdown, references=() if args.clear_refs else refs, assets=() if args.clear_images else images)
    if not result.changed:
        lines = ["바뀐 것이 없습니다."]
    else:
        lines = [f"고쳤습니다(판 {result.project.revision})."]
        if result.reset_platforms:
            lines.append("원고가 바뀌어 아래 플랫폼의 검토·승인이 풀렸습니다 — 글을 다시 만들어(review) 처음부터 다시 검토해야 합니다: " + ", ".join(fmt.PLATFORM_KO[name] for name in result.reset_platforms))
    return Output(lines + fmt.project_lines(result.project), result.to_dict())


def _platform(args):
    return PLATFORM_ALIAS[args.platform]


def cmd_review(ctx, args):
    platform = _platform(args)
    result = review.request_review(ctx, args.id, platform, pages=pages_params(args) if platform == "github_pages" else None,
                                   naver_options=naver_options(args) if platform != "github_pages" else None)
    return Output(fmt.review_lines(result), result.to_dict())


def cmd_preview(ctx, args):
    if args.platform in ("pages", "github_pages"):
        preview = preview_pages(ctx, args.id, pages_params(args))
        return Output(fmt.pages_preview_lines(preview, full=args.full), preview.to_dict(with_text=args.full))
    options = {args.platform: naver_options(args)} if args.platform in ("naver_a", "naver_b") else {}
    preview = preview_naver(ctx, args.id, options)
    return Output(fmt.naver_preview_lines(preview, full=args.full), preview.to_dict(with_text=args.full))


def cmd_approve(ctx, args):
    result = review.grant_approval(ctx, args.id, _platform(args), similarity_approved=args.similarity_approved)
    if result.platform == "github_pages":
        lines = fmt.approval_lines(result, "승인했습니다.") + [f"  다음: `{PROG} publish-pages {fmt.short_id(result.project_id)}` 로 미리 본 뒤 `--yes` 로 올립니다."]
    else:
        lines = fmt.approval_lines(result, "복사 준비를 마쳤습니다.") + [f"  다음: `{PROG} naver-package {fmt.short_id(result.project_id)} --blog {result.platform}` 로 복사용 글을 받습니다."]
    return Output(lines, result.to_dict())


def cmd_revoke(ctx, args):
    result = review.revoke_approval(ctx, args.id, _platform(args))
    return Output(fmt.approval_lines(result, "승인을 거뒀습니다(검토 중으로 되돌렸습니다)."), result.to_dict())


def cmd_publish_pages(ctx, args):
    if args.cancel:
        report = pages_flow.cancel_pages_publish(ctx, args.id, confirmed=args.yes)
        return Output(["올리지 않은 글 기록을 되돌렸습니다.", *[f"  - {step}" for step in report.steps]], report.to_dict())
    if args.yes:
        report = pages_flow.run_pages_publish(ctx, args.id, confirmed=True, wait=not args.no_wait, deadline=args.wait)
    else:
        report = pages_flow.preview_publish(ctx, args.id, deadline=args.wait)
    return Output(fmt.publish_report_lines(report), report.to_dict())


def cmd_check_deploy(ctx, args):
    report = pages_flow.check_pages_deploy(ctx, args.id, deadline=args.wait)
    return Output(fmt.publish_report_lines(report), report.to_dict())


def cmd_naver_package(ctx, args):
    issue = review.issue_naver_package(ctx, args.id, args.blog, similarity_approved=args.similarity_approved)
    return Output(fmt.naver_issue_lines(issue), issue.to_dict())


def cmd_naver_done(ctx, args):
    result = review.record_naver_published(ctx, args.id, args.blog, args.url)
    return Output(fmt.approval_lines(result, "발행 주소를 기록했습니다."), result.to_dict())


def cmd_naver_profile(ctx, args):
    if args.action == "show":
        found = ctx.settings.naver_profile_dicts()
        lines = [f"{fmt.PLATFORM_KO[key]}: {item.get('display_name', '')} — {item.get('blog_url', '')}" for key, item in sorted(found.items())] or ["설정된 네이버 블로그 프로필이 없습니다."]
        return Output(lines, {"profiles": found})
    if not args.blog:
        raise UsageError("`naver-profile set` 에는 블로그 구분(naver_a 또는 naver_b)이 필요합니다.")
    fields = {target: getattr(args, source) for source, target in PROFILE_FIELDS if getattr(args, source) is not None}
    for source, target in (("tags", "default_tags"), ("forbidden", "forbidden_phrases")):
        if getattr(args, source) is not None:
            fields[target] = list(split_list(getattr(args, source)))
    if args.category_map:
        pairs = [item.split("=", 1) for item in args.category_map]
        if any(len(pair) != 2 for pair in pairs):
            raise UsageError("--category-map 은 `원고분류=네이버카테고리` 모양이어야 합니다.")
        fields["categories"] = [[left.strip(), right.strip()] for left, right in pairs]
    for source, target in (("min_chars", "min_chars"), ("max_chars", "max_chars")):
        if getattr(args, source) is not None:
            fields[target] = getattr(args, source)
    profile = naver_flow.set_profile(ctx.settings, args.blog, fields)
    return Output([f"{fmt.PLATFORM_KO[profile.key]} 프로필을 저장했습니다: {profile.display_name} — {profile.blog_url}"], {"profile": profile.to_dict()})


def cmd_backup(ctx, args):
    path = projects.backup_store(ctx)
    return Output([f"백업을 만들었습니다: {path}", "  (최근 10개만 남기고 오래된 것은 지웁니다)"], {"backup": str(path)})


def cmd_restore(ctx, args):
    if (args.file is None) == (not args.latest):
        raise UsageError("백업 파일을 적거나(`restore 파일`) 가장 최근 백업을 쓰려면 --latest 를 쓰세요 — 둘 중 하나만 씁니다.")
    if not args.yes:
        source = projects.resolve_backup(ctx, args.file, latest=args.latest)         # 어느 백업인지 보여 주려고 이름만 정한다(열지도 바꾸지도 않는다)
        raise AppError("CONFIRMATION_REQUIRED", {"항목": f"백업으로 되돌리기 — {source.name}"},
                       detail="지금 글 저장소의 내용이 그 백업의 내용으로 통째로 바뀝니다(바꾸기 직전 상태는 backups 폴더 안 before-restore 에 따로 백업해 둡니다) — 맞으면 같은 명령 끝에 --yes 를 붙여 다시 실행합니다")
    source, safety = projects.restore_store(ctx, args.file, latest=args.latest, confirmed=True)
    return Output([f"백업으로 되돌렸습니다: {source}", f"  되돌리기 직전의 상태는 따로 백업해 두었습니다: {safety}"], {"restored_from": str(source), "safety_backup_folder": str(safety)})


def cmd_delete(ctx, args):
    if not args.yes:
        view = projects.show_project(ctx, args.id)                       # 어느 글인지 보여 주려고 읽기만 한다(아무것도 지우지 않는다)
        states = ", ".join(f"{fmt.PLATFORM_KO[item.platform]}: {fmt.status_text(item.status)}" for item in view.variants if item.status != st.NOT_STARTED)
        raise AppError("CONFIRMATION_REQUIRED", {"항목": f"글 지우기 — 「{view.title}」(번호 {fmt.short_id(view.project_id)}, {states or '아직 어느 곳에도 내보내지 않음'})"},
                       detail="지우면 되돌릴 수 없습니다 — 이 글이 맞으면 같은 명령 끝에 --yes 를 붙여 다시 실행합니다")
    project_id, note = projects.delete_project(ctx, args.id, confirmed=args.yes)
    return Output([f"글을 지웠습니다: {project_id}"] + ([note] if note else []), {"deleted": project_id})


# ---- 사용법(argparse) -------------------------------------------------------------------------------------------------------------
def _common():
    common = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", help="사람이 아니라 프로그램이 읽기 쉬운 JSON 으로 출력합니다")
    common.add_argument("--data-dir", metavar="폴더", help="원고·설정·백업을 둘 폴더(기본: 사용자 데이터 폴더). 저장소 폴더 안은 안 됩니다")
    common.add_argument("--repo", metavar="폴더", help="이번 한 번만 쓸 chanceblog 저장소 폴더(저장해 둔 연결보다 우선)")
    common.add_argument("--verbose", action="store_true", help="오류의 기록용 한 줄(키·토큰은 가려짐)도 보여 줍니다")
    common.add_argument("--debug", action="store_true", help="예상하지 못한 오류에서 자세한 추적 정보를 그대로 보여 줍니다(개발용)")
    return common


def _pages_options(parser):
    parser.add_argument("--category", metavar="분야", help="글의 분야(Pages: 폴더·머리말 / 네이버: 원고 분류)")
    parser.add_argument("--lang", choices=("ko", "en"), help="글의 언어(GitHub Pages)")
    parser.add_argument("--image-url", metavar="주소", help="대표 이미지의 https 주소(GitHub Pages)")
    parser.add_argument("--tags", metavar="a,b,c", help="태그(쉼표로 나눔)")
    parser.add_argument("--description", metavar="설명", help="한 줄 설명(비우면 본문에서 뽑습니다)")
    parser.add_argument("--source-name", metavar="이름", help="출처 이름(출처를 적을 때)")
    parser.add_argument("--source-url", metavar="주소", help="출처 주소(http 또는 https)")
    parser.add_argument("--source-title", metavar="제목", help="출처 글의 제목(없으면 이 글의 제목)")


def _naver_options(parser):
    parser.add_argument("--title", metavar="제목", help="네이버 글의 제목(비우면 원고 제목) — 블로그마다 다르게 쓸 때")
    parser.add_argument("--body-file", metavar="파일", help="네이버 글의 본문 파일(비우면 원고 본문) — 블로그마다 다르게 쓸 때")
    parser.add_argument("--no-ai-disclosure", action="store_true", help="AI 활용 고지문을 붙이지 않습니다(AI 도움을 받지 않은 글)")


def build_parser():
    common = _common()
    parser = KoreanParser(prog=PROG, parents=[common],
                          description="여러 블로그(GitHub Pages·네이버)의 글을 쓰고·검토하고·내보내는 개인용 도구(명령줄판). 글을 올리는 명령은 기본이 미리 보기이고, --yes 가 있어야 실제로 올립니다.",
                          epilog="처음이라면: doctor → connect 폴더 → new → review → approve → publish-pages(미리 보기) → publish-pages --yes")
    sub = parser.add_subparsers(dest="command", metavar="명령", parser_class=KoreanParser)
    sub.required = True

    def add(name, handler, help_text):
        found = sub.add_parser(name, parents=[common], help=help_text, description=help_text)
        found.set_defaults(handler=handler)
        return found

    found = add("doctor", cmd_doctor, "프로그램·글 저장소·연결한 저장소 상태를 점검합니다(읽기만 합니다)")
    found.add_argument("--online", action="store_true", help="올리기 권한도 점검합니다(네트워크를 씁니다 — 실제로 올리지는 않습니다)")
    found = add("connect", cmd_connect, "GitHub Pages 에 올릴 때 쓸 chanceblog 저장소 폴더를 확인하고 연결합니다")
    found.add_argument("folder", metavar="폴더", help="chanceblog 를 받아 둔 폴더")
    found = add("new", cmd_new, "Markdown 글로 새 글(프로젝트)을 만듭니다")
    found.add_argument("--title", required=True, metavar="제목")
    found.add_argument("--file", metavar="파일", help="원고 파일(UTF-8)")
    found.add_argument("--text", metavar="본문", help="원고를 직접 입력")
    found.add_argument("--ref", action="append", metavar="주소", help="출처 주소(여러 번 쓸 수 있음)")
    found.add_argument("--image", action="append", metavar="파일|설명|문단번호", help="글에 쓸 이미지(여러 번 쓸 수 있음)")
    found = add("import-html", cmd_import_html, "기존에 쓴 HTML 글을 Markdown 으로 바꿔 불러옵니다")
    found.add_argument("--title", required=True, metavar="제목")
    found.add_argument("--file", metavar="파일", help="HTML 파일")
    found.add_argument("--text", metavar="HTML", help="HTML 을 직접 입력")
    found.add_argument("--ref", action="append", metavar="주소")
    found.add_argument("--image", action="append", metavar="파일|설명|문단번호")
    add("list", cmd_list, "글 목록과 플랫폼별 상태를 보여 줍니다")
    found = add("show", cmd_show, "글 하나의 자세한 상태와 다음에 할 일을 보여 줍니다")
    found.add_argument("id", metavar="글번호")
    found.add_argument("--full", action="store_true", help="본문도 보여 줍니다")
    found = add("edit", cmd_edit, "원고를 고칩니다(바뀌면 승인이 풀리고 처음부터 다시 검토합니다)")
    found.add_argument("id", metavar="글번호")
    found.add_argument("--title", metavar="제목")
    found.add_argument("--file", metavar="파일")
    found.add_argument("--text", metavar="본문")
    found.add_argument("--ref", action="append", metavar="주소", help="출처 주소 목록을 이것으로 바꿉니다")
    found.add_argument("--clear-refs", action="store_true", help="출처 주소를 모두 지웁니다")
    found.add_argument("--image", action="append", metavar="파일|설명|문단번호", help="이미지 목록을 이것으로 바꿉니다")
    found.add_argument("--clear-images", action="store_true", help="이미지를 모두 지웁니다")
    found = add("review", cmd_review, "글을 그 플랫폼용으로 만들어 검토 중으로 보냅니다(미리 보기도 함께 보여 줍니다)")
    found.add_argument("id", metavar="글번호")
    found.add_argument("--platform", required=True, choices=("pages", "github_pages", "naver_a", "naver_b"))
    _pages_options(found)
    _naver_options(found)
    found = add("preview", cmd_preview, "플랫폼에 맞게 만들어 보여 주기만 합니다(아무것도 저장하지 않습니다)")
    found.add_argument("id", metavar="글번호")
    found.add_argument("--platform", required=True, choices=("pages", "github_pages", "naver", "naver_a", "naver_b"), help="naver 는 A·B 를 함께 보여 주고 서로 비교합니다")
    found.add_argument("--full", action="store_true", help="본문 전체를 보여 줍니다")
    _pages_options(found)
    _naver_options(found)
    found = add("approve", cmd_approve, "읽어 본 글을 승인합니다(GitHub Pages 는 검사를 다시 통과해야 합니다)")
    found.add_argument("id", metavar="글번호")
    found.add_argument("--platform", required=True, choices=("pages", "github_pages", "naver_a", "naver_b"))
    found.add_argument("--similarity-approved", action="store_true", help="네이버 두 블로그 글이 많이 비슷해도 내가 직접 보고 승인합니다")
    found = add("revoke", cmd_revoke, "승인을 거둡니다(검토 중으로 되돌립니다)")
    found.add_argument("id", metavar="글번호")
    found.add_argument("--platform", required=True, choices=("pages", "github_pages", "naver_a", "naver_b"))
    found = add("publish-pages", cmd_publish_pages, "승인한 글을 GitHub Pages(연결한 chanceblog 의 main)에 올립니다. 기본은 미리 보기 — 실제로 올리려면 --yes")
    found.add_argument("id", metavar="글번호")
    found.add_argument("--yes", action="store_true", help="미리 본 내용대로 실제로 기록(commit)하고 올립니다(push)")
    found.add_argument("--no-wait", action="store_true", help="올린 뒤 공개 주소가 열리는지 기다리지 않습니다(나중에 check-deploy)")
    found.add_argument("--wait", type=wait_seconds, default=pages_flow.DEFAULT_DEADLINE, metavar="초", help="공개 주소가 열리기를 기다리는 최대 시간(기본 720초, 최대 21600초)")
    found.add_argument("--cancel", action="store_true", help="올리지 않은 글 기록(commit)을 되돌립니다(--yes 필요)")
    found = add("check-deploy", cmd_check_deploy, "올린 글의 공개 주소가 열리는지 확인합니다(열리면 '공개됨' 으로 기록)")
    found.add_argument("id", metavar="글번호")
    found.add_argument("--wait", type=wait_seconds, default=pages_flow.DEFAULT_DEADLINE, metavar="초", help="기다리는 최대 시간(0 이면 한 번만 확인, 최대 21600초)")
    found = add("naver-package", cmd_naver_package, "네이버 복사용 글(제목·본문·태그·이미지 자리)을 내어 줍니다 — 검토 중이면 이 명령이 승인입니다")
    found.add_argument("id", metavar="글번호")
    found.add_argument("--blog", required=True, choices=("naver_a", "naver_b"))
    found.add_argument("--similarity-approved", action="store_true", help="두 블로그 글이 많이 비슷해도 내가 직접 보고 승인합니다")
    found = add("naver-done", cmd_naver_done, "네이버에 직접 발행한 글의 주소를 기록합니다")
    found.add_argument("id", metavar="글번호")
    found.add_argument("--blog", required=True, choices=("naver_a", "naver_b"))
    found.add_argument("--url", required=True, metavar="주소", help="https://blog.naver.com/… 모양의 발행한 글 주소")
    found = add("naver-profile", cmd_naver_profile, "네이버 블로그 A·B 의 프로필(표시명·주소·기본 태그 …)을 보거나 정합니다")
    found.add_argument("action", choices=("show", "set"))
    found.add_argument("blog", nargs="?", choices=("naver_a", "naver_b"), help="set 할 블로그")
    for flag, label in (("name", "블로그 표시명"), ("url", "블로그 주소(https://blog.naver.com/아이디)"), ("topic", "주제"), ("audience", "대상 독자"), ("tone", "말투"), ("image_spec", "대표 이미지 규격 안내"),
                        ("publish_cycle", "발행 주기 안내"), ("disclosure", "AI 활용 고지문")):
        found.add_argument("--" + flag.replace("_", "-"), dest=flag, metavar="값", help=label)
    found.add_argument("--tags", metavar="a,b,c", help="기본 태그(쉼표로 나눔)")
    found.add_argument("--forbidden", metavar="a,b,c", help="금지 표현(쉼표로 나눔)")
    found.add_argument("--category-map", action="append", metavar="원고분류=네이버카테고리", help="카테고리 매핑(여러 번 쓸 수 있음 — 쓰면 목록을 이것으로 바꿉니다)")
    found.add_argument("--min-chars", type=int, metavar="글자수")
    found.add_argument("--max-chars", type=int, metavar="글자수")
    add("backup", cmd_backup, "글 저장소의 점검한 백업 사본을 만듭니다(최근 10개 보관)")
    found = add("restore", cmd_restore, "백업으로 글 저장소를 되돌립니다(되돌리기 직전 상태는 따로 백업합니다 — --yes 필요)")
    found.add_argument("file", nargs="?", metavar="백업파일")
    found.add_argument("--latest", action="store_true", help="가장 최근 백업을 씁니다")
    found.add_argument("--yes", action="store_true", help="지금 글 저장소의 내용을 그 백업의 내용으로 정말 바꿉니다")
    found = add("delete", cmd_delete, "글을 지웁니다(되돌릴 수 없습니다 — --yes 필요)")
    found.add_argument("id", metavar="글번호")
    found.add_argument("--yes", action="store_true", help="정말 지웁니다")
    return parser


# ---- 실행 --------------------------------------------------------------------------------------------------------------------------
def _mask_deep(value):
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, dict):
        return {key: _mask_deep(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask_deep(item) for item in value]
    return value


def mask_block(text):
    """여러 줄 글을 통째로 가린 글. 줄 단위로 가리면 개인 키 블록(-----BEGIN … PRIVATE KEY----- 부터 END 까지)의 본문 줄과 '다음 줄에 이어지는 값' 이 그대로 나간다.
    글이 아주 길어 한 번에 가릴 수 없으면(`MAX_MASK_INPUT` 초과) 줄 경계에서 나눠 가리되 열린 개인 키 블록 안에서는 끊지 않는다(끝까지 가려진다)."""
    text = str(text)
    if len(text) <= MAX_MASK_INPUT:
        return mask(text)
    pieces, current, size, inside = [], [], 0, False
    for line in text.split("\n"):
        current.append(line)
        size += len(line) + 1
        if "PRIVATE KEY" in line:
            if "-----BEGIN" in line:
                inside = True
            if "-----END" in line:
                inside = False
        if size >= MAX_MASK_INPUT // 2 and not inside:
            pieces.append(mask("\n".join(current)))
            current, size = [], 0
    if current:
        pieces.append(mask("\n".join(current)))
    return "\n".join(pieces)


def _error_payload(error):
    shown = fmt.shown_error(error)
    return {"code": shown.code, "message": shown.message, "action": shown.action, "retry": shown.retry_text, "detail": " ".join(str(error.detail or "").split())[:700]}


def unexpected_error(problem):
    """예상하지 못한 예외 → UNEXPECTED_ERROR(예외 이름과 가린 한 줄만 — 스택 추적·키는 화면에 내지 않는다)."""
    return AppError("UNEXPECTED_ERROR", detail=f"{type(problem).__name__}: {mask(str(problem))[:200]}")


def _lenient(stream):
    """한국어 Windows 콘솔·파일 리다이렉트에서 표시할 수 없는 글자 하나 때문에 출력이 예외로 끝나지 않게 한다."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        with contextlib.suppress(OSError, ValueError):
            reconfigure(errors="replace")


def main(argv=None, *, out=None, err=None, ctx=None, env=None):
    """명령 하나를 실행하고 종료 코드(0·1·2)를 돌려준다. `ctx` 를 주면 그 Context 로(시험), 없으면 `--data-dir`·`--repo`·환경 변수로 만든다."""
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    _lenient(out)
    _lenient(err)

    def say(stream, text):
        print(mask_block(text), file=stream)

    parser = build_parser()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            args = parser.parse_args(argv)
    except SystemExit as stop:                                 # --help
        return int(stop.code or 0)
    except UsageError as problem:
        say(err, f"사용법 오류: {problem}")
        say(err, f"도움말: {PROG} --help")
        return 2
    as_json = getattr(args, "json", False)
    debug = getattr(args, "debug", False)
    command = args.command
    try:
        context = ctx if ctx is not None else make_context(data_dir=getattr(args, "data_dir", None), repo=getattr(args, "repo", None), env=env)
        if hasattr(context.backend, "progress"):                       # 공개 확인을 기다리는 동안(기본 최대 12분) 진행을 알린다 — 표준 오류로(--json 출력을 어지럽히지 않는다)
            context.backend.progress = lambda text: print(mask_block(text), file=err, flush=True)
        output = args.handler(context, args)
    except UsageError as problem:
        say(err, f"사용법 오류: {problem}")
        say(err, f"도움말: {PROG} {command} --help")
        return 2
    except AppError as error:
        _report_error(out, err, command, error, as_json, getattr(args, "verbose", False))
        return 1
    except KeyboardInterrupt:
        say(err, "중단했습니다. 이미 끝낸 단계는 그대로이고, 같은 명령을 다시 실행하면 이어서 합니다.")
        return 1
    except Exception as problem:
        if debug:
            raise
        _report_error(out, err, command, unexpected_error(problem), as_json, getattr(args, "verbose", False))
        return 1
    if as_json:
        print(json.dumps(_mask_deep({"ok": output.code == 0, "command": command, "data": output.data}), ensure_ascii=False, indent=2), file=out)
    else:
        say(out, "\n".join(output.lines))                    # 줄마다가 아니라 통째로 가린다 — 여러 줄에 걸친 비밀(개인 키 블록 …)이 줄 단위 가리기를 빠져나가지 않게
    return output.code


def _report_error(out, err, command, error, as_json, verbose):
    if as_json:
        print(json.dumps(_mask_deep({"ok": False, "command": command, "error": _error_payload(error)}), ensure_ascii=False, indent=2), file=out)
        return
    print(mask_block("\n".join(fmt.error_lines(error, verbose=verbose))), file=err)
