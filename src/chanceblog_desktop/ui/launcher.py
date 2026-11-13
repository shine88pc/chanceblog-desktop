"""`python -m chanceblog_desktop gui` — 화면을 연다. PySide6 가 없으면 **쉬운 한국어로 안내하고** 끝낸다(명령줄 기능은 PySide6 없이 그대로 동작한다).

`--data-dir 폴더` 는 명령줄과 같은 사용자 데이터 폴더를 가리키고(없으면 기본 위치), `--sample` 은 내 데이터 대신 **예시 데이터**로 화면을 보여 준다. 홈 화면은 읽기만 한다(보관함을 만들거나 바꾸지 않는다) — 설정 화면도 열고 다시 읽는 것은 읽기뿐이다. 파일에 쓰는 일은 화면마다 사용자가 단추를 눌렀을 때뿐이다: **블로그 관리·Seed 관리 화면**은 저장·복제·삭제(블로그 관리), 승인·바꾸기·저장·등록·불러오기(Seed 관리)를 눌렀을 때 사용자 데이터 폴더의 블로그 프로필 파일(`topic_engine/channel_profiles.json`)·Seed 파일(`topic_engine/seeds.json`)에 쓰고(`--sample` 은 아무 파일에도 쓰지 않는다), **설정 화면**은 키를 등록·삭제·고치는 단추를 눌렀을 때만 키 원문은 Windows 자격 증명 관리자에, 별칭·순서·사용 상태 같은 비밀이 아닌 값은 사용자 데이터 폴더의 `connections.json` 에 쓴다. **주제 후보 화면**은 열고 거르고 찾고 고르는 것까지 읽기만 하고(보관함이 없으면 만들지도 않는다), `후보 만들기` 를 눌러 확인창에서 `만들기` 를 골랐을 때만 후보 보관함(`topic_engine/topic_engine.db`)에 후보를 더한다.

**같은 데이터 폴더로 이미 열려 있으면 새 창을 만들지 않는다**(SINGLEWIN, `ui/single_instance.py`) — 윈도에서 같은 로그온·같은 데이터 폴더로 한 번 더 열면 열려 있는 창을 앞으로 가져오고 조용히 끝난다(종료 코드 0). 다른 데이터 폴더(`--data-dir`)·`--sample` 은 따로 열 수 있다.

**사용법 오류는 입력한 값을 되풀이하지 않는다** — 파이썬 `argparse` 의 기본 오류 문구(`ignored explicit argument '…'`·`unrecognized arguments: …`)는 사용자가 친 값을 그대로 보여 주므로,
값(키가 들어 있을 수도 있다)이 화면·기록에 남지 않게 `GuiParser.error` 가 값 없는 고정 문장만 낸다. 종료 코드는 명령줄의 사용법 오류와 같은 2 이다.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys

from . import single_instance

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
    parser = GuiParser(prog=PROG, description="ChanceBlog Desktop 화면을 엽니다(홈은 읽기만 합니다 — 설정 화면도 열고 다시 읽는 것은 읽기뿐입니다. 블로그 관리 화면은 저장·복제·삭제를, Seed 관리 화면은 승인·바꾸기·저장·등록·불러오기를, 주제 후보 화면은 후보 만들기 확인창의 만들기를, 설정 화면은 키를 등록·삭제·고치는 단추와 백업·복원 카드의 지금 백업·복원하기(확인창 뒤)를 눌렀을 때만 해당 파일·자격 증명 관리자에 씁니다).")
    parser.add_argument("--data-dir", default=None, metavar="폴더", help="사용자 데이터 폴더(없으면 기본 위치 — 명령줄과 같은 폴더를 씁니다)")
    parser.add_argument("--sample", action="store_true", help="내 데이터 대신 예시 데이터로 화면을 보여 줍니다")
    return parser


def main(argv=None, *, out=None):
    from ..security import boundary
    boundary.install()                                                                # 맨 앞 — 묶음 실행 파일의 진입점(`gui_entry`)은 `__main__` 을 거치지 않고 여기로 바로 들어온다. 공통 경계(표준 출력·오류·로그·예외 훅)가 두 진입점 모두에 깔리게 한다(멱등 — `__main__` 이 먼저 깔았으면 그대로). 사용법 오류·버전 오류의 글도 이미 가려져 나간다
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
    if not single_instance.claim(args.data_dir, sample=args.sample):                  # 같은 데이터 폴더로 이미 열려 있으면 그 창을 앞으로 가져오고 새 창 없이 조용히 끝난다(종료 코드 0) — 묶음 실행 파일(`gui_entry`)도 이 함수를 지나므로 두 시작 길이 같은 장치다. `--sample` 은 따로 열 수 있고 `--selftest`·명령줄은 여기를 지나지 않는다. Qt 를 불러오기 전이라 둘째 실행은 빨리 끝난다
        return 0
    boundary.install_gui()                                                            # PySide6 가 있다고 확인된 뒤 — Qt 가 직접 찍는 메시지도 가려서 표준 오류로(멱등 — `__main__` 이 먼저 걸었으면 그대로). 화면을 만들기 전이다
    from .adapters import ServiceHomeProvider
    from .core.services import FakeHomeProvider
    from .qt.app import run
    provider = FakeHomeProvider(delay=0.3, backups=True) if args.sample else ServiceHomeProvider(args.data_dir)          # 예시 화면은 백업·복원 카드도 메모리 예시로 짝을 둔다(D-391 — 아무것도 저장하지 않는다)
    return run(provider)
