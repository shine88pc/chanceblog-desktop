"""`python -m chanceblog_desktop gui` — 화면을 연다. PySide6 가 없으면 **쉬운 한국어로 안내하고** 끝낸다(명령줄 기능은 PySide6 없이 그대로 동작한다).

`--data-dir 폴더` 는 명령줄과 같은 사용자 데이터 폴더를 가리키고(없으면 기본 위치), `--sample` 은 내 데이터 대신 **예시 데이터**로 화면을 보여 준다. 화면은 읽기만 한다(보관함을 만들거나 바꾸지 않는다).

**사용법 오류는 입력한 값을 되풀이하지 않는다** — 파이썬 `argparse` 의 기본 오류 문구(`ignored explicit argument '…'`·`unrecognized arguments: …`)는 사용자가 친 값을 그대로 보여 주므로,
값(키가 들어 있을 수도 있다)이 화면·기록에 남지 않게 `GuiParser.error` 가 값 없는 고정 문장만 낸다. 종료 코드는 명령줄의 사용법 오류와 같은 2 이다.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys

PROG = "python -m chanceblog_desktop gui"
USAGE_LINE = f"사용법: {PROG} [--data-dir 폴더] [--sample]"
USAGE_ERROR = "사용법 오류: gui 명령의 인자가 올바르지 않습니다(입력한 값은 보이지 않습니다)."
USAGE_HINT = f"도움말: {PROG} --help"
USAGE_EXIT_CODE = 2                                                                   # 명령줄(`service/cli.py`)의 사용법 오류와 같다
NEEDS_PYSIDE6 = (
    "화면(GUI)을 쓰려면 'PySide6' 가 필요한데 이 PC 에는 아직 없어요.\n"
    "아래 한 줄을 실행해 설치한 뒤 다시 열어 주세요(설치는 한 번만 하면 돼요).\n"
    "    python -m pip install PySide6\n"
    "화면 없이 쓰는 명령(글 만들기·목록·후보 등)은 그대로 쓸 수 있어요 — 도움말: python -m chanceblog_desktop --help"
)


def has_pyside6():
    return importlib.util.find_spec("PySide6") is not None


class KoreanHelpFormatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, "사용법: " if prefix is None else prefix)


class GuiParser(argparse.ArgumentParser):
    """사용법 오류에서 입력한 값을 되풀이하지 않는 파서 — 어떤 오류든(`--sample=값`·위치 인자·모르는 옵션·`-h값`·`--help=값`·값 빠짐) 값 없는 고정 문장 + 사용법 한 줄만 낸다."""

    def __init__(self, *args, **kwargs):
        kwargs["add_help"] = False                                                    # 영어 도움말 항목을 쓰지 않고 아래에서 한국어로 직접 더한다
        kwargs.setdefault("formatter_class", KoreanHelpFormatter)
        super().__init__(*args, **kwargs)
        self.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS, help="이 도움말을 보여 주고 끝냅니다")
        for attribute, title in (("_positionals", "위치 인자"), ("_optionals", "옵션")):          # 영어 제목('positional arguments'·'options'·'optional arguments')을 바꾼다
            group = getattr(self, attribute, None)
            if group is not None:
                group.title = title

    def error(self, message):                                                         # `message` 에는 사용자가 친 값이 들어 있다 — 쓰지 않는다
        print(USAGE_ERROR, USAGE_LINE, USAGE_HINT, sep="\n", file=sys.stderr)
        self.exit(USAGE_EXIT_CODE)


def build_parser():
    parser = GuiParser(prog=PROG, description="ChanceBlog Desktop 화면을 엽니다(읽기만 합니다).")
    parser.add_argument("--data-dir", default=None, metavar="폴더", help="사용자 데이터 폴더(없으면 기본 위치 — 명령줄과 같은 폴더를 씁니다)")
    parser.add_argument("--sample", action="store_true", help="내 데이터 대신 예시 데이터로 화면을 보여 줍니다")
    return parser


def main(argv=None, *, out=None):
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    from .core import version as app_version
    problem = app_version.release_problem(app_version.read_version(), app_version.is_release())      # Release 인데 버전을 못 읽으면 쉬운 안내로 끝낸다(개발 화면은 '개발 버전' 으로 계속) — 새 오류 코드 없음, UI-C1a D-173
    if problem:
        print(problem, file=out)
        return 1
    if not has_pyside6():
        print(NEEDS_PYSIDE6, file=out)
        return 1
    from .adapters import ServiceHomeProvider
    from .core.services import FakeHomeProvider
    from .qt.app import run
    provider = FakeHomeProvider(delay=0.3) if args.sample else ServiceHomeProvider(args.data_dir)
    return run(provider)
