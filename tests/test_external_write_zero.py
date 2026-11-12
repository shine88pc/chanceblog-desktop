"""Network Write 0 — 영구 시험(PCSEC1 H3 넷째 겹, 운영자 결정 2026-11-11).

모든 **명령줄 부명령**(파서에서 열거 — 새 부명령이 생기면 자동으로 포함된다)과 **화면이 서비스를 부르는 모든 어댑터 동작**(`ui/*_adapter.py` 의 서비스 제공자)을 앱이 실제로 쓰는 기본 부품
(`make_context` — 파일만 읽는 backend·무엇이든 거절하는 git 실행기)과 임시 데이터 폴더로 돌리면서 바깥으로 나가는 호출을 모두 막고(`tests/outgoing_support.Tripwire`: 소켓·HTTP·`urlopen`·하위 프로세스·
`os.system`·`os.spawn*`·`os.exec*`·`os.startfile`·`webbrowser`) **세어서 0** 을 단언한다. 허용 목록은 비어 있다 — 네이버 글쓰기 주소 열기는 화면(Qt)의 `qt_open_url` 한 길이고(주소 모양 검사 뒤 기본 브라우저가
연다 — 앱이 연결하지 않는다) 클립보드·자격 증명 관리자 호출(`ctypes` — 로컬)은 소켓·하위 프로세스가 아니다.
입력은 올바른 것과 틀린 것을 섞어 쓴다(틀린 입력의 오류 길도 바깥으로 나가지 않는다). 결과(종료 코드·오류)는 따지지 않고 **바깥 호출 0** 과 **예외로 끝나지 않음**만 본다.
"""
import argparse
import io
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import outgoing_support as og  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop.service import cli  # noqa: E402
from chanceblog_desktop.service.context import make_context  # noqa: E402
from chanceblog_desktop.ui.adapters import ServiceHomeProvider  # noqa: E402

REQUIRED_VALUES = {"--title": "시험 글", "--topic": "시험 주제", "--keyword": "시험 키워드", "--blog": "naver_a", "--name": "기본", "--url": "https://blog.naver.com/exampleaaa/1",
                   "--category": "경제·일", "--lang": "ko", "--image-url": "https://images.example.invalid/a.jpg", "--platform": "pages"}


def leaf_commands(parser):
    """(경로 튜플, 그 말단 부명령의 파서) — 하위 명령이 더 없는 것만."""
    found = []

    def walk(current, path):
        subs = [action for action in current._actions if isinstance(action, argparse._SubParsersAction)]
        if not subs:
            found.append((path, current))
            return
        for action in subs:
            for name, child in action.choices.items():
                walk(child, path + (name,))

    walk(parser, ())
    return found


def positional_value(action, tmp):
    if action.choices:
        return str(list(action.choices)[0])
    meta = (action.metavar or action.dest or "").lower()
    if "파일" in meta or "폴더" in meta or "file" in meta or "folder" in meta:
        return str(tmp / "없는 파일.txt")
    if "번호" in meta or "순번" in meta or "항목" in meta or "id" in meta or "ref" in meta:
        return "1"
    return "x"


def argv_for(path, parser, tmp, *, with_yes=False):
    argv = list(path)
    for action in parser._actions:
        if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
            continue
        if not action.option_strings:                                                             # 위치 인자
            if action.nargs in ("?", "*"):
                continue
            argv.append(positional_value(action, tmp))
            continue
        if action.required:
            flag = action.option_strings[-1]
            if action.choices:
                argv += [flag, str(list(action.choices)[0])]
            elif flag in REQUIRED_VALUES:
                argv += [flag, REQUIRED_VALUES[flag]]
            else:
                argv += [flag, "x"]
    if with_yes and any("--yes" in action.option_strings for action in parser._actions):
        argv.append("--yes")
    return argv


class EveryCommandTest(unittest.TestCase):
    def test_the_sweep_really_covers_the_parser(self):
        leaves = leaf_commands(cli.build_parser())
        names = {" ".join(path) for path, _parser in leaves}
        self.assertGreaterEqual(len(leaves), 50, sorted(names))
        for must in ("doctor", "connect", "publish-pages", "check-deploy", "backup", "restore", "keys add", "keys test", "candidates add", "topics backup", "draft body", "naver-package"):
            self.assertIn(must, names)

    def test_every_subcommand_with_and_without_yes_makes_no_outgoing_call(self):
        parser = cli.build_parser()
        ran, problems = 0, []
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            ctx = make_context(data_dir=str(tmp / "data"), env={}, expected_origin=ss.LOCAL_ORIGIN, clock=ss.Clock())                # 앱이 실제로 쓰는 기본 부품
            variants = []
            for path, leaf in leaf_commands(parser):
                variants.append(argv_for(path, leaf, tmp))
                yes = argv_for(path, leaf, tmp, with_yes=True)
                if yes != variants[-1]:
                    variants.append(yes)
            variants += [["doctor", "--online"], ["publish-pages", "ffffffff", "--cancel", "--yes"], ["publish-pages", "ffffffff", "--yes", "--no-wait"]]
            with og.Tripwire() as wire:
                for argv in variants:
                    out, err = io.StringIO(), io.StringIO()
                    try:
                        code = cli.main(argv, out=out, err=err, ctx=ctx, env={}, stdin=io.StringIO(""))
                    except SystemExit as stop:                                                           # 사용법 오류가 아닌데 SystemExit 이면 안 된다
                        problems.append((" ".join(argv[:2]), "SystemExit", stop.code))
                        continue
                    if code not in (0, 1, 2):
                        problems.append((" ".join(argv[:2]), "exit", code))
                    ran += 1
            self.assertEqual(wire.calls, [], f"바깥으로 나가는 호출이 일어났다(종류 {wire.kinds()})")
        self.assertEqual(problems, [])
        self.assertGreaterEqual(ran, 60, "열거한 부명령(말단) 56개 이상이 한두 번씩 돌았어야 한다")

    def test_the_commands_that_could_publish_say_why_they_stopped(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = make_context(data_dir=str(Path(tmp) / "data"), env={}, clock=ss.Clock())
            for argv in (["publish-pages", "ffffffff"], ["publish-pages", "ffffffff", "--yes"], ["check-deploy", "ffffffff"], ["doctor", "--online"]):
                out, err = io.StringIO(), io.StringIO()
                with og.Tripwire() as wire:
                    code = cli.main(argv, out=out, err=err, ctx=ctx, env={})
                self.assertEqual((code, wire.calls), (1, []))
                self.assertIn("코드: EXTERNAL_WRITE_DISABLED", err.getvalue())


class EveryScreenActionTest(unittest.TestCase):
    """화면이 서비스로 가는 유일한 문(`ui/*_adapter.py` 의 제공자)의 모든 동작 — 올바른 입력과 틀린 입력으로 한 번씩."""

    def test_every_provider_method_makes_no_outgoing_call(self):
        progress, cancelled = (lambda *args, **kwargs: None), (lambda: False)
        problems, called = [], []
        with tempfile.TemporaryDirectory() as tmp:
            data = str(Path(tmp) / "data")
            home = ServiceHomeProvider(data)                                                           # 기본 부품(make_context)으로 만든 홈 공급자와 짝 공급자들
            blogs, candidates, drafts, seeds, keys = home.blogs_provider(), home.candidates_provider(), home.drafts_provider(), home.seeds_provider(), home.connections_provider()
            calls = [
                ("home.load_home", lambda: home.load_home(progress, cancelled)), ("home.load_connections", lambda: home.load_connections(progress, cancelled)),
                ("blogs.load_blogs", lambda: blogs.load_blogs(progress, cancelled)), ("blogs.save_blog", lambda: blogs.save_blog("naver_a", {"display_name": "시험"}, "0", progress, cancelled)),
                ("blogs.clone_blog", lambda: blogs.clone_blog("naver_a", "naver_b", "0", progress, cancelled)), ("blogs.clear_blog", lambda: blogs.clear_blog("naver_b", "0", progress, cancelled)),
                ("candidates.load_candidates", lambda: candidates.load_candidates(progress, cancelled)), ("candidates.preview_make", lambda: candidates.preview_make(progress, cancelled)),
                ("candidates.make_candidates", lambda: candidates.make_candidates(None, progress, cancelled)),
                ("drafts.make_draft", lambda: drafts.make_draft(None, progress, cancelled)),
                ("seeds.load_seeds", lambda: seeds.load_seeds(progress, cancelled)), ("seeds.set_state", lambda: seeds.set_state("s1", "paused", "0", progress, cancelled)),
                ("seeds.set_states", lambda: seeds.set_states(["s1"], "paused", "0", progress, cancelled)), ("seeds.edit_seed", lambda: seeds.edit_seed("s1", {"keyword": "시험"}, "0", progress, cancelled)),
                ("seeds.create_seed", lambda: seeds.create_seed({"keyword": "시험"}, "0", progress, cancelled)),
                ("seeds.preview_import", lambda: seeds.preview_import(str(Path(tmp) / "없는 파일.json"), progress, cancelled)),
                ("seeds.apply_import", lambda: seeds.apply_import(None, progress, cancelled)),
                ("keys.add_key", lambda: keys.add_key("ai_assist", "gemini", "기본", None, False, progress, cancelled)),
                ("keys.remove_key", lambda: keys.remove_key("ai_assist", "00000000", progress, cancelled)), ("keys.set_key_state", lambda: keys.set_key_state("ai_assist", "00000000", "off", progress, cancelled)),
                ("keys.rename_key", lambda: keys.rename_key("ai_assist", "00000000", "새 이름", progress, cancelled)), ("keys.move_key", lambda: keys.move_key("ai_assist", "00000000", "up", progress, cancelled)),
                ("keys.test_key", lambda: keys.test_key("ai_assist", "00000000", progress, cancelled)),
            ]
            with og.Tripwire() as wire:
                for label, call in calls:
                    try:
                        call()
                    except Exception as error:                                                          # 틀린 입력의 오류(서비스 오류·형식 오류)는 괜찮다 — 바깥 호출만 본다
                        if isinstance(error, og.OutgoingBlocked):
                            problems.append((label, "바깥 호출이 막혔다"))
                    called.append(label)
            self.assertEqual(wire.calls, [], f"바깥으로 나가는 호출이 일어났다(종류 {wire.kinds()})")
        self.assertEqual(problems, [])
        self.assertEqual(len(called), len(calls))

    def test_the_sweep_names_every_public_provider_method(self):
        """어댑터에 새 동작이 생기면 이 표에도 넣어야 한다 — 공개 메서드 이름을 소스에서 읽어 표와 맞춘다."""
        import ast
        ui = ss.ROOT / "src" / "chanceblog_desktop" / "ui"
        found = set()
        for name, prefix in (("adapters.py", "home"), ("blogs_adapter.py", "blogs"), ("candidates_adapter.py", "candidates"), ("drafts_adapter.py", "drafts"), ("seeds_adapter.py", "seeds"), ("keys_adapter.py", "keys")):
            tree = ast.parse((ui / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name.startswith("Service") and node.name != "ServiceEngine":
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and not item.name.startswith("_") and item.args.args[-2:] and [arg.arg for arg in item.args.args[-2:]] == ["progress", "cancelled"]:
                            found.add(f"{prefix}.{item.name}")
        expected = {"home.load_home", "home.load_connections", "blogs.load_blogs", "blogs.save_blog", "blogs.clone_blog", "blogs.clear_blog", "candidates.load_candidates", "candidates.preview_make",
                    "candidates.make_candidates", "drafts.make_draft", "seeds.load_seeds", "seeds.set_state", "seeds.set_states", "seeds.edit_seed", "seeds.create_seed", "seeds.preview_import",
                    "seeds.apply_import", "keys.add_key", "keys.remove_key", "keys.set_key_state", "keys.rename_key", "keys.move_key", "keys.test_key"}
        self.assertEqual(found, expected, "화면 어댑터의 공개 동작과 이 시험의 표가 달라졌다 — 새 동작을 표에 더한다")


if __name__ == "__main__":
    unittest.main()
