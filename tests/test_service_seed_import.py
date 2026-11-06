"""씨앗 제안 불러오기(P3b-1 S1 — `topics.import_seeds`·명령줄 `topics seeds import`) 시험.

지키는 것: ① 기본은 미리 보기이고 `--yes` 가 없으면 아무것도 쓰지 않는다(파일 하나 만들지 않는다) ② 불러온 씨앗은 모두 승인 전(`proposed`) — 후보 생성에 쓰이지 않는다 ③ 이미 있는 씨앗은 덮어쓰지 않고 건너뛴다
④ 읽을 수 없는 씨앗이 하나라도 있으면 아무것도 쓰지 않는다 ⑤ 키·토큰 모양 글은 불러오지 않고 화면에 되풀이하지 않는다 ⑥ 친 파일 경로와 파일 속 글은 오류 문구에 되풀이하지 않는다 — 리눅스에서만 드러나는
파일 이름 길이 오류(ENAMETOOLONG)나 경로 구분자에 기대지 않는다(P3 에서 두 번 겪었다: 어느 OS 에서든 같은 고정 문구여야 한다) ⑦ 판 1 `seeds.json` 에 더하면 판 2 로 올리고 옛 모양 사본을 남긴다.
입력은 모두 시험용 예시이고 네트워크 없이 돈다.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402
import topics_support as ts  # noqa: E402
from test_service_topics import World, digest, put, tree  # noqa: E402
from test_topics_seeds_v2 import proposal, proposal_file  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import topic_files as tf  # noqa: E402
from chanceblog_desktop.service import topics as tp  # noqa: E402
from chanceblog_desktop.topics import notice, seeds  # noqa: E402

KEY_LIKE = "AI" + "za" + "E" * 35
TODAY = "2026-11-06"


def write_file(folder, name, data):
    path = Path(folder) / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def entries(count):
    return [proposal(id=f"EX{number:03d}", keyword=f"예시 물건 {number}") for number in range(1, count + 1)]


class PreviewAndApplyTest(unittest.TestCase):
    def test_the_default_is_a_preview_that_writes_nothing_not_even_the_data_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            source = write_file(tmp, "proposal.json", proposal_file(*entries(3)))
            before = tree(tmp)
            result = tp.import_seeds(world.ctx, source, today=TODAY)
            self.assertEqual((result.applied, result.total, len(result.new), result.skipped, result.rejected), (False, 3, 3, (), ()))
            self.assertEqual(tree(tmp), before, "미리 보기는 파일을 하나도 만들거나 바꾸지 않는다(topic_engine 폴더도 만들지 않는다)")
            self.assertFalse(world.paths.seeds.exists())

    def test_applying_registers_every_seed_as_proposed_and_they_are_not_used_for_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            source = write_file(tmp, "proposal.json", proposal_file(*entries(3), default_status="active"))
            result = tp.import_seeds(world.ctx, source, apply=True, today=TODAY)
            self.assertEqual((result.applied, len(result.new)), (True, 3))
            saved = tf.load_seeds(world.paths).value
            self.assertEqual([item.state for item in saved], ["proposed"] * 3)
            self.assertEqual(json.loads(world.paths.seeds.read_text(encoding="utf-8"))["schema"], 2)
            planned = world.plan(channel="naver_a")
            self.assertEqual(sum(len(item.candidates) for item in planned.plans), 0, "승인 전 씨앗은 후보 생성에 쓰이지 않는다")
            self.assertTrue(any("승인 전" in note for note in result.notes), "파일이 다른 상태를 적었어도 무시했다고 알린다")

    def test_an_existing_seed_is_skipped_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            put(world.paths.seeds, seeds.seeds_to_dict((ts.example_seed(seed_id="EX001", keyword="예시 내가 쓰던 것", scope="naver_a"),
                                                       ts.example_seed(seed_id="EX900", keyword="예시 물건 2", scope="naver_a"))))
            source = write_file(tmp, "proposal.json", proposal_file(*entries(3)))
            result = tp.import_seeds(world.ctx, source, apply=True, today=TODAY)
            self.assertEqual([name for name, _why in result.skipped], ["EX001", "EX002"], "번호가 같거나(EX001) 같은 소속의 같은 낱말(EX002 = 예시 물건 2)이면 건너뜀")
            self.assertEqual([item.seed_id for item in result.new], ["EX003"])
            saved = {item.seed_id: item for item in tf.load_seeds(world.paths).value}
            self.assertEqual(saved["EX001"].keyword, "예시 내가 쓰던 것", "있던 씨앗은 그대로다")
            self.assertEqual(saved["EX001"].state, "active")
            self.assertEqual(saved["EX003"].state, "proposed")
            again = tp.import_seeds(world.ctx, source, apply=True, today=TODAY)
            self.assertEqual((again.applied, len(again.new), len(again.skipped)), (False, 0, 3), "다시 해도 아무것도 바뀌지 않는다")

    def test_a_rejected_seed_stops_everything_and_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            good = entries(2)
            bad = proposal(id="EX777", keyword="예시 틀린 것", target_type="gadget")
            source = write_file(tmp, "proposal.json", proposal_file(*good, bad))
            before = tree(tmp)
            for apply in (False, True):
                result = tp.import_seeds(world.ctx, source, apply=apply, today=TODAY)
                self.assertEqual((result.applied, result.blocked, [name for name, _why in result.rejected]), (False, True, ["EX777"]))
                self.assertEqual(tree(tmp), before)

    def test_a_key_shaped_seed_is_not_imported_and_its_text_is_never_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            leaky = proposal(id="EX050", keyword="예시 " + KEY_LIKE)
            source = write_file(tmp, "proposal.json", proposal_file(*entries(2), leaky))
            result = tp.import_seeds(world.ctx, source, apply=True, today=TODAY)
            self.assertEqual((result.applied, [name for name, _why in result.rejected]), (False, ["EX050"]))
            shown = json.dumps(result.to_dict(), ensure_ascii=False) + " ".join(" ".join(map(str, row)) for row in result.rejected)
            self.assertNotIn(KEY_LIKE, shown)
            idkey = write_file(tmp, "idkey.json", proposal_file(proposal(id=KEY_LIKE, keyword="예시 번호가 키")))
            masked = tp.import_seeds(world.ctx, idkey, today=TODAY)
            self.assertNotIn(KEY_LIKE, json.dumps(masked.to_dict(), ensure_ascii=False), "번호 자체가 키 모양이면 이름을 가린다")

    def test_the_total_stays_within_the_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            put(world.paths.seeds, seeds.seeds_to_dict(tuple(ts.example_seed(seed_id=f"ex-{n:04d}", keyword=f"예시 기존 {n}") for n in range(seeds.MAX_SEEDS - 1))))
            source = write_file(tmp, "proposal.json", proposal_file(*entries(2)))
            with self.assertRaises(AppError) as caught:
                tp.import_seeds(world.ctx, source, apply=True, today=TODAY)
            self.assertEqual(caught.exception.code, "CONTENT_INVALID")

    def test_the_preview_shows_how_many_seeds_each_channel_could_use_and_whether_it_generates(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            mixed = [proposal(id="EX001", keyword="예시 하나", scope="common", allowed_channels=["naver_a", "github_pages"]), proposal(id="EX002", keyword="예시 둘", scope="blogger_en", allowed_channels=["blogger_en"])]
            result = tp.import_seeds(world.ctx, write_file(tmp, "proposal.json", proposal_file(*mixed)), today=TODAY)
            self.assertEqual(result.per_channel, (("github_pages", 1, False), ("blogger_en", 1, False), ("blogger_ko", 0, False), ("naver_a", 1, True), ("naver_b", 0, True)))


class LimitsAndStrictnessTest(unittest.TestCase):
    """독립 검증 1라운드 A-L1 ③④·A-L4. 상한 상수는 `mock.patch` 로 작게 바꿔 쓴다(8MB 파일이나 1,000개 씨앗을 실제로 만들지 않는다). 두 한도 시험은 일부러 **정상으로 읽히는** 파일과 **미리 보기**로 돈다 —
    그래야 한도 검사 자신이 없어졌을 때 다른 검사(큰 빈 파일의 'JSON 아님' 거절·쓰기 단계의 씨앗 목록 검사)가 대신 막아 시험이 통과하는 일이 없다."""

    def test_a_file_over_the_size_limit_is_refused_with_the_too_big_message_and_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            source = write_file(tmp, "proposal.json", proposal_file(*entries(3)))              # 정상으로 읽히는 파일 — 크기 검사가 없으면 그냥 불러와진다
            size = source.stat().st_size
            before = tree(tmp)
            with mock.patch.object(tp, "MAX_JSON_BYTES", size - 1):
                for apply in (False, True):
                    with self.subTest(apply=apply):
                        with self.assertRaises(AppError) as caught:
                            tp.import_seeds(world.ctx, source, apply=apply, today=TODAY)
                        self.assertEqual(caught.exception.code, "CONTENT_INVALID")
                        self.assertIn("파일이 너무 큽니다", str(caught.exception.slots["항목"]), "'JSON 아님' 이 아니라 '너무 큼' 으로 거절한다")
            self.assertEqual(tree(tmp), before, "아무것도 쓰지 않았다")
            with mock.patch.object(tp, "MAX_JSON_BYTES", size):
                self.assertEqual(len(tp.import_seeds(world.ctx, source, today=TODAY).new), 3, "딱 상한인 파일은 받는다")

    def test_the_preview_refuses_when_the_total_would_pass_the_seed_limit_and_a_total_exactly_at_the_limit_is_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            put(world.paths.seeds, seeds.seeds_to_dict((ts.example_seed(seed_id="ex-1", keyword="예시 기존 1"), ts.example_seed(seed_id="ex-2", keyword="예시 기존 2"))))
            source = write_file(tmp, "proposal.json", proposal_file(*entries(3)))
            before = tree(tmp)
            with mock.patch.object(seeds, "MAX_SEEDS", 4):                                      # 기존 2 + 새 3 = 5 > 4
                with self.assertRaises(AppError) as caught:
                    tp.import_seeds(world.ctx, source, today=TODAY)                              # 미리 보기 — 쓰기 단계의 검사가 없으니 불러오기 자신의 검사만 막는다
                self.assertEqual(caught.exception.code, "CONTENT_INVALID")
                self.assertIn("개를 넘습니다", str(caught.exception.slots["항목"]))
                with self.assertRaises(AppError):
                    tp.import_seeds(world.ctx, source, apply=True, today=TODAY)
            self.assertEqual(tree(tmp), before, "아무것도 쓰지 않았다")
            with mock.patch.object(seeds, "MAX_SEEDS", 5):                                      # 2 + 3 = 5 — 딱 한도
                self.assertEqual(len(tp.import_seeds(world.ctx, source, today=TODAY).new), 3)

    def test_only_a_real_true_writes_values_that_merely_look_true_stay_a_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            good = write_file(tmp, "good.json", proposal_file(*entries(2)))
            bad = write_file(tmp, "bad.json", proposal_file(*entries(1), proposal(id="EX777", keyword="예시 틀린 것", target_type="gadget")))
            before = tree(tmp)
            for loose in ("false", "true", "yes", "1", 1, 2, ["x"], object()):
                with self.subTest(apply=type(loose).__name__ + str(loose)[:6]):
                    result = tp.import_seeds(world.ctx, good, apply=loose, today=TODAY)
                    self.assertEqual((result.applied, len(result.new), result.kept_copy), (False, 2, None), "쓰지 않고 미리 보기만 한다(`cleanup_hold`·`generate` 의 `is True` 와 같다)")
                    self.assertEqual(tree(tmp), before)
                    blocked = tp.import_seeds(world.ctx, bad, apply=loose, today=TODAY)
                    self.assertTrue(blocked.blocked)
                    self.assertTrue(any("있으면 저장하지 않습니다" in note for note in blocked.notes), "안내 문구도 미리 보기 쪽이다('저장하지 않았습니다' 가 아니다)")
            self.assertFalse(world.paths.seeds.exists())
            written = tp.import_seeds(world.ctx, good, apply=True, today=TODAY)
            self.assertEqual((written.applied, len(written.new)), (True, 2), "진짜 True 는 쓴다")
            refused = tp.import_seeds(world.ctx, bad, apply=True, today=TODAY)
            self.assertTrue(any("아무것도 저장하지 않았습니다" in note for note in refused.notes))


class VersionOneFileTest(unittest.TestCase):
    def test_adding_to_a_version_1_file_upgrades_it_and_keeps_the_old_shape_as_a_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            old = {"schema": 1, "seeds": [{key: value for key, value in ts.example_seed(seed_id="ex-old", keyword="예시 옛 씨앗").to_dict().items() if key in seeds._KEYS_V1}]}
            put(world.paths.seeds, old)
            result = tp.import_seeds(world.ctx, write_file(tmp, "proposal.json", proposal_file(*entries(1))), apply=True, today=TODAY)
            self.assertEqual(result.kept_copy, "seeds.json.v1.bak")
            copy = json.loads((world.paths.seeds.parent / "seeds.json.v1.bak").read_text(encoding="utf-8"))
            self.assertEqual(copy, old, "사본은 옛 모양 그대로다")
            self.assertEqual(json.loads(world.paths.seeds.read_text(encoding="utf-8"))["schema"], 2)
            self.assertEqual([item.seed_id for item in tf.load_seeds(world.paths).value], ["ex-old", "EX001"])

    def test_an_existing_different_copy_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            old = {"schema": 1, "seeds": []}
            put(world.paths.seeds, old)
            other = world.paths.seeds.parent / "seeds.json.v1.bak"
            other.write_text('{"schema": 1, "seeds": ["다른 사본"]}', encoding="utf-8")
            before = digest(other)
            result = tp.import_seeds(world.ctx, write_file(tmp, "proposal.json", proposal_file(*entries(1))), apply=True, today=TODAY)
            self.assertEqual(result.kept_copy, "seeds.json.v1.2.bak")
            self.assertEqual(digest(other), before)

    def test_a_version_2_file_needs_no_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            put(world.paths.seeds, seeds.seeds_to_dict(()))
            result = tp.import_seeds(world.ctx, write_file(tmp, "proposal.json", proposal_file(*entries(1))), apply=True, today=TODAY)
            self.assertIsNone(result.kept_copy)
            self.assertEqual(sorted(path.name for path in world.paths.seeds.parent.iterdir()), ["seeds.json"])


class InputSourceTest(unittest.TestCase):
    def test_a_path_text_that_looks_like_json_is_still_a_path_when_it_is_a_path_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            text = json.dumps(proposal_file(*entries(1)), ensure_ascii=False)
            self.assertEqual(len(tp.import_seeds(world.ctx, text, today=TODAY).new), 1, "글(JSON)을 직접 줘도 된다")
            self.assertEqual(len(tp.import_seeds(world.ctx, text.encode("utf-8"), today=TODAY).new), 1)
            with self.assertRaises(AppError):
                tp.import_seeds(world.ctx, Path(text), today=TODAY)

    def test_unreadable_inputs_give_fixed_korean_errors_that_never_repeat_the_typed_path_or_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            secret_name = "비밀" + KEY_LIKE
            cases = [Path(tmp) / secret_name, Path(tmp) / ("긴" * 400), Path(tmp), Path(tmp) / "빈\x00이름"]
            for source in cases:
                with self.subTest(source=type(source).__name__ + str(len(str(source)))):
                    with self.assertRaises(AppError) as caught:
                        tp.import_seeds(world.ctx, source, today=TODAY)
                    shown = str(caught.exception.slots) + str(caught.exception.detail)
                    self.assertEqual(caught.exception.code, "CONTENT_INVALID")
                    self.assertNotIn(KEY_LIKE, shown)
                    self.assertNotIn("긴" * 20, shown)
                    self.assertNotIn(tmp, shown, "친 경로를 되풀이하지 않는다")
                    self.assertTrue(notice.is_clean(str(caught.exception.slots["항목"])))
            garbage = Path(tmp) / "garbage.json"
            garbage.write_bytes(b"\xff\xfe not json " + KEY_LIKE.encode())
            with self.assertRaises(AppError) as caught:
                tp.import_seeds(world.ctx, garbage, today=TODAY)
            self.assertNotIn(KEY_LIKE, str(caught.exception.slots) + str(caught.exception.detail), "파일 속 글을 되풀이하지 않는다")
            huge = Path(tmp) / "huge.json"
            huge.write_bytes(b" " * (tp.MAX_JSON_BYTES + 1))
            with self.assertRaises(AppError) as caught:
                tp.import_seeds(world.ctx, huge, today=TODAY)
            self.assertEqual(caught.exception.code, "CONTENT_INVALID")

    def test_a_broken_existing_seeds_file_is_reported_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            world.paths.seeds.parent.mkdir(parents=True)
            world.paths.seeds.write_text("{ 깨진 파일", encoding="utf-8")
            before = digest(world.paths.seeds)
            with self.assertRaises(AppError) as caught:
                tp.import_seeds(world.ctx, write_file(tmp, "proposal.json", proposal_file(*entries(1))), apply=True, today=TODAY)
            self.assertEqual(caught.exception.code, "TOPIC_FILE_INVALID")
            self.assertEqual(digest(world.paths.seeds), before)


class CommandLineTest(unittest.TestCase):
    def run_cli(self, world, *argv):
        return ss.run_cli(world.ctx, "topics", "seeds", "import", *argv)

    def test_preview_apply_json_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            source = str(write_file(tmp, "proposal.json", proposal_file(*entries(2))))
            code, out, err = self.run_cli(world, source)
            self.assertEqual((code, err), (0, ""))
            self.assertIn("미리 보기", out)
            self.assertIn("--yes", out)
            self.assertFalse(world.paths.seeds.exists())
            code, out, err = self.run_cli(world, source, "--yes")
            self.assertEqual((code, err), (0, ""))
            self.assertIn("새로 등록한 씨앗 2개(모두 승인 전)", out)
            self.assertEqual(len(tf.load_seeds(world.paths).value), 2)
            code, out, _err = self.run_cli(world, source, "--json")
            envelope = json.loads(out)
            data = envelope["data"]
            self.assertEqual((code, envelope["ok"], envelope["command"], data["applied"], data["new"], len(data["skipped"])), (0, True, "topics seeds import", False, 0, 2))
            bad = str(write_file(tmp, "bad.json", proposal_file(proposal(id="EX900", keyword="예시 하나", importance="weird"))))
            code, out, _err = self.run_cli(world, bad)
            self.assertEqual(code, 1, "읽을 수 없는 씨앗이 있으면 종료 코드 1")
            self.assertIn("EX900", out)

    def test_a_missing_or_unreadable_file_is_a_handled_error_that_does_not_echo_the_typed_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            for typed in ("비밀" + KEY_LIKE, "{" + KEY_LIKE + "}", "긴" * 300, str(Path(tmp)), "없는/폴더/" + KEY_LIKE):
                with self.subTest(typed=typed[:10]):
                    code, out, err = self.run_cli(world, typed, "--verbose", "--json")
                    self.assertEqual(code, 1)
                    self.assertNotIn(KEY_LIKE, out + err)
                    self.assertNotIn("긴" * 20, out + err)
                    self.assertNotIn("Traceback", err)

    def test_without_a_file_it_is_a_usage_error_and_the_group_without_a_subcommand_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, with_world=False)
            self.assertEqual(ss.run_cli(world.ctx, "topics", "seeds", "import")[0], 2)
            self.assertEqual(ss.run_cli(world.ctx, "topics", "seeds")[0], 2)
            self.assertEqual(ss.run_cli(world.ctx, "topics", "seeds", "import", "x.json", "--y")[0], 2, "줄임 옵션은 받지 않는다")


if __name__ == "__main__":
    unittest.main()
