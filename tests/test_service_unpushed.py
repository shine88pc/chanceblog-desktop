"""서비스 층 — 연결한 저장소에 '올리지 않은 commit' 이 있을 때 **정확한 안내 한 가지**를 하는지(`service/unpushed.py`)를 확인한다.

상황이 넷이다. 앱이 올리다 멈춘 글 하나의 기록(이어받기 — `resume`), 그런 글이 둘 겹친 것(`overlap` — 나중 글부터 되돌린다), 앱이 만든 것이 아닌 commit(`unknown`),
앱이 아는 기록과 모르는 commit 이 섞인 것(`mixed`). `publish-pages`(미리 보기 포함)·`doctor` 가 같은 말을 하고, 일반 문구('앱은 남의 커밋을 지우거나 되돌리지 않습니다')가 이어받기 안내와 어긋나게 나오지 않는다.
올리고 나서(기록을 마치기 전에) 멈춘 글은 올리지 않은 commit 이 아니다 — `--cancel` 은 전용 오류(`PUBLISH_ALREADY_PUSHED`)로 거절하고 같은 명령이 마무리한다. 공개된 글에 남은 발행 기록은 다음 호출이 정리한다.

빠른 시험(가짜 backend — 상황을 값으로 만든다)이 모양을 모두 확인하고, 진짜 git(로컬 bare 저장소) 시험은 안내대로 하면 실제로 두 글이 모두 올라가는지를 확인한다.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import status as st  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.publish.pages import CommitInfo  # noqa: E402
from chanceblog_desktop.render.pages import PagesPost, post_path  # noqa: E402
from chanceblog_desktop.service import doctor, gate, pages_flow, review, unpushed  # noqa: E402
from chanceblog_desktop.service.backend import GitPagesBackend  # noqa: E402
from chanceblog_desktop.service.journal import STAGE_COMMITTED, STAGE_PUSHED, Journal, PublishRecord  # noqa: E402

OLD_GENERIC = "앱은 남의 커밋을 지우거나 되돌리지 않습니다"                # 예전 doctor 의 일반 문구 — 이어받기 안내와 어긋났다
TOP = "d" * 40                                                      # 가짜 저장소의 맨 위 commit


# ---- 빠른 시험: 가짜 backend ------------------------------------------------------------------------------------------------------
class FakeBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.backend = ss.FakeBackend()
        self.backend.head = TOP
        self.ctx = ss.make_ctx(self.tmp, backend=self.backend)
        self.journal = Journal(self.ctx.workspace.journal_dir)

    def approved(self, title):
        self.ctx.clock.advance(seconds=7)
        project_id = ss.make_approved(self.ctx, title=title)
        self.backend.calls.clear()
        return project_id

    def stuck(self, title, *, on_top=False):
        """옛 방식(main 에 곧바로 올리던 시절)으로 올리다 멈춰 COMMITTED 로 남은 글 — 새 흐름은 이 상태를 만들지 않으므로 시험이 옛 데이터를 직접 만든다(상태 + 발행 기록). on_top 이면 그 commit 이 맨 위(가짜 HEAD)다."""
        project_id = self.approved(title)
        with self.ctx.store() as store:
            project = store.load(project_id)
            rendered = project.variant("github_pages").rendered
            project.transition("github_pages", st.COMMITTED, now=self.ctx.stamp())
            store.save(project)
        header, _ = gate.split_post(rendered)
        path = post_path(header["category"], header["lang"], self.ctx.now())
        self.journal.write(PublishRecord(project_id, path, TOP if on_top else "e" * 40, "b" * 40, STAGE_COMMITTED))
        self.backend.calls.clear()
        return project_id

    def orphan_of(self, project_id):
        with self.ctx.store() as store:
            variant = store.load(project_id).variant("github_pages")
        header, _ = gate.split_post(variant.rendered)
        self.backend.orphan = CommitInfo(post_path(header["category"], header["lang"], self.ctx.now()), "c" * 40, "b" * 40)

    def results(self):
        return doctor.run_doctor(self.ctx)

    def pending(self):
        return [item for item in self.results() if item.name == "이어서 처리할 글"]

    def repo_line(self):
        return next(item for item in self.results() if item.name == "연결한 chanceblog 저장소")

    def blocked(self, project_id):
        """새 글(project_id)은 미리 보기·올리기 모두 PAGES_LOCAL_REPO_DIVERGED 로 막히고 같은 안내를 한다 → 올리기의 오류."""
        errors = []
        for call in (lambda: pages_flow.preview_publish(self.ctx, project_id), lambda: pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)):
            error = ss.code_of(call)
            self.assertEqual(error.code, "PAGES_LOCAL_REPO_DIVERGED", error.detail)
            errors.append(error)
        self.assertEqual(errors[0].detail, errors[1].detail)
        for argv in (("publish-pages", project_id), ("publish-pages", project_id, "--yes")):
            code, out, err = ss.run_cli(self.ctx, *argv)
            self.assertEqual(code, 1, argv)
            self.assertIn("PAGES_LOCAL_REPO_DIVERGED", err)
            self.assertIn(errors[0].detail.split(" — ", 1)[1][:40], err, "화면에도 같은 안내가 나온다")
        self.assertEqual((self.backend.count("commit"), self.backend.count("push"), self.backend.count("discard")), (0, 0, 0), "아무것도 올리거나 되돌리지 않았다")
        self.assertEqual(ss.status_of(self.ctx, project_id), st.APPROVED)
        return errors[-1]


class ResumeTest(FakeBase):
    def test_a_post_that_stopped_before_its_push_is_named_with_the_one_way_out(self):
        """옛 방식으로 올리다 멈춘 글 — 예전에는 '이어서 올리거나 되돌린다' 두 길이었고 새 흐름에서는 되돌리는 길 하나다(이어서 올리는 길은 없어졌다). 새 글은 이 글 때문에 막히지 않는다(만들기는 받은 원격 main 에서 시작한다)."""
        first = self.stuck("올리다 멈춘 글", on_top=True)
        self.backend.unpushed = 1
        second = self.approved("새로 올릴 글")
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, second).stage, pages_flow.STAGE_BRANCH, "올리지 않은 옛 commit 이 있어도 새 글은 막히지 않는다")
        short = first[:8]
        situation = unpushed.describe(self.ctx, self.ctx.repo_path())
        self.assertEqual((situation.kind, situation.ahead, [entry.project_id for entry in situation.entries], situation.entries[0].kind), (unpushed.RESUME, 1, [first], unpushed.KIND_COMMITTED))
        text = unpushed.action_text(situation)
        for expected in ("옛 방식으로 올리다 멈춘", "「올리다 멈춘 글」", f"번호 {short}", f"`publish-pages {short} --cancel --yes`", "이어서 올리는 길은 없어졌습니다"):
            self.assertIn(expected, text)
        self.assertNotIn(f"`publish-pages {short} --yes`", text, "이어서 올리라는 말은 없다")

    def test_a_commit_left_without_a_record_is_named_as_adoptable(self):
        """기록 직후에 멈춘 옛 commit 도 '이어받아 올리는' 길은 없어지고 되돌리는 길만 안내한다."""
        first = self.approved("기록 직후 멈춘 글")
        self.orphan_of(first)
        self.backend.unpushed = 1
        situation = unpushed.describe(self.ctx, self.ctx.repo_path())
        self.assertEqual((situation.kind, [(entry.project_id, entry.kind) for entry in situation.entries]), (unpushed.RESUME, [(first, unpushed.KIND_ADOPT)]))
        text = unpushed.action_text(situation)
        for expected in ("올리다 기록(commit) 직후에 멈춘", "이어서 올리는 길은 없어졌습니다", f"`publish-pages {first[:8]} --cancel --yes`"):
            self.assertIn(expected, text)
        self.assertNotIn(f"`publish-pages {first[:8]} --yes`", text)
        self.assertNotIn("이어받아", text)

    def test_the_doctor_gives_that_one_instruction_and_never_the_old_contradicting_sentence(self):
        first = self.stuck("올리다 멈춘 글", on_top=True)
        self.backend.unpushed = 1
        short = first[:8]
        line = self.repo_line()
        self.assertEqual((line.status, line.code), ("warn", "PAGES_LOCAL_REPO_DIVERGED"))
        self.assertIn("올리지 않은 commit 이 1개", line.message)
        self.assertIn(f"`publish-pages {short} --cancel --yes`", line.action)
        self.assertEqual(line.action, unpushed.action_text(unpushed.describe(self.ctx, self.ctx.repo_path())))
        items = self.pending()
        self.assertEqual(len(items), 1)
        self.assertIn(f"publish-pages {short} --cancel --yes", items[0].message)
        self.assertNotIn(f"publish-pages {short} --yes", items[0].message, "이어서 올리라는 말은 없다")
        self.assertEqual(items[0].action, "", "한 줄에 안내가 하나뿐이다")
        for item in self.results():
            self.assertNotIn(OLD_GENERIC, item.action + item.message)
        code, out, err = ss.run_cli(self.ctx, "doctor")
        self.assertEqual(code, 0)
        self.assertNotIn(OLD_GENERIC, out)

    def test_the_adoptable_commit_is_told_in_the_doctor_as_adoptable(self):
        first = self.approved("기록 직후 멈춘 글")
        self.orphan_of(first)
        self.backend.unpushed = 1
        items = self.pending()
        self.assertEqual(len(items), 1)
        self.assertIn("기록(commit) 직후에 멈춘 흔적", items[0].message)
        self.assertIn("이어서 올리는 길은 없어졌습니다", items[0].message)
        self.assertIn("이어서 올리는 길은 없어졌습니다", self.repo_line().action)
        self.assertNotIn(OLD_GENERIC, items[0].message + self.repo_line().action)


class OverlapTest(FakeBase):
    def two_stacked(self):
        first = self.stuck("먼저 기록한 글")
        second = self.stuck("나중에 기록한 글", on_top=True)
        self.backend.unpushed = 2
        return first, second

    def test_with_two_stacked_posts_the_instruction_names_the_later_one_first(self):
        first, second = self.two_stacked()
        situation = unpushed.describe(self.ctx, self.ctx.repo_path())
        self.assertEqual((situation.kind, situation.ahead), (unpushed.OVERLAP, 2))
        self.assertEqual(situation.entries[0].project_id, second, "맨 위(가장 나중) 글이 맨 앞")
        self.assertEqual(situation.top().project_id, second)
        text = unpushed.action_text(situation)
        self.assertIn(f"`publish-pages {second[:8]} --cancel --yes`", text)
        self.assertIn("가장 나중에 기록한 글", text)
        self.assertIn("review", text, "되돌린 글은 다시 만들어 승인해야 한다")
        self.assertLess(text.index("「나중에 기록한 글」"), text.index("「먼저 기록한 글」"))
        third = self.approved("세 번째 글")
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, third).stage, pages_flow.STAGE_BRANCH, "겹친 옛 commit 이 있어도 새 글은 막히지 않는다")

    def test_cancelling_the_earlier_post_is_refused_and_the_error_says_which_post_to_cancel_first(self):
        first, second = self.two_stacked()
        self.backend.discard_error = AppError("PAGES_LOCAL_REPO_DIVERGED", detail="되돌릴 커밋이 글 하나만 더한 것이 아니다")
        self.backend.head_has_post = True                                                      # 앞 글의 파일은 여전히 HEAD 에 있다 — 이미 되돌려진 것이 아니다
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, first, confirmed=True)
        self.assertEqual(error.code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertIn("글 하나만 더한 것이 아니다", error.detail, "원래 오류는 그대로")
        self.assertIn(f"`publish-pages {second[:8]} --cancel --yes`", error.detail, "어느 글부터인지 덧붙였다")
        self.assertEqual((ss.status_of(self.ctx, first), self.journal.read(first) is not None), (st.COMMITTED, True))

    def test_cancelling_the_later_post_first_is_what_the_instruction_says_and_it_works(self):
        first, second = self.two_stacked()
        report = pages_flow.cancel_pages_publish(self.ctx, second, confirmed=True)
        self.assertEqual((report.status, ss.status_of(self.ctx, second), self.backend.count("discard")), (st.PUBLISH_FAILED, st.PUBLISH_FAILED, 1))
        self.backend.unpushed = 1
        report = pages_flow.cancel_pages_publish(self.ctx, first, confirmed=True)
        self.assertEqual((report.status, ss.status_of(self.ctx, first), self.backend.count("discard")), (st.PUBLISH_FAILED, st.PUBLISH_FAILED, 2), "남은 글도 같은 방식으로 되돌린다")

    def test_a_post_that_is_already_online_is_not_counted_among_the_unpushed_ones(self):
        first, second = self.two_stacked()
        self.backend.unpushed = 1                                                  # 앞 글은 이미 원격에 있다(올림 기록만 남았다) — 올리지 않은 것은 맨 위 글 하나
        self.backend.remote_paths = {self.journal.read(first).path}
        situation = unpushed.describe(self.ctx, self.ctx.repo_path())
        self.assertEqual((situation.kind, [entry.project_id for entry in situation.entries]), (unpushed.RESUME, [second]))

    def test_the_doctor_says_which_post_to_undo_first_and_which_has_to_wait(self):
        first, second = self.two_stacked()
        line = self.repo_line()
        self.assertIn("올리지 않은 commit 이 2개", line.message)
        self.assertIn(f"`publish-pages {second[:8]} --cancel --yes`", line.action)
        items = {item.message.split(" — ")[0]: item for item in self.pending()}
        self.assertEqual(sorted(items), ["나중에 기록한 글", "먼저 기록한 글"])
        top, under = items["나중에 기록한 글"], items["먼저 기록한 글"]
        self.assertIn("맨 위(가장 나중)", top.message)
        self.assertIn(f"publish-pages {second[:8]} --cancel --yes", top.message)
        self.assertIn("위에 다른 글의 기록이 쌓여", under.message)
        self.assertIn(f"publish-pages {first[:8]} --cancel --yes", under.message)
        self.assertNotIn(f"publish-pages {first[:8]} --yes", under.message, "이어서 올리라는 말은 없다")
        for item in self.results():
            self.assertNotIn(OLD_GENERIC, item.action + item.message)
            self.assertNotIn("이어받아", item.action, "겹친 글은 바로 이어받을 수 없다")


class NotMadeByTheAppTest(FakeBase):
    def test_a_commit_the_app_did_not_make_says_to_look_at_it_by_hand_and_never_offers_to_adopt_or_undo_it(self):
        self.backend.unpushed = 1
        second = self.approved("새로 올릴 글")
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, second).stage, pages_flow.STAGE_BRANCH, "사람이 만든 commit 이 있어도 새 글은 막히지 않는다(객체로만 만들어 그 commit 을 건드리지 않는다)")
        text = unpushed.action_text(unpushed.describe(self.ctx, self.ctx.repo_path()))
        for expected in ("앱이 만든 글 기록이 아닌 commit 1개", "git log origin/main..HEAD", "지우거나 되돌리지 않습니다"):
            self.assertIn(expected, text)
        self.assertNotIn("이어받아", text)
        self.assertNotIn("--cancel", text)
        line = self.repo_line()
        self.assertEqual((line.status, line.code), ("warn", "PAGES_LOCAL_REPO_DIVERGED"))
        self.assertIn("git log origin/main..HEAD", line.action)
        self.assertEqual(self.pending(), [])
        self.assertEqual(unpushed.describe(self.ctx, self.ctx.repo_path()).kind, unpushed.UNKNOWN)

    def test_a_known_record_together_with_a_commit_the_app_did_not_make_is_called_mixed(self):
        first = self.stuck("올리다 멈춘 글")
        self.backend.unpushed = 2
        situation = unpushed.describe(self.ctx, self.ctx.repo_path())
        self.assertEqual((situation.kind, situation.ahead, len(situation.entries)), (unpushed.MIXED, 2, 1))
        text = unpushed.action_text(situation)
        for expected in ("앱이 만든 것이 아닙니다", "git log origin/main..HEAD", "「올리다 멈춘 글」", "지우거나 되돌리지 않습니다"):
            self.assertIn(expected, text)
        for forbidden in ("이어받아", "--cancel"):
            self.assertNotIn(forbidden, text, "앱이 만든 것이 아닌 commit 이 섞여 있으면 이어받거나 되돌린다고 하지 않는다")
        self.assertEqual(self.repo_line().action, text)
        for item in self.pending():
            self.assertNotIn("이어받아", item.message)
            self.assertIn("앱이 만든 것이 아닌 commit", item.message)
        second = self.approved("새로 올릴 글")
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, second).stage, pages_flow.STAGE_BRANCH, "섞여 있어도 새 글은 막히지 않는다")

    def test_a_store_that_cannot_be_read_does_not_break_the_analysis(self):
        self.backend.unpushed = 1
        with mock.patch.object(unpushed, "list_projects", side_effect=AppError("STORE_CORRUPT", {"파일": "x.db"})):
            situation = unpushed.describe(self.ctx, self.ctx.repo_path())
        self.assertEqual((situation.kind, situation.ahead, situation.entries), (unpushed.UNKNOWN, 1, ()), "앱이 아는 기록이 없는 것으로 본다")

    def test_the_kind_is_decided_only_by_the_number_of_commits_and_the_number_of_known_records(self):
        one, two = unpushed.Entry("a" * 32, "하나", unpushed.KIND_COMMITTED, True), unpushed.Entry("b" * 32, "둘", unpushed.KIND_COMMITTED, False)
        for ahead, entries, kind in ((0, (), ""), (1, (), unpushed.UNKNOWN), (2, (), unpushed.UNKNOWN), (1, (one,), unpushed.RESUME), (2, (one,), unpushed.MIXED), (3, (one,), unpushed.MIXED),
                                     (2, (one, two), unpushed.OVERLAP), (1, (one, two), unpushed.OVERLAP), (3, (one, two), unpushed.MIXED)):
            with self.subTest(ahead=ahead, known=len(entries)):
                self.assertEqual(unpushed.Situation(ahead, entries).kind, kind)
        self.assertEqual(unpushed.action_text(unpushed.Situation(0, ())), "")

    def test_nothing_unpushed_means_no_instruction_and_no_block(self):
        situation = unpushed.describe(self.ctx, self.ctx.repo_path())
        self.assertEqual((situation.ahead, situation.kind, unpushed.action_text(situation)), (0, "", ""))
        self.assertEqual(self.repo_line().status, "ok")
        second = self.approved("새로 올릴 글")
        self.assertTrue(pages_flow.preview_publish(self.ctx, second).dry_run)

    def test_when_git_cannot_say_how_many_commits_are_ahead_nothing_is_claimed(self):
        self.backend.unpushed = None
        self.assertEqual(unpushed.describe(self.ctx, self.ctx.repo_path()).ahead, 0)
        self.assertEqual(self.repo_line().status, "ok")



LONG_TITLE = ("에너지 절약과 난방비 줄이기를 위한 겨울철 생활 습관 정리 " * 4)[:190]        # 독립 검증 3차가 재현한 약 190자 제목


class LongTitleTest(FakeBase):
    """독립 검증 3차 낮음 5: 긴 제목(약 190자) 글이 겹치면 안내가 제목에 밀려 오류 화면의 '세부'(700자)에서 `--cancel --yes` 명령이 잘렸다(doctor 에는 전체가 있었다).
    안내에 쓰는 제목을 30자로 줄이고(번호가 함께 나간다) 이름을 보이는 글은 셋까지로 해서 어떤 제목 길이·글 수에서도 명령 전체가 화면에 보인다."""

    def overlapped(self, count=2):
        """긴 제목의 글 count 개를 겹쳐 쌓는다(맨 위 글이 마지막) → 글 번호들(아래부터)."""
        ids = [self.stuck(f"{LONG_TITLE} {n}", on_top=n == count - 1) for n in range(count)]
        self.backend.unpushed = count
        return ids

    def detail_line(self, out, err):
        text = out + err
        return next(line for line in text.splitlines() if line.strip().startswith("세부:"))

    def test_a_title_is_shortened_to_thirty_characters_with_an_ellipsis(self):
        self.assertEqual(unpushed.shown_title("짧은 제목"), "짧은 제목")
        exactly = "가" * unpushed.MAX_TITLE_SHOWN
        self.assertEqual(unpushed.shown_title(exactly), exactly, "정확히 30자는 그대로")
        longer = unpushed.shown_title(exactly + "나")
        self.assertEqual((len(longer), longer[-1]), (unpushed.MAX_TITLE_SHOWN, "…"))
        self.assertEqual(unpushed.shown_title("줄바꿈이\n\n  섞인   제목"), "줄바꿈이 섞인 제목")
        self.assertLessEqual(len(unpushed.shown_title(LONG_TITLE)), unpushed.MAX_TITLE_SHOWN)
        self.assertEqual(unpushed.shown_title(""), "")

    def test_the_names_in_the_advice_are_short_and_at_most_three_are_named(self):
        ids = self.overlapped(5)
        situation = unpushed.describe(self.ctx, self.ctx.repo_path())
        self.assertEqual((situation.kind, len(situation.entries)), (unpushed.OVERLAP, 5))
        for entry in situation.entries:
            self.assertLessEqual(len(entry.title), unpushed.MAX_TITLE_SHOWN)
        text = unpushed.action_text(situation)
        self.assertEqual(text.count("「"), 4, "나열한 글 셋과 맨 위 글 하나뿐이다")
        self.assertIn("외 2개", text)
        self.assertIn(f"`publish-pages {ids[-1][:8]} --cancel --yes`", text)

    def test_the_cancel_command_is_whole_on_the_screen_for_a_new_post_a_lower_post_a_cancel_and_the_doctor(self):
        first, second = self.overlapped(2)
        door = f"`publish-pages {second[:8]} --cancel --yes`"
        for label, argv in (("아래 글 되돌리기", ("publish-pages", first, "--cancel", "--yes")),):
            with self.subTest(command=label):
                self.backend.discard_error = AppError("PAGES_LOCAL_REPO_DIVERGED", detail="되돌릴 커밋이 글 하나만 더한 것이 아니다")
                self.backend.head_has_post = True                                         # 글이 아직 HEAD 에 있어서 '이미 되돌려졌다' 로 보지 않는다
                code, out, err = ss.run_cli(self.ctx, *argv)
                self.assertEqual(code, 1, err)
                line = self.detail_line(out, err)
                self.assertLessEqual(len(line.split("세부:", 1)[1].strip()), 700)
                self.assertIn(door, line, "화면에 보이는 세부 안에 명령 전체가 있다")
        self.backend.discard_error = None
        code, out, err = ss.run_cli(self.ctx, "doctor")
        self.assertIn(door, out)

    def test_an_adoptable_post_with_a_long_title_is_named_short_too(self):
        """기록 직후에 멈춘 옛 commit 의 글 이름도 줄인 제목을 쓴다(되돌리는 명령만 안내한다)."""
        project_id = self.approved(f"이어받을 글 {LONG_TITLE}")
        self.orphan_of(project_id)
        self.backend.unpushed = 1
        situation = unpushed.describe(self.ctx, self.ctx.repo_path())
        entry = situation.entries[0]
        self.assertEqual((situation.kind, entry.kind), (unpushed.RESUME, unpushed.KIND_ADOPT))
        self.assertLessEqual(len(entry.title), unpushed.MAX_TITLE_SHOWN)
        text = unpushed.action_text(situation)
        self.assertIn(f"「{entry.title}」(번호 {entry.short})", text)
        self.assertNotIn(LONG_TITLE[:60], text)
        self.assertIn(f"`publish-pages {entry.short} --cancel --yes`", text)

    def test_a_short_title_is_shown_whole_so_the_old_advice_is_unchanged(self):
        self.stuck("올리다 멈춘 글")
        self.backend.unpushed = 1
        self.assertIn("「올리다 멈춘 글」(번호 ", unpushed.action_text(unpushed.describe(self.ctx, self.ctx.repo_path())))


class OtherDataFolderTest(FakeBase):
    """독립 검증 3차 낮음 4: `--data-dir` 을 다르게 준 다른 앱이 올리다 멈춘 글(앱이 만든 모양인데 이 데이터 폴더에는 기록이 없는 commit)을 '앱이 만든 것이 아닙니다' 라고 안내하던 것을 바로잡는다 —
    앱이 만든 모양의 commit 이 기록 없이 있으면 다른 데이터 폴더의 앱이 올리다 멈춘 글일 수 있다고 말하고(그 앱에서 맨 위 commit 의 글부터 `--cancel --yes`), 직접 만든 commit 이 섞였으면 그것도 따로 말한다.
    맨 위 commit 이 이 데이터 폴더의 글이면 '올릴 수는 없지만 되돌릴 수는 있다' 고 정확히 말한다(예전에는 위에 다른 commit 이 있어 되돌릴 수 없다고 했다)."""

    def situation(self, ahead, made):
        self.backend.unpushed, self.backend.made_by_app = ahead, made
        return unpushed.describe(self.ctx, self.ctx.repo_path())

    def test_the_number_of_commits_that_look_like_the_apps_but_have_no_record_here_is_counted_without_going_over(self):
        self.stuck("이 데이터 폴더의 글")
        for ahead, made, foreign in ((2, 1, 0), (2, 2, 1), (2, 3, 1), (3, 2, 1), (3, 3, 2), (3, 1, 0), (3, 0, 0)):
            with self.subTest(ahead=ahead, made=made):
                situation = self.situation(ahead, made)
                self.assertEqual((situation.kind, situation.foreign), (unpushed.MIXED, foreign))
        self.assertEqual(unpushed.describe(self.ctx, self.ctx.repo_path()).kind, unpushed.MIXED)

    def test_without_any_commit_that_looks_like_the_apps_the_old_wording_stays_exactly(self):
        self.stuck("올리다 멈춘 글")
        text = unpushed.action_text(self.situation(2, 1))
        self.assertIn("나머지는 앱이 만든 것이 아닙니다", text)
        self.assertNotIn("--data-dir", text)
        self.assertEqual(unpushed.action_text(self.situation(0, 0)), "")

    def test_an_app_shaped_commit_without_a_record_is_not_called_hand_made_and_the_way_out_is_the_other_app(self):
        self.stuck("이 데이터 폴더의 글")
        situation = self.situation(2, 2)
        text = unpushed.action_text(situation)
        for expected in ("이 데이터 폴더에 기록이 있는 글은 1개", "앱이 만든 모양(제목이 '글 올리기(데스크톱 앱):')인데 이 데이터 폴더에는 그 글의 기록이 없습니다", "`--data-dir`", "CHANCEBLOG_DESKTOP_DATA",
                         "`doctor`", "`publish-pages 글번호 --cancel --yes`", "다른 데이터 폴더의 글 기록을 지우거나 되돌리지 않습니다", "맨 위(가장 나중) commit 은 이 데이터 폴더의 글이 아니라"):
            self.assertIn(expected, text)
        self.assertNotIn("나머지는 앱이 만든 것이 아닙니다", text, "앱이 만든 모양인 commit 을 '앱이 만든 것이 아니다' 라고 하지 않는다")
        self.assertNotIn("그 밖의 commit", text, "직접 만든 commit 은 없다")
        self.assertEqual(self.repo_line().action, text, "doctor 가 같은 말을 한다")
        self.assertEqual(pages_flow.plan_pages_publish(self.ctx, self.approved("새로 올릴 글")).stage, pages_flow.STAGE_BRANCH, "다른 앱의 옛 commit 이 있어도 새 글은 막히지 않는다")

    def test_a_hand_made_commit_next_to_an_app_shaped_one_is_told_separately(self):
        self.stuck("이 데이터 폴더의 글")
        text = unpushed.action_text(self.situation(3, 2))
        self.assertIn("나머지 2개 중 1개는 앱이 만든 모양", text)
        self.assertIn("그 밖의 commit 1개는 앱이 만든 것이 아니라 앱이 지우거나 되돌리지 않습니다", text)
        self.assertIn("git log origin/main..HEAD", text)

    def test_when_the_top_commit_is_this_data_folders_post_the_advice_says_it_can_be_undone(self):
        first = self.stuck("이 데이터 폴더의 글", on_top=True)
        situation = self.situation(2, 2)
        self.assertEqual((situation.top().project_id, situation.foreign), (first, 1))
        text = unpushed.action_text(situation)
        self.assertIn(f"맨 위(가장 나중) commit 이 이 데이터 폴더의 글 「이 데이터 폴더의 글」(번호 {first[:8]})이라 `publish-pages {first[:8]} --cancel --yes` 로 되돌릴 수 있습니다", text)
        line = self.pending()[0]
        self.assertIn("이 글의 기록이 맨 위(가장 나중)이고 그 아래에", line.message)
        self.assertIn(f"`publish-pages {first[:8]} --cancel --yes`", line.message)
        self.assertIn("올릴 수 없습니다", line.message)
        self.assertIn("다른 앱이 같은 저장소에 올리다 멈춘 글일 수 있습니다", line.message)
        self.assertNotIn("이 글의 기록 위에", line.message, "맨 위 글에 '기록 위에 다른 commit 이 있다' 고 하지 않는다")

    def test_a_post_that_is_not_on_top_is_told_that_another_commit_is_above_it(self):
        first = self.stuck("이 데이터 폴더의 글")
        self.situation(2, 2)
        line = self.pending()[0]
        self.assertIn("이 글의 기록 위에 다른 commit 이 있어 지금은 올리거나 되돌릴 수 없습니다", line.message)
        self.assertIn("다른 앱이 같은 저장소에 올리다 멈춘 글일 수 있습니다", line.message)
        self.assertNotIn("이 글의 기록이 맨 위", line.message)
        self.assertIn(f"`publish-pages {first[:8]} --cancel --yes`", line.message)
        self.assertNotIn(f"`publish-pages {first[:8]} --yes`", line.message, "이어서 올리라는 말은 없다")

    def test_a_hand_made_commit_below_the_top_post_also_says_it_can_be_undone_but_not_pushed(self):
        first = self.stuck("이 데이터 폴더의 글", on_top=True)
        self.situation(2, 1)                                                               # 앱이 만든 모양은 이 글 하나뿐 — 아래 commit 은 직접 만든 것
        line = self.pending()[0]
        self.assertIn("이 글의 기록이 맨 위(가장 나중)이고 그 아래에", line.message)
        self.assertIn(f"`publish-pages {first[:8]} --cancel --yes`", line.message)
        self.assertIn("앱이 만든 것이 아니라 앱이 지우거나 되돌리지 않습니다", line.message)
        self.assertNotIn("--data-dir", line.message)

    def test_unknown_commits_that_look_like_the_apps_are_told_the_same_way(self):
        self.backend.unpushed, self.backend.made_by_app = 2, 1
        situation = unpushed.describe(self.ctx, self.ctx.repo_path())
        self.assertEqual((situation.kind, situation.foreign), (unpushed.UNKNOWN, 1))
        text = unpushed.action_text(situation)
        for expected in ("이 데이터 폴더에 기록이 없는 올리지 않은 commit 2개", "그중 1개는 앱이 만든 모양", "`--data-dir`", "그 밖의 commit 1개는 앱이 만든 것이 아니라"):
            self.assertIn(expected, text)
        self.assertNotIn("앱이 만든 글 기록이 아닌 commit", text)
        self.backend.made_by_app = 0
        self.assertIn("앱이 만든 글 기록이 아닌 commit 2개", unpushed.action_text(unpushed.describe(self.ctx, self.ctx.repo_path())), "앱이 만든 모양이 없으면 예전 안내 그대로")

    def test_when_the_subjects_cannot_be_read_the_old_advice_is_given(self):
        self.stuck("이 데이터 폴더의 글")
        self.backend.unpushed = 2
        with mock.patch.object(self.backend, "unpushed_made_by_app", side_effect=AppError("GIT_PUSH_NETWORK")):
            situation = unpushed.describe(self.ctx, self.ctx.repo_path())
        self.assertEqual((situation.kind, situation.foreign), (unpushed.MIXED, 0))
        self.assertNotIn("--data-dir", unpushed.action_text(situation))

    def test_nothing_is_asked_when_every_commit_is_explained_by_a_record_here(self):
        self.stuck("올리다 멈춘 글")
        self.backend.calls.clear()
        self.backend.unpushed = 1
        self.assertEqual(unpushed.describe(self.ctx, self.ctx.repo_path()).foreign, 0)
        self.assertNotIn("unpushed_made_by_app", self.backend.names(), "설명되지 않는 commit 이 없으면 제목을 읽지도 않는다")


class AlreadyPushedTest(FakeBase):
    def test_cancelling_a_post_whose_commit_is_already_online_is_refused_with_its_own_code_and_the_same_command_finishes_it(self):
        """옛 방식으로 올라가 버린 글(상태는 COMMITTED) — 되돌리지 않고 전용 오류로 거절한다. 이어서 마치는 길은 없어졌으므로 안내는 '이 글은 앱이 되돌리지 않는다 — 글은 저장소에서 확인하고 이 글의 기록만 `delete` 로 지울 수 있다'."""
        project_id = self.stuck("올라가 버린 글")
        self.backend.discard_error = AppError("UNEXPECTED_ERROR", detail="이미 원격 main 에 올라간 커밋이라 되돌리지 않는다")
        self.backend.remote_has_post = True
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True)
        self.assertEqual(error.code, "PUBLISH_ALREADY_PUSHED")
        self.assertIn(f"delete {project_id[:8]} --yes", error.detail)
        shown = error.rendered()
        self.assertIn("이미 공개 저장소에 올라간 글", shown.message)
        self.assertIn("되돌리지", shown.message)
        self.assertEqual((ss.status_of(self.ctx, project_id), self.journal.read(project_id) is not None), (st.COMMITTED, True), "아무것도 바꾸지 않았다")
        code, out, err = ss.run_cli(self.ctx, "publish-pages", project_id, "--cancel", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("PUBLISH_ALREADY_PUSHED", err)
        for word in ("UNEXPECTED_ERROR", "로그 내보내기"):
            self.assertNotIn(word, err)
        error = ss.code_of(pages_flow.run_pages_publish, self.ctx, project_id, confirmed=True)
        self.assertEqual(error.code, "STATUS_TRANSITION_INVALID", "이어서 올리는 길은 없어졌다")

    def test_an_unexpected_refusal_stays_unexpected_when_the_post_is_not_online(self):
        project_id = self.stuck("그대로 오류")
        self.backend.discard_error = AppError("UNEXPECTED_ERROR", detail="알 수 없음")
        self.backend.remote_has_post = False
        self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True).code, "UNEXPECTED_ERROR")

    def test_the_doctor_says_it_is_already_online_and_to_finish_it_not_to_cancel_it(self):
        project_id = self.stuck("올라가 버린 글")
        self.backend.remote_has_post = True
        self.assertEqual(self.repo_line().status, "ok", "올리지 않은 commit 이 아니다")
        items = self.pending()
        self.assertEqual(len(items), 1)
        self.assertIn("옛 방식으로 올리다 멈춘 글이 이미 원격 main 에 올라가 있습니다", items[0].message)
        self.assertIn(f"delete {project_id[:8]} --yes", items[0].message)
        self.assertNotIn("--cancel", items[0].message)
        self.assertEqual(items[0].action, "")

    def test_an_already_pushed_or_public_post_cannot_be_cancelled_and_says_what_to_do(self):
        from chanceblog_desktop.publish.pages import MainCheck
        pushed = self.approved("올림 상태 글")
        pages_flow.run_pages_publish(self.ctx, pushed, confirmed=True)
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, pushed, confirmed=True)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.MERGE_PENDING), "병합 기다리는 글은 `abandon` 으로 정리한다")
        self.assertIn(f"abandon {pushed[:8]} --yes", error.detail)
        self.backend.merge_results = [MainCheck("merged", commit="d" * 40)]
        pages_flow.merge_check_pages(self.ctx, pushed)
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, pushed, confirmed=True)
        self.assertEqual(error.code, "PUBLISH_ALREADY_PUSHED")
        self.assertIn(f"check-deploy {pushed[:8]}", error.detail)
        self.assertEqual(self.backend.count("discard"), 0)
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, pushed).status, st.PUBLISHED)
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, pushed, confirmed=True)
        self.assertEqual(error.code, "PUBLISH_ALREADY_PUSHED")
        self.assertIn("이미 공개된", error.detail)


class CancelUnrecordedTest(FakeBase):
    """기록 직후에 멈춰 이 글의 commit 이 기록 없이 남은 승인된 글 — `--cancel --yes` 가 그것만 되돌린다(빠른 시험: 진짜 git 시험은 test_service_recovery)."""

    def test_the_orphan_is_undone_the_post_is_marked_cancelled_and_an_old_record_is_cleaned(self):
        project_id = self.approved("기록 직후 멈춘 글")
        self.orphan_of(project_id)
        self.backend.unpushed = 1
        self.journal.write(PublishRecord(project_id, ss.KO_PATH, "d" * 40, "b" * 40, STAGE_COMMITTED))
        report = pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual(report.status, st.PUBLISH_FAILED)
        self.assertEqual(ss.status_of(self.ctx, project_id), st.PUBLISH_FAILED)
        self.assertEqual(ss.projects.show_project(self.ctx, project_id).variant("github_pages").error_code, "PUBLISH_CANCELLED")
        self.assertEqual([call for call in self.backend.calls if call[0] == "discard"], [("discard", self.backend.orphan.path, "c" * 40)])
        self.assertIsNone(self.journal.read(project_id), "남은 낡은 기록도 같이 치웠다")
        self.assertTrue(any("멈춰 남은 이 글의 commit" in step for step in report.steps), report.steps)

    def test_an_approved_post_without_such_a_commit_is_refused_and_nothing_is_undone(self):
        project_id = self.approved("그냥 승인된 글")
        error = ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True)
        self.assertEqual((error.code, error.slots["현재 상태"]), ("STATUS_TRANSITION_INVALID", st.APPROVED))
        self.assertEqual((self.backend.count("discard"), ss.status_of(self.ctx, project_id)), (0, st.APPROVED))

    def test_a_record_that_cannot_be_read_does_not_stop_the_cancel_after_the_commit_was_already_undone(self):
        project_id = self.approved("기록 직후 멈춘 글")
        self.orphan_of(project_id)
        self.backend.unpushed = 1
        broken = self.ctx.workspace.journal_dir / f"{project_id}.json"
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_text("{깨짐", encoding="utf-8")
        report = pages_flow.cancel_pages_publish(self.ctx, project_id, confirmed=True)
        self.assertEqual((report.status, ss.status_of(self.ctx, project_id)), (st.PUBLISH_FAILED, st.PUBLISH_FAILED))
        self.assertEqual(self.backend.count("discard"), 1)
        self.assertEqual(broken.read_text(encoding="utf-8"), "{깨짐", "읽을 수 없는 기록은 건드리지 않았다")
        self.assertTrue(any("읽을 수 없는 발행 기록 파일은 그대로 두었습니다" in step for step in report.steps), report.steps)

    def test_a_refusal_of_the_undo_leaves_the_post_as_it_was(self):
        project_id = self.approved("기록 직후 멈춘 글")
        self.orphan_of(project_id)
        self.backend.unpushed = 1
        self.backend.discard_error = AppError("PAGES_LOCAL_REPO_DIVERGED", detail="지금 HEAD 가 되돌릴 글 커밋이 아니다")
        self.backend.head_has_post = True
        self.assertEqual(ss.code_of(pages_flow.cancel_pages_publish, self.ctx, project_id, confirmed=True).code, "PAGES_LOCAL_REPO_DIVERGED")
        self.assertEqual(ss.status_of(self.ctx, project_id), st.APPROVED, "되돌리지 못했으면 상태도 그대로다")


class LeftoverRecordTest(FakeBase):
    def publish_fully(self, title="공개될 글"):
        """새 흐름의 끝까지 — 새 가지에 올리고(MERGE_PENDING) 병합을 확인하고(PUSHED) 공개 확인(PUBLISHED)."""
        from chanceblog_desktop.publish.pages import MainCheck
        project_id = self.approved(title)
        self.assertEqual(pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True).status, st.MERGE_PENDING)
        self.backend.merge_results = [MainCheck("merged", commit="d" * 40)]
        self.assertEqual(pages_flow.merge_check_pages(self.ctx, project_id).status, st.PUSHED)
        self.assertEqual(pages_flow.check_pages_deploy(self.ctx, project_id).status, st.PUBLISHED)
        return project_id

    def leave_the_record_like_a_crash_before_it_was_removed(self, project_id):
        self.journal.write(PublishRecord(project_id, ss.KO_PATH, "d" * 40, "b" * 40, STAGE_PUSHED))

    def test_a_record_left_on_a_public_post_is_harmless_and_the_doctor_says_it_can_be_cleaned(self):
        project_id = self.publish_fully()
        self.assertIsNone(self.journal.read(project_id))
        self.leave_the_record_like_a_crash_before_it_was_removed(project_id)
        items = [item for item in self.results() if item.name == "남은 발행 기록"]
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0].status, items[0].code), ("warn", ""))
        self.assertIn("해롭지 않습니다", items[0].message)
        self.assertIn(f"check-deploy {project_id[:8]}", items[0].message)
        code, out, err = ss.run_cli(self.ctx, "doctor")
        self.assertEqual(code, 0, "주의일 뿐 실패가 아니다")
        self.assertIsNotNone(self.journal.read(project_id), "doctor 는 읽기만 한다 — 지우지 않았다")

    def test_check_deploy_and_publish_clean_only_that_posts_own_record(self):
        project_id = self.publish_fully()
        other = self.approved("다른 글")
        for runner in (lambda: pages_flow.check_pages_deploy(self.ctx, project_id), lambda: pages_flow.run_pages_publish(self.ctx, project_id, confirmed=True)):    # 둘 다 공개된 글에 남은 그 글의 기록만 정리한다
            self.leave_the_record_like_a_crash_before_it_was_removed(project_id)
            self.journal.write(PublishRecord(other, ss.KO_PATH, "e" * 40, "b" * 40, STAGE_PUSHED))            # 다른 글의 기록(이 글의 일이 아니다)
            report = runner()
            self.assertEqual(report.status, st.PUBLISHED)
            self.assertTrue(any("정리했습니다" in note for note in report.notes), report.notes)
            self.assertIsNone(self.journal.read(project_id), "공개된 글에 남은 기록은 지웠다")
            self.assertIsNotNone(self.journal.read(other), "다른 글의 기록은 그대로다")
            self.journal.remove(other)
        self.assertEqual([item for item in self.results() if item.name == "남은 발행 기록"], [])
        self.assertEqual((self.backend.count("build_branch_commit"), self.backend.count("push_branch")), (0, 0), "정리하려고 다시 만들거나 올리지는 않았다")

    def test_a_record_that_cannot_be_read_is_not_touched(self):
        project_id = self.publish_fully()
        broken = self.ctx.workspace.journal_dir / f"{project_id}.json"
        broken.write_text("{깨짐", encoding="utf-8")
        report = pages_flow.check_pages_deploy(self.ctx, project_id)
        self.assertEqual(report.status, st.PUBLISHED)
        self.assertEqual(broken.read_text(encoding="utf-8"), "{깨짐")
        self.assertFalse(any("정리했습니다" in note for note in report.notes))
        self.assertEqual([item for item in self.results() if item.name == "남은 발행 기록"], [], "읽을 수 없는 기록은 '정리해도 된다' 고 하지 않는다")

    def test_a_clean_public_post_has_nothing_to_clean_and_no_note(self):
        project_id = self.publish_fully()
        report = pages_flow.check_pages_deploy(self.ctx, project_id)
        self.assertEqual(report.status, st.PUBLISHED)
        self.assertFalse(any("정리" in note for note in report.notes))


# ---- 진짜 git: 안내대로 하면 실제로 두 글이 모두 올라간다 -------------------------------------------------------------------------------------
@unittest.skipUnless(ss.HAVE_GIT, "git 이 필요하다")
class RealGit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = ss.GitSandbox()
        cls.addClassCleanup(cls.box.cleanup)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.origin, self.work = self.box.copy_into(self.tmp)
        self.spy = ss.Spy()
        self.backend = GitPagesBackend(git=self.spy, expected_origin=ss.LOCAL_ORIGIN, fetcher=ss.FakeWorld().fetcher)
        self.ctx = ss.make_ctx(self.tmp, backend=self.backend, repo=None, git=self.spy)
        self.ctx.expected_origin = ss.LOCAL_ORIGIN
        self.ctx.settings.save_repo_path(str(self.work))
        self.journal = Journal(self.ctx.workspace.journal_dir)
        self.base = ss.git(self.work, "rev-parse", "HEAD")

    def approved(self, title):
        self.ctx.clock.advance(seconds=7)
        return ss.make_approved(self.ctx, title=title)

    def rendering(self, project_id):
        with self.ctx.store() as store:
            return store.load(project_id).variant("github_pages").rendered

    def stuck(self, title):
        project_id = self.approved(title)
        self.spy.fail = {"push"}
        try:
            self.assertEqual(ss.code_of(pages_flow.run_pages_publish, self.ctx, project_id, confirmed=True, wait=False).code, "GIT_PUSH_NETWORK")
        finally:
            self.spy.fail = set()
        return project_id

    def stack_on_top(self, project_id):
        """앞 글의 commit 위에 이 글의 commit 을 쌓고 COMMITTED 로 기록한다 — 서로 다른 두 글을 동시에 올려 둘 다 commit 만 했던 때의 모양(독립 검증이 재현)."""
        text = self.rendering(project_id)
        header, _body = gate.split_post(text)
        self.ctx.clock.advance(seconds=7)
        path = post_path(header["category"], header["lang"], self.ctx.now())
        target = self.work / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        ss.git(self.work, "add", "--", path)
        ss.git(self.work, "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "글 올리기(데스크톱 앱): 쌓인 글")
        info = CommitInfo(path, ss.git(self.work, "rev-parse", "HEAD"), ss.git(self.work, "rev-parse", "HEAD^"))
        pages_flow._record_committed(self.ctx, self.work, self.journal, project_id, PagesPost(path, text, header["category"], header["lang"]), info, undo_on_failure=False)
        self.assertEqual(ss.status_of(self.ctx, project_id), st.COMMITTED)

    def head(self):
        return ss.git(self.work, "rev-parse", "HEAD")



def setUpModule():
    ss.external_write_on()                                   # 이 시험은 게시 흐름을 쓴다 — 외부 Write 관문을 임시로만 연다(소스 상수는 False — PCSEC1 H3)


def tearDownModule():
    ss.external_write_off()


if __name__ == "__main__":
    unittest.main()
