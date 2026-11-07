"""명령줄 `topics`(`service/cli.py`·`service/topic_format.py`) 시험 — 기존 명령의 출력은 한 글자도 안 바뀌었다는 특성 시험, 새 하위 명령의 사용법 오류·종료 코드·`--yes`·`--json`·쉬운 말 출력(P3, D-64). 네트워크·실제 시계 없이 돈다.

지키는 것:
  1) **기존 명령 45개의 `--help` 글**과 몇몇 기존 출력(`keys purposes`·`candidates list`·`list`·`naver-profile show`)은 P3 전(기준 커밋 `85996f6`)과 해시가 같다 — 바뀐 곳은 맨 위 도움말의 새 `topics` 줄뿐이다.
  2) 새 하위 명령은 읽기 전용이 기본이고 `init`·`generate`·`restore` 는 `--yes`(True 하나)가 있을 때만 저장·복원한다. 종료 코드는 0 정상·1 처리된 오류·2 사용법 오류다.
  3) 사용법 오류와 없는 번호 오류에서 친 값(키 모양 포함)이 화면·`--json` 에 되풀이되지 않고, 줄임 옵션(`--y`)은 받지 않는다.
  4) 화면 글에는 파이썬 목록 꼴·내부 이름이 없다 — 오류의 개발자용 세부(`AppError.detail`)는 `--verbose` 가 아니면 나오지 않는다.
"""
import argparse
import errno
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import topics_support as ts  # noqa: E402
from test_service_topics import World  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import cli  # noqa: E402
from chanceblog_desktop.service import format as fmt  # noqa: E402
from chanceblog_desktop.service import topic_format as tfmt  # noqa: E402
from chanceblog_desktop.topicdb import backup as bk  # noqa: E402
from chanceblog_desktop.topicdb.store import TopicStore, open_for_write  # noqa: E402
from chanceblog_desktop.topics import layout, notice  # noqa: E402

KEY_LIKE = "AI" + "za" + "E" * 35
TODAY = "2026-11-10"

# P3 전(기준 커밋 85996f6)의 기존 명령 `--help` 글 해시(COLUMNS=100) — 기존 명령의 도움말은 바뀌지 않았다. 의식적으로 고칠 때는 이 값과 이유를 함께 고친다.
HELP = {
    "approve": "6303abb9db1288852eca7eca9e5f5a776d2239d2e20736c621b66f06f0b06561",
    "backup": "aedf15f075941513b8ff1c4b05fc44a4219dbe9c312a20f06dcc237e47872cfc",
    "candidates": "c258e73fc0347d0df5c3e15e1f0406b9dc3cde265d72e5b8e57d46c1cd5483d6",
    "candidates add": "dbc919dfac7cfa2b5abedbcbeac504baecc09cea2e5c1c65250eb44c31e7ef27",
    "candidates delete": "d83a092f402d556340444339e88b793a592107161c3bb44f12ca65894519feb0",
    "candidates hold": "00c980ccb443f2ecb50e6254302ad5b6c772128d51c9d3418bbb7f57d7d32088",
    "candidates import-csv": "8cffd72c915bafdf2ad90b371a0d3db4aedc87da5ad885d7de6a88124d63d103",
    "candidates link": "7291401a0b05d5d4974ccd2ecfb2da82d0119ff4734ceb7e732ec75bffb6dc4f",
    "candidates list": "aff6b340a69e316e39c484d7b7e449370fc4fae5994801670a860f55ddc9aaf7",
    "candidates reject": "bfd9fabca56311e4781ebbda78c0911fe1e3b5f0bf2110182ee8aa709639e947",
    "candidates restore": "9867dacac39f5505dedf8d903467321cdbe2089939217198658c5ee81ddb34b9",
    "candidates review": "36345abae757e5832295c3cf34a012d39215354a75febb1bf60b54c2c364236b",
    "candidates select": "54dc0acac615c9b01149a1b59d9374663fccba0b82ce3cd143c8a722ebf78eeb",
    "candidates show": "db083abdc0d81dbff9f8b39073c55453a2d299ab9780ec5dfe4bafc03cd7d695",
    "candidates suggest": "96746b78999882ff7970fd88dfa99f4c02b1d390d29cf88b4907d1136918c2ce",
    "candidates unlink": "5aebe7b610bcf92511a8a3bfca2c6c85a17e4bfdb2822c1a1c141b6acf1cb4ff",
    "check-deploy": "29c203e2219b5eced52ee3959eeb0d30cb2d625de724edd96d8594e10c744c36",
    "connect": "6afd1202688b63ee1938100cb07601de4ecfa79154131b3d8bbf2f434cae64b2",
    "delete": "1ba24dd59c52fbad72bba624289901745211a92d95560598ae3ab8aabeeddf11",
    "doctor": "d3de6c56f5a62bc2285b9c6a25664b2d1074555bae6d6a329f697d4f3b0a3078",
    # 의도적 갱신(DB — 규칙 기반 초안 본문): `draft` 그룹 도움말에 하위 명령 `body` 가 더해져(설명·예시 문구 포함) 글이 바뀌었다 — 이전 값은 c9da1654…(P3 전 기준 커밋). `draft plan` 은 그대로다(아래 값).
    "draft": "1f526c22d37f71f647153522010f49de715ae1bd9bfb40066b3bff11a3340d5f",
    "draft plan": "dd51871e68e3f8eab80a50fc60d07887ff919ba580d612128796d587da5ac796",
    "edit": "9d96ffdd7603debafee49b72d40b6d198ae7d97ca5f11680748aabe8ff84fb20",
    "import-html": "0fa510092c0ac4a8954a02717263ebfe8537fa2905321a439458282ea7765f68",
    "keys": "6f91eec23e5584d442049675096e5db96c9c64970e31ee727cbf9669c9c3f3ff",
    "keys add": "d1987295fa6129600743b17bb544575ed2854e76f3036ee07334c54810457c79",
    "keys list": "82296217e44e8d9e4689c877c5ac0bb73f820582b6ed7a5a44837dc27a6e61e8",
    "keys order": "0a33fca0ffe9777a26635e88664a91a4a8ac4d1cb597158f14325fe691bd2bea",
    "keys policy": "d564871db1ce75795b5b52fadce8b9cd4f3087d072903461209c87f5fe592ea0",
    "keys purposes": "6c0f730f886adb6f97fd6e0028cc3e6f232499039bbaec95fa5589ebfb3254ce",
    "keys remove": "f8377d6d6c3df7c2a47e6568d1857ab0733151ee6c476651781d441378483ebd",
    "keys state": "fa26505aa28338d1ce6432bd641cddd460f2b902b4579721c2c8d7949f169f27",
    "keys test": "3f7da0c76a403f675a6c35120ed063b8b934bc8c3f79cab2f40accd3fd8a77ff",
    "keys usage": "bb7be251778f242b496c197ca1b50372a725a850bbdee40c0c59f66e67c4bffc",
    "list": "72a1ef087c7c5267bb20e75f4a3039dbb45b0737e63d1d9048441dfc1d5b8b54",
    "naver-done": "7a15d442ca059b2e5b79dcca553e850b314e12186dcfdd53751cd5a83a82240f",
    "naver-package": "49e6ebf80164960b8795306cd4f72d20f9f46867bd7515a3fd2406bdc81b5841",
    "naver-profile": "65c6b90d230268d3cdf57f64b0cd2f73edb46adfadcee86d46da5179ff57f025",
    "new": "ef6176324afe5f7149563af5e6f7451a08eddf4176b8b4a0ff1adf34cad70638",
    "preview": "9e51f92ff34047df48457ddb1f20390f364229018d64630ffbf7fb5833476226",
    "publish-pages": "f821ea0b2e8b986dd8d374f578c9af1448376f5e2569c456e5cfa6346cf21d3b",
    "restore": "dabfd60addbf80ce3bdec933f376919abeea34f43c5f4a60a659b80575709279",
    "review": "487ccedfd2bc5cc6e303d2a99e3d636b831a08596429339ecba4f4ce09bf0ad1",
    "revoke": "024384417b24413a0d492a8ce4dd9828d2c92ec182c63d191cb158eb8ba4e532",
    "show": "b469ca871851518a449f426d31d1d0fc6b5f8234d06ce12015013b939f570ed0",
}
# P3 전의 기존 명령 출력(출력 글 해시 — 종료 코드와 함께). 번호·경로가 없는 것만 골랐다.
OUTPUTS = (
    (["keys", "purposes"], 0, "1f6d8fa62e6c462a4422d5377a0df2cc96e754a482c7ebc5e9812d0fa070221e"),
    (["keys", "purposes", "--json"], 0, "8b3bd066757e772588f7a075b4bf11d05e994d59e55c7dfe508bee40edf90b61"),
    (["keys", "list"], 0, "72d594c73fe59992b0e8bb7ea4af82f305ecd10032d02321481595ca62b0d168"),
    (["candidates", "list"], 0, "c64d2ea8fed0270ad2aad32467fa9bcfb614d55b6f904fbb67019f7d2f95071d"),
    (["candidates", "list", "--json"], 0, "1997486554adcbe7cfaf78337a3d7e9dd811522b1ddcd2408c34415301277abe"),
    (["list"], 0, "0a8ffc292ea20426858c6a447ba5eb1bb0e8de5a3bde5c3b7dfd530076f690aa"),
    (["naver-profile", "show"], 0, "722c0083bd4e5ec729c18234171c5b6428930d39befed332f4a1f1a8761d1f06"),
)


STABLE_ARGV0 = "chanceblog-desktop"


def help_hashes():
    found = {}

    def walk(parser, path):
        found[" ".join(path) or "(top)"] = hashlib.sha256(parser.format_help().encode("utf-8")).hexdigest()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, sub in action.choices.items():
                    walk(sub, [*path, name])

    with mock.patch.object(sys, "argv", [STABLE_ARGV0]), mock.patch.dict(os.environ, {"COLUMNS": "100"}):          # 시험을 어떻게 시작했든(`python.exe -m unittest`·`python -m unittest`·pytest) 같은 글이 나오게 시작 이름과 줄 너비를 고정한다
        walk(cli.build_parser(), [])
    return found


class ExistingOutputUnchangedTest(unittest.TestCase):
    def test_the_help_of_every_existing_command_is_the_same_as_before_p3(self):
        found = help_hashes()
        for name, expected in HELP.items():
            with self.subTest(command=name):
                self.assertEqual(found.get(name), expected, "기존 명령의 도움말이 바뀌었다 — P3 는 기존 명령을 바꾸지 않는다")
        # 의도적 갱신(DB): `draft body`(규칙 기반 초안 본문)는 P3 뒤에 더해진 새 하위 명령이라 '기존 명령' 목록에서 뺀다(그 도움말은 tests/test_service_draft_body.py 가 시험한다).
        self.assertEqual({name for name in found if not name.startswith("topics") and name not in ("(top)", "draft body")}, set(HELP), "기존 명령이 더해지거나 빠졌다")

    def test_the_help_does_not_depend_on_how_the_tests_were_started(self):
        """수정 4차: Linux CI 가 실패한 원인으로 '도움말의 `usage:` 줄이 `sys.argv[0]`(윈도 `python.exe -m unittest`·리눅스 `python -m unittest`)에서 온다' 는 가설이 있었다 — 파서의 `prog` 가 상수(`PROG`)라서 그렇지 않다는 것을 못박는다."""
        before = help_hashes()
        for started_as in ("python.exe -m unittest", "python -m unittest", "/usr/bin/python3 -m pytest", "__main__.py"):
            with self.subTest(started_as=started_as):
                with mock.patch.object(sys, "argv", [started_as]), mock.patch.dict(os.environ, {"COLUMNS": "100"}):
                    parser = cli.build_parser()
                    self.assertEqual(parser.prog, cli.PROG)
                    self.assertEqual(hashlib.sha256(parser.format_help().encode("utf-8")).hexdigest(), before["(top)"])

    def test_the_top_level_help_only_gained_the_topics_line(self):
        with mock.patch.dict(os.environ, {"COLUMNS": "100"}):
            text = cli.build_parser().format_help()
        for name in HELP:
            if " " not in name:
                self.assertIn(name, text)
        self.assertIn("topics", text)

    def test_some_existing_outputs_are_byte_for_byte_the_same_as_before_p3(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ss.make_ctx(tmp)
            ss.naver_profiles(ctx)
            for argv, code, expected in OUTPUTS:
                with self.subTest(argv=" ".join(argv)):
                    got_code, out, _err = ss.run_cli(ctx, *argv)
                    self.assertEqual((got_code, hashlib.sha256(out.encode("utf-8")).hexdigest()), (code, expected))


class TopicsCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.ctx = self.world.ctx

    def run_cli(self, *argv):
        return ss.run_cli(self.ctx, "topics", *argv)

    def clean(self, text, where):
        root = str(self.ctx.workspace.root)
        for line in text.splitlines():
            if root in line or str(self.tmp.name) in line or line.startswith("  코드: "):
                continue                                              # 이 PC 의 실제 경로가 든 줄(백업 위치 안내)은 경로 때문에 밑줄이 있고, 오류 코드 줄(`코드: …`)은 기존 모든 명령이 똑같이 보이는 지원용 번호다
            self.assertEqual(notice.leaks(line), (), f"{where}: {line}")

    def test_status_init_check_walk_through_the_first_use_with_the_right_exit_codes(self):
        shutil_world = World(tempfile.mkdtemp(), with_world=False)
        code, out, err = ss.run_cli(shutil_world.ctx, "topics", "status")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("아직 없음", out)
        code, out, _err = ss.run_cli(shutil_world.ctx, "topics", "init")
        self.assertEqual(code, 0)
        self.assertIn("만들지 않았습니다(미리 보기", out)
        self.assertFalse(shutil_world.paths.folder.exists())
        code, out, _err = ss.run_cli(shutil_world.ctx, "topics", "init", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(sorted(os.listdir(shutil_world.paths.folder)), sorted(layout.USER_DATA_FILES))
        self.assertIn("새로 만들었습니다", out)
        code, out, _err = ss.run_cli(shutil_world.ctx, "topics", "check", "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("검사를 통과했습니다", out)
        shutil_world.paths.seeds.write_text("{broken", encoding="utf-8")
        code, out, err = ss.run_cli(shutil_world.ctx, "topics", "check", "--today", TODAY)
        self.assertEqual(code, 1, "읽을 수 없는 파일이 있으면 종료 코드 1")
        self.assertIn("읽을 수 없습니다", out)
        self.assertEqual(shutil_world.paths.seeds.read_bytes(), b"{broken", "검사는 고치거나 덮어쓰지 않는다")

    def test_plan_is_a_preview_and_generate_needs_yes_and_both_say_so(self):
        code, out, err = self.run_cli("plan", "--today", TODAY, "--target", "6")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("아무것도 저장하지 않았습니다", out)
        self.assertFalse(self.world.paths.database.exists())
        code, out, _err = self.run_cli("generate", "--today", TODAY, "--target", "6")
        self.assertEqual(code, 0)
        self.assertIn("아무것도 저장하지 않았습니다", out)
        self.assertFalse(self.world.paths.database.exists(), "--yes 가 없으면 저장하지 않는다")
        code, out, _err = self.run_cli("generate", "--today", TODAY, "--target", "6", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("후보를 저장했습니다", out)
        self.assertTrue(self.world.paths.database.exists())
        self.world.ledger_post()
        code, out, _err = self.run_cli("generate", "--today", TODAY, "--target", "3", "--channel", "naver_a", "--yes")
        code, again, _err = self.run_cli("generate", "--today", TODAY, "--target", "3", "--channel", "naver_a", "--yes")
        self.assertIn("남은 자리가 없어 새 후보를 만들지 않았습니다", again, "목표만큼 찼으면 다시 해도 늘지 않는다")

    def test_the_reading_commands_show_what_was_saved(self):
        self.run_cli("generate", "--today", TODAY, "--target", "6", "--yes")
        code, out, _err = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("순번", out)
        code, out, _err = self.run_cli("list", "--channel", "naver_b", "--band", "보류함(점수 구간)")
        self.assertEqual(code, 0)
        code, out, _err = self.run_cli("top")
        self.assertEqual(code, 0)
        self.assertIn("우수 후보", out)
        self.assertIn("이번 분석에서 기준을 충족한 주제는", out)
        code, out, _err = self.run_cli("show", "1")
        self.assertEqual(code, 0)
        self.assertIn("선정 이유", out)
        code, out, _err = self.run_cli("review", "--today", "2027-06-01")
        self.assertEqual(code, 0)
        self.assertIn("지우거나 바꾸지 않았습니다", out)
        code, out, _err = self.run_cli("list", "--channel", "blogger_a")
        self.assertEqual(code, 0, "전략 문서의 채널 별칭도 받는다")

    def test_a_candidate_without_a_score_is_shown_as_unknown_never_as_zero(self):
        unrated = ts.make(candidate_id="tc-naver_a-seed-aaaa000000009", channel="naver_a", topic="예시 점수 없는 주제 글", created_at="2026-11-10T00:00:00Z")      # 점수 묶음이 비어 있다 — 구간도 '없음'
        with open_for_write(self.world.paths.database) as store:
            store.add_candidates(lambda existing: [unrated], now="2026-11-10T01:00:00Z")
        code, out, _err = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("(점수 없음)", out)
        self.assertNotIn("0점", out, "모르는 값은 0점이 아니다")
        code, out, _err = self.run_cli("show", "1")
        self.assertEqual(code, 0)
        self.assertIn("점수: 아직 없음(모르는 값은 0점이 아닙니다)", out)

    def test_backup_and_restore_need_yes_and_the_plain_restore_without_a_name_is_a_usage_error(self):
        self.run_cli("generate", "--today", TODAY, "--target", "6", "--yes")
        code, out, _err = self.run_cli("backup")
        self.assertEqual(code, 0)
        self.assertIn("주제 엔진 백업을 만들었습니다", out)
        before = {path.name: path.read_bytes() for path in self.world.paths.folder.iterdir() if path.is_file()}
        code, out, err = self.run_cli("restore", "--latest")
        self.assertEqual(code, 1)
        self.assertIn("CONFIRMATION_REQUIRED", err)
        self.assertEqual({path.name: path.read_bytes() for path in self.world.paths.folder.iterdir() if path.is_file()}, before)
        self.assertEqual(self.run_cli("restore")[0], 2)
        both = self.run_cli("restore", "topic-20261102-013012", "--latest")
        self.assertEqual(both[0], 2)
        code, out, _err = self.run_cli("restore", "--latest", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("주제 엔진 백업으로 되돌렸습니다", out)
        self.assertIn("되돌리기 직전의 상태는 따로 백업해 두었습니다", out, "지금 데이터가 있었으면 되돌리기 직전 상태를 따로 백업했다고 알린다")

    def test_restore_tells_that_a_broken_store_was_moved_aside_not_deleted(self):
        self.run_cli("generate", "--today", TODAY, "--target", "6", "--yes")
        self.run_cli("backup")
        self.world.paths.database.write_bytes(os.urandom(4096))
        code, out, _err = self.run_cli("restore", "--latest", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("깨져 있던 지금 후보 보관함은 지우지 않고 옆으로 옮겨 두었습니다", out)
        self.assertTrue([name for name in os.listdir(self.world.paths.folder) if ".bad-" in name], "깨진 파일은 지워지지 않고 옆에 남아 있다")

    def test_json_output_has_the_common_shape_and_carries_no_developer_detail(self):
        code, out, err = self.run_cli("plan", "--today", TODAY, "--target", "4", "--json")
        data = json.loads(out)
        self.assertEqual((code, data["ok"], data["command"]), (0, True, "topics plan"))
        self.assertEqual(sorted(data["data"]), ["channels", "history", "notes", "saved", "store", "today", "total_new"])
        self.assertEqual([channel["channel"] for channel in data["data"]["channels"]], ["github_pages", "blogger_en", "blogger_ko", "naver_a", "naver_b"])
        self.world.paths.seeds.write_text('{"schema": 1, "seeds": [{"seed_id": "x", "unknown_field": 1}]}', encoding="utf-8")
        code, out, err = self.run_cli("plan", "--json")
        error = json.loads(out)
        self.assertEqual((code, error["ok"], error["error"]["code"]), (1, False, "CONTENT_INVALID"))
        self.assertEqual(error["error"]["detail"], "", "파이썬 목록 꼴이 든 개발자용 세부는 화면·--json 에 내지 않는다")
        self.assertNotIn("['", out)
        code, out, err = self.run_cli("plan", "--verbose")
        self.assertEqual(code, 1)
        self.assertIn("기록용 한 줄", err, "--verbose 는 개발자용 기록을 보인다")

    def test_a_broken_seed_file_stops_the_plan_with_the_reason_and_without_python_list_forms(self):
        self.world.paths.seeds.write_text('{"schema": 1, "seeds": [{"seed_id": "x", "unknown_field": 1}]}', encoding="utf-8")
        code, out, err = self.run_cli("plan")
        self.assertEqual(code, 1)
        self.assertIn("CONTENT_INVALID", err)
        for needle in ("['", "']", "모르는 칸 [", "dev ", "detail"):
            self.assertNotIn(needle, err + out)

    def test_every_line_of_every_command_is_plain_korean_without_developer_marks(self):
        self.world.ledger_post()
        steps = (("status",), ("init", "--yes"), ("check", "--today", TODAY), ("plan", "--today", TODAY, "--target", "6"), ("plan", "--today", TODAY, "--target", "6", "--verbose"),
                 ("generate", "--today", TODAY, "--target", "6", "--yes"), ("generate", "--today", TODAY, "--target", "6", "--yes"), ("list",), ("list", "--status", "새 후보"), ("top",), ("show", "1"), ("show", "5"),
                 ("review", "--today", "2027-06-01"), ("backup",), ("restore", "--latest"), ("restore", "--latest", "--yes"), ("status",))
        for argv in steps:
            with self.subTest(argv=" ".join(argv)):
                code, out, err = self.run_cli(*argv)
                self.assertIn(code, (0, 1))
                self.clean(out, "출력")
                self.clean(err, "오류")


def folder_digests(folder):
    return {item.name: hashlib.sha256(item.read_bytes()).hexdigest() for item in sorted(Path(folder).iterdir()) if item.is_file()}


DEVELOPER_TEXT = re.compile(r"(?i)[A-Za-z]{3,}Error\b|Errno|Traceback|sqlite|not a database|JSONDecode|disk image|\bUNIQUE\b|\bfile is\b")


class ErrorDetailIsHiddenTest(unittest.TestCase):
    """`topics` 명령의 오류 화면·`--json` 에는 개발자용 세부(`AppError.detail` — 영어 SQLite 문장·예외 이름·내부 값)가 안 나온다. `--verbose`(또는 `--debug`)에서만 나온다(D-67)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.ctx = self.world.ctx

    def run_cli(self, *argv):
        return ss.run_cli(self.ctx, "topics", *argv)

    def break_store(self, how):
        self.run_cli("generate", "--today", TODAY, "--target", "4", "--yes")
        database = self.world.paths.database
        if how == "corrupt":
            database.write_bytes(b"this is not a database at all, just some english text " * 100)
        else:
            connection = sqlite3.connect(str(database))
            with connection:
                connection.execute("PRAGMA user_version = 99")
            connection.close()

    def test_a_broken_or_newer_store_shows_the_easy_error_without_the_hidden_detail_in_every_reading_and_writing_command(self):
        for how in ("corrupt", "newer"):
            for argv in (("list",), ("status",), ("plan", "--today", TODAY), ("backup",), ("generate", "--today", TODAY, "--yes"), ("restore", "--latest", "--yes"), ("init", "--yes")):
                with self.subTest(how=how, argv=" ".join(argv)):
                    with tempfile.TemporaryDirectory() as other:
                        world = World(other)
                        ss.run_cli(world.ctx, "topics", "generate", "--today", TODAY, "--target", "4", "--yes")
                        if how == "corrupt":
                            world.paths.database.write_bytes(b"this is not a database at all, just some english text " * 100)
                        else:
                            connection = sqlite3.connect(str(world.paths.database))
                            with connection:
                                connection.execute("PRAGMA user_version = 99")
                            connection.close()
                        code, out, err = ss.run_cli(world.ctx, "topics", *argv)
                        text = out + err
                        self.assertNotIn("세부:", text)
                        self.assertIsNone(DEVELOPER_TEXT.search(text), text)
                        code_json, out_json, _err = ss.run_cli(world.ctx, "topics", *argv, "--json")
                        if code_json == 1:
                            self.assertEqual(json.loads(out_json)["error"]["detail"], "", "--json 에도 세부가 없다")

    def test_a_broken_settings_file_and_a_very_long_data_path_show_only_the_easy_error(self):
        self.ctx.workspace.settings_path.write_text("{broken", encoding="utf-8")
        for argv in (("status",), ("plan", "--today", TODAY)):
            with self.subTest(argv=" ".join(argv)):
                code, out, err = self.run_cli(*argv)
                self.assertEqual(code, 1)
                self.assertIn("SETTINGS_INVALID", err)
                self.assertNotIn("세부:", out + err)
                self.assertIsNone(DEVELOPER_TEXT.search(out + err), out + err)
                code, out, err = self.run_cli(*argv, "--json")
                self.assertEqual(json.loads(out)["error"]["detail"], "")
        self.ctx.workspace.settings_path.unlink()
        error = FileNotFoundError(3, "The system cannot find the path specified", "C:\\" + "깊은폴더\\" * 30 + "topic_engine.db")          # 경로가 너무 길 때 윈도가 내는 OS 오류 모양
        with mock.patch.object(cli.topics, "init_topics", side_effect=error):
            code, out, err = self.run_cli("init", "--yes")
        self.assertEqual(code, 1)
        self.assertNotIn("FileNotFoundError", out + err)
        self.assertNotIn("깊은폴더", out + err, "경로·예외 이름은 화면에 나오지 않는다")
        self.assertNotIn("세부:", out + err)

    def test_verbose_and_debug_still_show_the_detail_for_the_developer(self):
        self.break_store("corrupt")
        code, out, err = self.run_cli("list", "--verbose")
        self.assertEqual(code, 1)
        self.assertIn("세부:", err, "--verbose 에서는 보인다")
        code, out, err = self.run_cli("list", "--verbose", "--json")
        self.assertIn("not a database", json.loads(out)["error"]["detail"])
        code, out, err = self.run_cli("list")
        self.assertNotIn("세부:", err)

    def test_an_unexpected_exception_becomes_the_easy_unexpected_error_without_its_name_and_message_unless_verbose_or_debug(self):
        boom = RuntimeError("개발자 메모 C:\\somewhere\\secret.txt")
        with mock.patch.object(cli.topics, "status", side_effect=boom):
            code, out, err = self.run_cli("status")
            self.assertEqual(code, 1)
            self.assertIn("예상하지 못한 오류", err)
            self.assertNotIn("RuntimeError", err + out)
            self.assertNotIn("개발자 메모", err + out)
            code, out, err = self.run_cli("status", "--json")
            self.assertEqual(json.loads(out)["error"]["detail"], "")
            code, out, err = self.run_cli("status", "--verbose")
            self.assertIn("RuntimeError", err)
            with self.assertRaises(RuntimeError):
                self.run_cli("status", "--debug")

    def test_an_os_error_with_a_typed_file_name_shows_only_its_kind_even_with_verbose(self):
        """리눅스의 `File name too long: '<친 글>'` 같은 OS 오류가 `topics` 명령에서 올라와도 `--verbose`·`--json` 에 친 글이 없고 종류(번호·OS 설명)만 있다(D-80)."""
        typed = "typed-" + "q" * 300
        boom = OSError(errno.ENAMETOOLONG, "File name too long", typed)
        with mock.patch.object(cli.topics, "status", side_effect=boom):
            for extra in ((), ("--verbose",), ("--json",), ("--verbose", "--json")):
                with self.subTest(extra=" ".join(extra)):
                    code, out, err = self.run_cli("status", *extra)
                    self.assertEqual(code, 1)
                    self.assertNotIn("qqqqqqqq", out + err)
                    self.assertNotIn("Traceback", err)
            code, out, err = self.run_cli("status", "--verbose")
            self.assertIn("OSError", err)
            self.assertIn(f"errno={errno.ENAMETOOLONG}", err)
            code, out, err = self.run_cli("status", "--verbose", "--json")
            self.assertTrue(json.loads(out)["error"]["detail"].startswith(f"OSError: errno={errno.ENAMETOOLONG} "))

    def test_usage_errors_and_the_restore_blocks_also_say_nothing_in_english(self):
        for argv in (("plan", "--target", "abc"), ("plan", "--channel", "없는채널"), ("show",), ("nothing",), ("restore", "--latest"), ("restore", "topic-20200101-000000", "--yes")):
            with self.subTest(argv=" ".join(argv)):
                code, out, err = self.run_cli(*argv)
                self.assertIn(code, (1, 2))
                self.assertNotIn("세부:", out + err)
                self.assertIsNone(DEVELOPER_TEXT.search(out + err), out + err)


class RestoreSafetyThroughTheCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.ctx = self.world.ctx
        ss.run_cli(self.ctx, "topics", "generate", "--today", TODAY, "--target", "4", "--yes")
        ss.run_cli(self.ctx, "topics", "backup")

    def test_a_current_seed_file_with_a_key_shape_stops_the_restore_with_a_clear_message_and_changes_nothing(self):
        data = json.loads(self.world.paths.seeds.read_text(encoding="utf-8"))
        data["seeds"][0]["keyword"] = f"예시 {KEY_LIKE}"
        self.world.paths.seeds.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        before = folder_digests(self.world.paths.folder)
        code, out, err = ss.run_cli(self.ctx, "topics", "restore", "--latest", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("TOPIC_BACKUP_BLOCKED", err)
        self.assertIn("seeds.json", err)
        self.assertIn("아무것도 바꾸지 않았습니다", err)
        self.assertNotIn("깨져", out + err, "멀쩡한 보관함을 '깨져 있던' 이라고 말하지 않는다")
        self.assertNotIn(KEY_LIKE, out + err)
        self.assertEqual(folder_digests(self.world.paths.folder), before)
        self.assertEqual([name for name in os.listdir(self.world.paths.folder) if ".bad-" in name], [])

    def test_a_broken_current_seed_file_is_kept_aside_and_the_screen_says_so(self):
        self.world.paths.seeds.write_bytes(b"{broken")
        code, out, err = ss.run_cli(self.ctx, "topics", "restore", "--latest", "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn("읽을 수 없던 지금 설정 파일은 지우지 않고 옆으로 옮겨 두었습니다", out)
        self.assertNotIn("깨져 있던 지금 후보 보관함", out, "보관함은 멀쩡했다")
        self.assertTrue([name for name in os.listdir(self.world.paths.folder) if name.startswith("seeds.json.bad-")])

    def test_the_json_output_of_a_restore_lists_the_files_kept_aside(self):
        self.world.paths.seeds.write_bytes(b"{broken")
        code, out, err = ss.run_cli(self.ctx, "topics", "restore", "--latest", "--yes", "--json")
        self.assertEqual(code, 0, err)
        data = json.loads(out)["data"]
        self.assertEqual(len(data["moved_json"]), 1)
        self.assertTrue(Path(data["moved_json"][0]).name.startswith("seeds.json.bad-"))
        self.assertIsNone(data["moved_aside"], "보관함은 멀쩡했다")

    def test_a_wrong_backup_name_gets_a_backup_specific_message_not_the_post_store_one(self):
        code, out, err = ss.run_cli(self.ctx, "topics", "restore", "topic-20200101-000000", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("TOPIC_BACKUP_INVALID", err)
        self.assertIn("백업 폴더에서 찾을 수 없습니다", err)
        self.assertNotIn("이미 지운 글", err)
        with tempfile.TemporaryDirectory() as other:
            code, out, err = ss.run_cli(World(other).ctx, "topics", "restore", "--latest", "--yes")
            self.assertEqual(code, 1)
            self.assertIn("topics backup", err, "백업이 하나도 없으면 먼저 만들라고 알린다")


class KeyShapeAndEmptyStoreThroughTheCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.ctx = self.world.ctx

    def test_generate_withholds_the_key_shaped_seed_names_it_and_check_warns_first(self):
        data = json.loads(self.world.paths.seeds.read_text(encoding="utf-8"))
        data["seeds"][0]["keyword"] = f"예시 {KEY_LIKE}"
        self.world.paths.seeds.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        code, out, err = ss.run_cli(self.ctx, "topics", "check", "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("키·토큰처럼 보이는 글이 든 곳", out)
        self.assertIn("씨앗 ‘g1’", out)
        self.assertNotIn(KEY_LIKE, out + err)
        code, out, err = ss.run_cli(self.ctx, "topics", "generate", "--today", TODAY, "--target", "6", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("후보를 만들지 않았습니다", out)
        self.assertIn("씨앗 ‘g1’", out)
        self.assertNotIn(KEY_LIKE, out + err)
        self.assertNotIn(KEY_LIKE.encode("utf-8"), self.world.paths.database.read_bytes())

    def test_a_zero_byte_store_is_shown_as_empty_and_the_save_command_makes_it(self):
        self.world.paths.folder.mkdir(parents=True, exist_ok=True)
        self.world.paths.database.write_bytes(b"")
        code, out, err = ss.run_cli(self.ctx, "topics", "status")
        self.assertEqual(code, 0, err)
        self.assertIn("비어 있음(0바이트", out)
        self.assertEqual(self.world.paths.database.stat().st_size, 0, "읽기 명령은 0바이트 파일을 바꾸지 않는다")
        code, out, err = ss.run_cli(self.ctx, "topics", "generate", "--today", TODAY, "--target", "3", "--yes")
        self.assertEqual(code, 0, err)
        self.assertGreater(self.world.paths.database.stat().st_size, 0)


class ErrorNotesTest(unittest.TestCase):
    """복원이 되돌리다 또 실패했을 때 못 돌린 파일 이름 같은 쉬운 말은 오류의 `notes` 로 '참고:' 줄에 보이고 `--json` 에도 담긴다(D-76) — 노트가 없는 오류의 출력은 그대로다."""

    def test_notes_are_shown_as_reference_lines_and_in_json_only_when_there_are_some(self):
        plain = AppError("TOPIC_STORE_LOCKED")
        self.assertEqual(cli._error_text(plain, False), fmt.error_lines(plain), "노트가 없는 오류의 출력은 그대로다")
        self.assertNotIn("notes", cli._error_payload(plain))
        noted = AppError("TOPIC_STORE_LOCKED")
        noted.notes = ("calendar.json 은(는) 원래 내용으로 돌리지 못했습니다 — 원래 내용은 직전 상태 백업(`before-restore`)에 있습니다",)
        lines = cli._error_text(noted, False)
        self.assertIn("  참고: " + noted.notes[0], lines)
        self.assertEqual(lines[1], "  코드: TOPIC_STORE_LOCKED", "원래 오류 코드는 그대로다")
        self.assertEqual(cli._error_payload(noted)["notes"], list(noted.notes))

    def test_every_note_is_shown_and_listed_in_json_not_only_the_first(self):
        error = AppError("TOPIC_STORE_LOCKED")
        error.notes = ("첫째 파일 안내", "둘째 파일 안내", "셋째 파일 안내")
        shown = [line for line in cli._error_text(error, False) if line.startswith("  참고: ")]
        self.assertEqual(shown, ["  참고: 첫째 파일 안내", "  참고: 둘째 파일 안내", "  참고: 셋째 파일 안내"])
        self.assertEqual(cli._error_payload(error)["notes"], ["첫째 파일 안내", "둘째 파일 안내", "셋째 파일 안내"])

    def test_a_restore_that_fails_twice_shows_the_original_code_and_the_file_names_through_the_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            ss.run_cli(world.ctx, "topics", "generate", "--today", TODAY, "--target", "4", "--yes")
            ss.run_cli(world.ctx, "topics", "backup")
            world.paths.database.write_bytes(b"junk" * 1024)
            world.paths.seeds.write_bytes(b'{"seeds": [oops')
            state, real_write = {"rolling": False}, bk._write_bytes

            def fail_restore(self_, backup):
                state["rolling"] = True
                raise AppError("TOPIC_STORE_LOCKED", detail="일부러 낸 첫 실패")

            def full_disk(path, data):
                if state["rolling"]:
                    raise OSError(errno.ENOSPC, "일부러 낸 디스크 가득")
                return real_write(path, data)

            with mock.patch.object(TopicStore, "restore_from", fail_restore), mock.patch.object(bk, "_write_bytes", full_disk):
                code, out, err = ss.run_cli(world.ctx, "topics", "restore", "--latest", "--yes")
                self.assertEqual(code, 1)
                self.assertIn("코드: TOPIC_STORE_LOCKED", err, "원래 오류 코드가 그대로다")
                self.assertIn("참고:", err)
                self.assertIn(layout.CALENDAR_FILE, err, "돌리지 못한 파일의 이름이 쉬운 말로 보인다")
                self.assertNotIn("OSError", err)
                state["rolling"] = False
                code, out, err = ss.run_cli(world.ctx, "topics", "restore", "--latest", "--yes", "--json")
            payload = json.loads(out)
            self.assertEqual(payload["error"]["code"], "TOPIC_STORE_LOCKED")
            self.assertTrue(payload["error"]["notes"])
            self.assertEqual([name for name in os.listdir(world.paths.folder) if ".bad-" in name or name.endswith(".restoring")], [], "옮긴 파일은 모두 제자리로 돌아왔다")


class ZeroByteSettingsThroughTheCliTest(unittest.TestCase):
    def test_init_yes_fills_a_zero_byte_settings_file_and_check_says_so_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            world.paths.folder.mkdir(parents=True, exist_ok=True)
            world.paths.seeds.write_bytes(b"")
            code, out, err = ss.run_cli(world.ctx, "topics", "check")
            self.assertEqual(code, 1)
            self.assertIn("topics init --yes", out, "0바이트 파일은 채우는 길을 알려 준다")
            code, out, err = ss.run_cli(world.ctx, "topics", "init", "--yes")
            self.assertEqual(code, 0, err)
            self.assertGreater(world.paths.seeds.stat().st_size, 0)
            code, out, err = ss.run_cli(world.ctx, "topics", "check")
            self.assertEqual(code, 0, out + err)

    def test_check_shows_a_published_post_with_a_key_shape_in_its_own_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            folder = world.repo / "_posts" / "예시"
            folder.mkdir(parents=True)
            (folder / "2026-10-01-KR-100000.md").write_text(f'---\nlayout: post\ntitle: "예시 {KEY_LIKE}"\ncategory: "예시"\ntags: ["가"]\nlang: "ko"\nimage: "https://example.invalid/a.jpg"\n---\n본문\n', encoding="utf-8")
            code, out, err = ss.run_cli(world.ctx, "topics", "check", "--today", TODAY)
            self.assertEqual(code, 0, err)
            self.assertIn("발행한 글(블로그)에 키·토큰처럼 보이는 글이 든 곳", out)
            self.assertIn("백업은 막지 않습니다", out)
            self.assertNotIn(KEY_LIKE, out + err)
            code, out, err = ss.run_cli(world.ctx, "topics", "check", "--today", TODAY, "--json")
            self.assertEqual(len(json.loads(out)["data"]["public_key_shaped"]), 1)


class ListShowReviewLabelsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.ctx = self.world.ctx
        ss.run_cli(self.ctx, "topics", "generate", "--today", TODAY, "--target", "6", "--yes")

    def test_the_review_shows_days_left_before_the_deadline_and_the_word_expired_after_it(self):
        code, out, _err = ss.run_cli(self.ctx, "topics", "review", "--today", TODAY)
        self.assertEqual(code, 0)
        self.assertIn("90일", out)
        self.assertNotIn("지남", out.replace("기한이 지난 것 0개", ""))
        code, out, _err = ss.run_cli(self.ctx, "topics", "review", "--today", "2027-06-01")
        self.assertIn("지남", out)
        self.assertNotRegex(out, r"\d+일\s+예시")

    def test_the_auto_draft_stop_mark_is_shown_in_the_list_and_the_detail_only_when_the_calculation_says_so(self):
        plain = ss.run_cli(self.ctx, "topics", "list")[1] + ss.run_cli(self.ctx, "topics", "show", "1")[1]
        self.assertNotIn("(자동 초안 중지)", plain)
        real_assess = cli.topics.safety.assess

        def forced_stop(candidate):                                                      # 계산 결과만 '중지' 로 바꾼다(나머지 칸은 진짜 안전 표시)
            real = real_assess(candidate)
            return SimpleNamespace(**real._asdict(), level=real.level, stop=True)

        with mock.patch.object(cli.topics, "safety", SimpleNamespace(assess=forced_stop)):
            listed = ss.run_cli(self.ctx, "topics", "list")[1]
            shown = ss.run_cli(self.ctx, "topics", "show", "1")[1]
        self.assertEqual(listed.count("(자동 초안 중지)"), len([line for line in listed.splitlines() if re.match(r"\s*\d+\s+[0-9a-f]{8}", line)]), "목록의 모든 후보 줄에 표시")
        self.assertIn("(자동 초안 중지)", shown)

    def test_a_target_written_with_digits_of_other_scripts_is_a_usage_error_not_a_number(self):
        for typed in (chr(0x663), chr(0xFF13), chr(0x0663) + "0", "3" + chr(0x0660)):
            with self.subTest(typed=ascii(typed)):
                code, out, err = ss.run_cli(self.ctx, "topics", "plan", "--target", typed)
                self.assertEqual(code, 2)
                self.assertIn("채널당 후보 수", err)
                self.assertNotIn(typed, err)

    def test_the_backup_help_says_it_is_the_only_exception_to_read_only_by_default(self):
        code, out, _err = ss.run_cli(self.ctx, "topics", "backup", "--help")
        self.assertEqual(code, 0)
        flat = " ".join(out.split())
        self.assertIn("읽기 전용 기본의 유일한 예외", flat)
        self.assertIn("기존 데이터는 바꾸지 않", flat)
        self.assertIn("오래된 백업", flat)


class UsageErrorsDoNotEchoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = World(self.tmp.name).ctx

    def test_a_key_shaped_value_in_any_place_is_never_shown_again(self):
        cases = (
            ("status", KEY_LIKE), ("plan", "--channel", KEY_LIKE), ("plan", "--today", KEY_LIKE), ("plan", "--target", KEY_LIKE), ("plan", f"--{KEY_LIKE}"), ("plan", f"--yes={KEY_LIKE}"),
            ("plan", "--json=" + KEY_LIKE), ("generate", "--yes", KEY_LIKE), ("list", "--status", KEY_LIKE), ("list", "--band", KEY_LIKE), ("list", "--channel", KEY_LIKE), ("show",), ("show", KEY_LIKE),
            ("show", "1", KEY_LIKE), ("restore", KEY_LIKE), ("restore", KEY_LIKE, "--yes"), ("restore", "--latest", KEY_LIKE), ("backup", KEY_LIKE), ("review", "--today", KEY_LIKE),
            (KEY_LIKE,), ("plan", "--today", "2026-11-10", "--target", "0"),
        )
        for argv in cases:
            for flag in ((), ("--json",)):
                with self.subTest(argv=" ".join(argv)[:40], flag=flag):
                    code, out, err = ss.run_cli(self.ctx, "topics", *argv, *flag)
                    self.assertIn(code, (1, 2), f"{argv} → {code}")
                    self.assertNotIn(KEY_LIKE, out + err)
                    self.assertNotIn(KEY_LIKE[:20], out + err, "키 모양의 앞부분도 남지 않는다")

    def test_abbreviated_options_are_refused_so_a_shortcut_cannot_trigger_a_save(self):
        for argv in (("generate", "--y"), ("generate", "--ye"), ("init", "--yes1"), ("restore", "--lat"), ("plan", "--tod", TODAY), ("plan", "--tar", "3")):
            with self.subTest(argv=argv):
                code, out, err = ss.run_cli(self.ctx, "topics", *argv)
                self.assertEqual(code, 2)
        self.assertFalse(tf_database(self.ctx).exists())

    def test_the_usage_error_names_the_option_in_plain_words_not_the_value(self):
        code, out, err = ss.run_cli(self.ctx, "topics", "plan", "--target", "abc")
        self.assertEqual(code, 2)
        self.assertIn("사용법 오류", err)
        self.assertIn("채널당 후보 수", err)
        self.assertNotIn("abc", err)
        code, out, err = ss.run_cli(self.ctx, "topics", "plan", "--today", "내일")
        self.assertEqual(code, 2)
        self.assertNotIn("내일", err)
        code, out, err = ss.run_cli(self.ctx, "topics", "nothing")
        self.assertEqual(code, 2)
        self.assertNotIn("nothing", err)
        for argv, typed in ((("plan", "--channel", "내채널이름"), "내채널이름"), (("list", "--band", "내구간이름"), "내구간이름"), (("list", "--status", "내상태이름"), "내상태이름")):
            with self.subTest(argv=" ".join(argv)):
                code, out, err = ss.run_cli(self.ctx, "topics", *argv)
                self.assertEqual(code, 2)
                self.assertIn("다음 중 하나여야 합니다", err)
                self.assertNotIn(typed, out + err, "틀린 값(키 모양이 아닌 보통 글도)은 되풀이하지 않는다")

    def test_the_not_found_errors_repeat_only_number_shaped_text(self):
        code, out, err = ss.run_cli(self.ctx, "topics", "show", "7")
        self.assertEqual(code, 1)
        self.assertIn("TOPIC_CANDIDATE_NOT_FOUND", err)
        code, out, err = ss.run_cli(self.ctx, "topics", "show", "abc123")
        self.assertIn("abc123", err, "번호 모양은 되풀이한다(친 번호를 확인할 수 있게)")
        code, out, err = ss.run_cli(self.ctx, "topics", "restore", "topic-20200101-000000", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("topic-20200101-000000", err)
        code, out, err = ss.run_cli(self.ctx, "topics", "restore", "내 폴더 이름", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("(입력한 파일)", err)
        self.assertNotIn("내 폴더 이름", err)


class NoticeLinesTest(unittest.TestCase):
    def make(self, code, title, *details):
        return notice.Notice(code=code, level="WARNING", title=title, message="무슨 일인지 설명합니다.", action="이렇게 하세요.", details=details)

    def test_notices_with_the_same_code_are_one_entry_with_all_their_details_in_order_without_repeats(self):
        lines = tfmt._notice_lines([self.make("HEALTH_TOPIC", "첫째 제목", "가 · 1건"), self.make("ECONOMIC_CHECK", "둘째 제목", "다 · 3건"), self.make("HEALTH_TOPIC", "첫째 제목", "나 · 2건", "가 · 1건")])
        self.assertEqual(lines, ["  - 첫째 제목: 무슨 일인지 설명합니다. 이렇게 하세요.", "      · 가 · 1건", "      · 나 · 2건", "  - 둘째 제목: 무슨 일인지 설명합니다. 이렇게 하세요.", "      · 다 · 3건"])

    def test_a_long_detail_list_is_cut_after_four_lines_with_the_count_of_the_rest(self):
        lines = tfmt._notice_lines([self.make("HEALTH_TOPIC", "제목", *[f"세부 {number}" for number in range(1, 7)])], indent="")
        self.assertEqual(lines[0], "- 제목: 무슨 일인지 설명합니다. 이렇게 하세요.")
        self.assertEqual(lines[1:], ["    · 세부 1", "    · 세부 2", "    · 세부 3", "    · 세부 4", "    · 그 밖에 2건"])


def tf_database(ctx):
    from chanceblog_desktop.service import topic_files as tf
    return tf.topic_paths(ctx.workspace).database


class StoreStatesInCliTest(unittest.TestCase):
    def test_a_newer_or_broken_store_is_reported_by_status_and_refused_by_the_other_commands_without_changing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            world.generate(target=4)
            database = world.paths.database
            connection = sqlite3.connect(str(database))
            with connection:
                connection.execute("PRAGMA user_version = 9")
            connection.close()
            before = database.read_bytes()
            code, out, _err = ss.run_cli(world.ctx, "topics", "status")
            self.assertEqual(code, 0)
            self.assertIn("더 새로운 버전", out)
            for argv in (("plan",), ("list",), ("top",), ("review",), ("generate", "--yes"), ("backup",)):
                with self.subTest(argv=argv):
                    code, out, err = ss.run_cli(world.ctx, "topics", *argv)
                    self.assertEqual(code, 1)
                    self.assertTrue("TOPIC_STORE_VERSION_UNSUPPORTED" in err or "TOPIC_BACKUP_BLOCKED" in err, err)
                    self.assertEqual(database.read_bytes(), before, "더 새로운 파일은 한 바이트도 바뀌지 않는다")


if __name__ == "__main__":
    unittest.main()
