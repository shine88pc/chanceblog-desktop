"""전체 백업·복원(BACKUPUI)과 저장한 초안(LOCALSAVE)이 같은 `chanceblog.db` 에서 만나는 곳의 시험 — 두 묶음을 합친 트리에서만 뜻이 있다(결정 D-375).

저장한 초안은 글 보관함의 `drafts` 표에 `dd-` 번호의 한 행으로 들어가고, 글칸은 `ensure_ascii` JSON 한 줄이다(줄바꿈·탭·한글이 `\\n`·`\\t`·`\\uXXXX` 로 이스케이프된다). 날것으로 훑으면 줄 맨 앞·탭 뒤·한글 바로 뒤에 붙은
토큰 글자(앞에 `key=` 같은 이름표가 없는 모양)가 앞 글자와 붙어 보여 놓친다(이 시험이 직접 재서 확인한다) — 백업의 훑기는 JSON 을 풀어 글 하나씩 훑으므로(`backup_flow._scan_cell`) 모두 찾아야 한다.

지키는 것:
  1) 저장한 초안에 키·토큰 모양이 있으면 — 여섯 종류 x 다섯 자리(공백 뒤·줄 처음·탭 뒤·한글 뒤 붙여·글 맨 앞)를 이름표가 붙은 한 줄과 토큰 글자만의 두 모양으로(55조합) 모두 — 전체 백업이 멈춘다(`FULL_BACKUP_BLOCKED`). 위치는 '글 보관함 · 저장한 초안' 으로 시작하고 유형만 알리며
     키 글자가 오류 어디에도 없고, 폴더·잠금이 남지 않고, 지금 데이터는 한 바이트도 바뀌지 않는다. 기록 자체는 올바른 모양이다(앱의 `load_draft` 가 읽는다 — 옛 데이터·손으로 고친 파일을 흉내 낸 것).
  2) 정상인 저장한 초안(고른 제목·본문의 CRLF·NBSP·이모지·결합 글자·키워드·태그·선택 입력·만든 초안 포함)은 백업에 한 글자도 안 바뀐 채 담기고, 되돌린 뒤에도 같다: 백업 안의 `drafts` 행이 지금과 같고,
     복원 뒤 `load_draft` 가 같은 기록을 돌려주고 목록이 같으며(백업 뒤에 고친 것은 되돌아가고 백업 뒤에 만든 것은 사라진다), 복원 직전 안전 사본에는 백업 뒤의 상태가 그대로 남고, 같은 초안을 이어 저장하면 저장 횟수가 이어진다.
  3) 되돌리는 쪽도 같다: 백업 폴더 안의 저장한 초안에 키·토큰 모양이 들어 있으면(손으로 고친 백업) 쓰지 않고 앱이 고칠 수 없다고 말하며, 지금 데이터는 한 바이트도 안 바뀌고 안전 사본도 시작하지 않는다.
네트워크·실제 비밀·실제 자격 증명 관리자 없이 돈다. 키 모양은 `scan_samples` 가 실행할 때 조각을 이어 붙여 만든다(소스에 완성된 키가 없다).
"""
import contextlib
import dataclasses
import hashlib
import json
import pickle
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_support as bs  # noqa: E402

from chanceblog_desktop.content import saved_draft as sd  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security import scan  # noqa: E402
from chanceblog_desktop.service import backup_flow as bf  # noqa: E402
from chanceblog_desktop.service import draft_store  # noqa: E402

S = bs.S
KINDS = bs.KINDS
EMOJI = chr(0x1F600)
NFD = "e" + chr(0x0301)
NBSP = chr(0x00A0)
PLACEMENTS = (("공백 뒤", lambda line: "앞 " + line + " 뒤"), ("줄 처음", lambda line: "첫 줄\n" + line + "\n끝"), ("탭 뒤", lambda line: "앞\t" + line),
              ("한글 뒤 붙여", lambda line: "한글" + line), ("글 맨 앞", lambda line: line + " 뒤"))
JSON_SENSITIVE = ("줄 처음", "탭 뒤", "한글 뒤 붙여")                 # 이스케이프된 날것으로는 놓치는 자리


def forms(kind):
    """한 종류의 시험 입력들 → `[(모양 이름, 글, 오류에 새면 안 되는 토큰 글자)]` — 이름표가 붙은 한 줄(`key=…`)과, 토큰 글자만 둬도 키 모양이면 토큰 글자만(이름표가 없어 줄 처음·탭 뒤·한글 뒤에서 날것 훑기가 놓치는 입력).
    Bearer 토큰은 낱말 `Bearer` 와 함께일 때만 키 모양이라 한 줄 하나뿐이다."""
    token, line = S.sample(kind)
    found = [("한 줄", line, token)]
    if scan.scan_secrets(token, "x"):
        found.append(("토큰만", token, token))
    return found


def shape(kind):
    """키 모양 글 하나 — 가능하면 토큰 글자만, 아니면 한 줄."""
    return forms(kind)[-1][1]


def save_clean(ctx, title="정상 제목", body="정상 본문\n둘째 줄", **more):
    more.setdefault("blog", "naver_a")
    more.setdefault("post_type", "정보형")
    return draft_store.save_draft(ctx, title=title, body=body, **more)


def write_record(db_path, record):
    """저장한 초안 한 편의 기록을 보관함 파일에 **직접** 바꿔 쓴다 — 앱의 저장은 키 모양을 쓰기 전에 거절하므로(LOCALSAVE D-361) 옛 데이터·손으로 고친 파일을 흉내 낸다.
    기록은 올바른 모양 그대로다(`SavedDraft.from_text` 가 읽는다 — 키 모양은 글칸의 글일 뿐이다)."""
    with contextlib.closing(sqlite3.connect(str(db_path))) as connection:
        connection.execute("UPDATE drafts SET text = ? WHERE project_id = ?", (record.to_text(), record.draft_id))
        connection.commit()


def plant(db_path, draft, body):
    """저장한 초안 한 편의 본문을 키 모양이 든 글로 바꿔 쓴다."""
    write_record(db_path, dataclasses.replace(draft, body=body))


def with_base(draft, **changes):
    return dataclasses.replace(draft, base=dataclasses.replace(draft.base, **changes))


# 저장한 초안 기록의 글칸 하나씩 — (이름, 그 칸에 글 한 줄을 넣은 기록). 목록 칸·선택 입력(`options`)·처음 만든 초안(`base`) 안의 칸은 JSON 안의 중첩이라 백업 훑기가 풀어서 한 칸씩 훑어야 찾는다
FIELDS = (("제목", lambda draft, line: dataclasses.replace(draft, title=line)),
          ("본문", lambda draft, line: dataclasses.replace(draft, body=line)),
          ("핵심 키워드", lambda draft, line: dataclasses.replace(draft, core_keywords=(draft.core_keywords[0], line))),
          ("보조 키워드", lambda draft, line: dataclasses.replace(draft, sub_keywords=(line,))),
          ("태그", lambda draft, line: dataclasses.replace(draft, tags=(draft.tags[0], line))),
          ("카테고리", lambda draft, line: dataclasses.replace(draft, category=line)),
          ("요약", lambda draft, line: dataclasses.replace(draft, summary=line)),
          ("후보 주제", lambda draft, line: dataclasses.replace(draft, topic=line)),
          ("선택 입력", lambda draft, line: dataclasses.replace(draft, options=(("message", line),))),
          ("만든 초안 제목", lambda draft, line: with_base(draft, title=line)),
          ("만든 초안 제목 후보", lambda draft, line: with_base(draft, titles=(draft.base.titles[0], line))),
          ("만든 초안 본문", lambda draft, line: with_base(draft, body=line)),
          ("만든 초안 확인 권장", lambda draft, line: with_base(draft, checks=(line,))),
          ("만든 초안 바꾼 형식", lambda draft, line: with_base(draft, replaced=(draft.base.replaced[0], line))))


def saved_rows(db_path):
    """보관함 파일의 저장한 초안 행 전부 — `(번호, 글, 저장한 시각)`(번호순)."""
    with contextlib.closing(sqlite3.connect(str(db_path))) as connection:
        return connection.execute("SELECT project_id, text, saved_at FROM drafts WHERE project_id LIKE 'dd-%' ORDER BY project_id").fetchall()


def surfaces(error):
    """오류 하나가 사용자에게 갈 수 있는 모든 글(문구·칸·세부·위치 목록·요약·repr·피클) — 키 글자가 새는지 보는 데 쓴다(`test_service_backup_secrets.surfaces` 와 같다)."""
    parts = [str(error), repr(error), error.log_line(), error.rendered().message, error.rendered().action, error.detail, error.summary, " ".join(f"{key}={value}" for key, value in error.slots.items()), error.reason,
             repr(error.findings), repr([dataclasses.asdict(item) for item in error.findings]), str(error.notes)]
    parts += [repr(pickle.loads(pickle.dumps(item))) for item in error.findings]
    return "\n".join(parts)


def rehash(folder):
    """백업 폴더 안 파일을 고친 뒤 목록(MANIFEST)의 크기·해시를 맞춘다 — 고친 백업이 '틀린 백업' 이 아니라 '키 모양이 든 백업' 으로 읽히게."""
    manifest = json.loads((folder / bf.MANIFEST_NAME).read_text(encoding="utf-8"))
    for name, info in manifest["files"].items():
        data = (folder / name).read_bytes()
        info["size"], info["sha256"] = len(data), hashlib.sha256(data).hexdigest()
    bs.write_manifest(folder, manifest)


class PremiseTest(unittest.TestCase):
    def test_the_escaped_text_hides_bare_tokens_that_the_decoded_text_shows(self):
        """이 모듈의 전제 — 저장한 초안의 기록(이스케이프한 JSON 한 줄)을 날것으로 훑으면 줄 처음·탭 뒤·한글 뒤에 붙은 토큰 글자(이름표 없는 모양)를 놓치고 풀어 낸 글에서는 찾는다. 그래서 백업이 JSON 을 풀어서 훑는 것이 뜻이 있고,
        아래 시험들이 그 입력을 쓴다. 놓치는 것은 토큰 글자만과 이스케이프되는 자리뿐이다."""
        sample = sd.SavedDraft.build(draft_id="dd-" + "a" * 20, revision=1, created_at="2026-11-11T00:00:00Z", updated_at="2026-11-11T00:00:00Z", title="제목", body="본문")
        missed = 0
        for kind in KINDS:
            for form, text, _ in forms(kind):
                for label, build in PLACEMENTS:
                    with self.subTest(kind=kind, form=form, placement=label):
                        self.assertTrue(scan.scan_secrets(build(text), "x"), "풀어 낸 글에서는 늘 찾는다")
                        if not scan.scan_secrets(dataclasses.replace(sample, body=build(text)).to_text(), "x"):
                            missed += 1
                            self.assertEqual((form, label in JSON_SENSITIVE), ("토큰만", True), "날것이 놓치는 것은 토큰 글자만과 이스케이프되는 자리뿐이다")
        self.assertGreaterEqual(missed, 10, "날것이 놓치는 입력이 있다 — 없으면 이 모듈의 JSON 풀기 시험이 뜻을 잃는다(전제가 사라진 것이니 시험을 다시 봐야 한다)")
        self.assertEqual(sum(len(forms(kind)) for kind in KINDS), 11, "여섯 종류 가운데 Bearer 만 토큰 글자만으로는 키 모양이 아니다")


class BlockedBackupTest(unittest.TestCase):
    def test_every_kind_in_every_placement_in_a_saved_draft_blocks_the_full_backup_and_leaves_nothing(self):
        count = 0
        for kind in KINDS:
            for form, text, token in forms(kind):
                for label, build in PLACEMENTS:
                    with self.subTest(kind=kind, form=form, placement=label), tempfile.TemporaryDirectory() as tmp:
                        world = bs.World.cached(tmp, posts=1, drafts=0)
                        draft = save_clean(world.ctx)
                        plant(world.path("chanceblog.db"), draft, build(text))
                        self.assertEqual(draft_store.load_draft(world.ctx, draft.draft_id).body, build(text), "먼저 확인: 기록은 올바른 모양이고 키 모양이 실제로 들어 있다(이 시험의 전제)")
                        before = world.data_digests()
                        error = bs.code_of(world.backup)
                        self.assertIsNotNone(error, "백업이 거절돼야 한다")
                        self.assertEqual((error.code, error.reason), ("FULL_BACKUP_BLOCKED", "blocked"))
                        self.assertIn(kind, {item.kind for item in error.findings}, "유형을 알린다")
                        self.assertTrue(all(item.where.startswith("글 보관함") and "저장한 초안" in item.where for item in error.findings), [item.where for item in error.findings])
                        self.assertFalse(S.leaked(surfaces(error), token), "오류 글에 키 글자가 새었다")
                        self.assertEqual(world.data_digests(), before, "지금 데이터는 한 바이트도 바뀌지 않는다")
                        backups = world.ctx.workspace.backups_dir
                        self.assertEqual(list(backups.iterdir()) if backups.is_dir() else [], [], "부분 폴더를 남기지 않는다")
                        self.assertEqual(list(world.ctx.workspace.locks_dir.iterdir()), [], "잠금이 풀린다")
                        count += 1
        self.assertEqual(count, 11 * len(PLACEMENTS), "55조합(열한 입력 x 다섯 자리)을 모두 돌았다")

    def test_a_key_shape_in_any_field_of_a_saved_draft_blocks_the_full_backup(self):
        """고친 글칸(제목·본문·키워드·태그·카테고리·요약·후보 주제·선택 입력)과 처음 만든 초안(제목·제목 후보·본문·확인 권장·바꾼 형식) 어느 칸이든 — 유형을 칸마다 돌려 가며 — 백업이 멈춘다."""
        made = sd.BaseDraft.build("만든 제목", ["만든 제목", "후보 둘"], "만든 본문", ["확인 하나"], "generic", ["후기형", "정보형"])
        for index, (field, put) in enumerate(FIELDS):
            kind = KINDS[index % len(KINDS)]
            line, token = bs.secret_text(kind), bs.secret_token(kind)
            with self.subTest(field=field, kind=kind), tempfile.TemporaryDirectory() as tmp:
                world = bs.World.cached(tmp, posts=1, drafts=0)
                draft = save_clean(world.ctx, title="정상 제목", body="정상 본문", core_keywords=("핵심",), sub_keywords=("보조",), tags=("#태그",), category="분류", summary="요약", topic="주제",
                                   options={"message": "전하고 싶은 말"}, base=made)
                self.assertEqual(world.backup().row.status, bf.STATUS_COMPLETE, "먼저 확인: 정상인 저장한 초안(선택 입력·처음 만든 초안 포함)은 백업을 막지 않는다 — 막는 것은 키 모양 하나뿐이다")
                write_record(world.path("chanceblog.db"), put(draft, " ".join(("앞", line, "뒤"))))
                self.assertEqual(draft_store.load_draft(world.ctx, draft.draft_id).draft_id, draft.draft_id, "먼저 확인: 기록은 올바른 모양이다")
                before = world.data_digests()
                error = bs.code_of(world.backup)
                self.assertIsNotNone(error, "백업이 거절돼야 한다")
                self.assertEqual((error.code, error.reason), ("FULL_BACKUP_BLOCKED", "blocked"))
                self.assertIn(kind, {item.kind for item in error.findings}, "유형을 알린다")
                self.assertTrue(all(item.where.startswith("글 보관함") and "저장한 초안" in item.where for item in error.findings), [item.where for item in error.findings])
                self.assertFalse(S.leaked(surfaces(error), token), "오류 글에 키 글자가 새었다")
                self.assertEqual(world.data_digests(), before, "지금 데이터는 한 바이트도 바뀌지 않는다")
        self.assertEqual(len(FIELDS), 14, "기록의 글칸 열네 곳을 모두 돌았다")

    def test_a_clean_saved_draft_next_to_a_planted_one_does_not_hide_it(self):
        """정상인 저장한 초안이 앞에 여럿 있어도 뒤의 한 편에 든 키 모양을 찾는다(번호순·표 순서에 기대지 않는다)."""
        with tempfile.TemporaryDirectory() as tmp:
            world = bs.World(tmp, posts=1, drafts=0)
            clean = [save_clean(world.ctx, title=f"정상 제목 {number}", body=f"정상 본문 {number}") for number in range(4)]
            dirty = save_clean(world.ctx, title="키가 들어갈 제목", body="키가 들어갈 본문")
            plant(world.path("chanceblog.db"), dirty, "첫 줄\n" + shape("github_token") + "\n끝")
            error = bs.code_of(world.backup)
            self.assertEqual((error.code, error.reason), ("FULL_BACKUP_BLOCKED", "blocked"))
            self.assertEqual({item.kind for item in error.findings}, {"github_token"})
            self.assertEqual(len(clean), 4)


class RoundTripTest(unittest.TestCase):
    def test_clean_saved_drafts_are_in_the_backup_and_come_back_letter_for_letter(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = bs.World(tmp, posts=1, drafts=0)
            ctx, live = world.ctx, world.path("chanceblog.db")
            made = sd.BaseDraft.build("만든 제목", ["만든 제목", "후보 둘"], "만든 본문\n둘째 줄", ["확인 하나"], "generic", ["후기형", "정보형"])
            rich = save_clean(ctx, title="  고친 제목 " + EMOJI, body="고친 본문\r\n둘째 줄 " + NFD + NBSP + "끝  ", core_keywords=("핵심",), sub_keywords=("보조 하나", "보조 둘"), tags=("#태그",),
                              category="생활 정보", summary="한 줄 요약", candidate_id="cand-1", topic="후보 주제", post_type_choice="비교형", post_type="비교형", options={"message": "전하고 싶은 말"}, base=made)
            plain = save_clean(ctx, title="둘째 저장한 초안", body="단순한 본문")
            rows_before = saved_rows(live)
            self.assertEqual(len(rows_before), 2)
            outcome = world.backup()
            self.assertEqual(outcome.row.status, bf.STATUS_COMPLETE)
            self.assertEqual(saved_rows(world.folder(outcome) / "chanceblog.db"), rows_before, "백업 안의 저장한 초안 행은 지금과 한 글자도 같다")
            # 백업 뒤에 고치고 새로 만든다 — 되돌리면 이 둘은 백업 때의 모습으로 돌아가야 한다
            edited = save_clean(ctx, title="백업 뒤에 고친 제목", body="백업 뒤에 고친 본문", draft_id=plain.draft_id, expected_revision=plain.revision)
            later = save_clean(ctx, title="백업 뒤에 새로 만든 글", body="새 본문")
            rows_after = saved_rows(live)
            self.assertEqual((edited.revision, len(rows_after)), (plain.revision + 1, 3))
            restored = bf.restore_full_backup(ctx, outcome.row.name, confirmed=True)
            self.assertEqual(restored.status, bf.STATUS_COMPLETE)
            self.assertEqual(saved_rows(live), rows_before, "되돌린 뒤의 저장한 초안 행은 백업 때와 한 글자도 같다")
            self.assertEqual(draft_store.load_draft(ctx, rich.draft_id), rich)
            self.assertEqual(draft_store.load_draft(ctx, plain.draft_id), plain)
            listing = draft_store.list_drafts(ctx)
            self.assertEqual(sorted(entry.draft_id for entry in listing.entries), sorted([rich.draft_id, plain.draft_id]))
            self.assertEqual(listing.unreadable, ())
            with self.assertRaises(AppError) as caught:
                draft_store.load_draft(ctx, later.draft_id)
            self.assertEqual(caught.exception.code, "CONTENT_NOT_FOUND", "백업 뒤에 만든 초안은 되돌리면 사라진다(복원은 그때의 데이터로 바꾼다)")
            # 복원 직전 안전 사본에는 백업 뒤의 상태(고친 것·새로 만든 것)가 그대로 남아 있다
            self.assertTrue(restored.safety, "되돌리기 전의 지금 데이터를 안전 사본으로 남겼다")
            self.assertEqual(saved_rows(ctx.workspace.backups_dir / bf.SAFETY_FOLDER / restored.safety / "chanceblog.db"), rows_after)
            # 되돌린 초안을 이어 고쳐 저장할 수 있다(저장 횟수가 이어진다 — 충돌이 아니다)
            again = save_clean(ctx, title="되돌린 뒤 이어 고침", body="이어 고친 본문", draft_id=plain.draft_id, expected_revision=plain.revision)
            self.assertEqual((again.draft_id, again.revision), (plain.draft_id, plain.revision + 1))


class RestoreRefusalTest(unittest.TestCase):
    def test_a_backup_whose_saved_draft_holds_a_key_shape_is_not_restored(self):
        count = 0
        for kind in KINDS:
            text, token = shape(kind), S.sample(kind)[0]
            for label, build in PLACEMENTS:
                if label not in JSON_SENSITIVE:
                    continue
                with self.subTest(kind=kind, placement=label), tempfile.TemporaryDirectory() as tmp:
                    world = bs.World.cached(tmp, posts=1, drafts=0)
                    draft = save_clean(world.ctx)
                    outcome = world.backup()
                    folder = world.folder(outcome)
                    plant(folder / "chanceblog.db", draft, build(text))
                    rehash(folder)
                    before = world.data_digests()
                    error = bs.code_of(bf.restore_full_backup, world.ctx, outcome.row.name, confirmed=True)
                    self.assertIsNotNone(error, "복원이 거절돼야 한다")
                    self.assertEqual((error.code, error.reason), ("FULL_BACKUP_BLOCKED", "blocked"))
                    self.assertIn("이 백업 안의 글이라 앱이 고치지 않아요", error.summary)
                    self.assertFalse(S.leaked(surfaces(error), token), "오류 글에 키 글자가 새었다")
                    self.assertEqual(world.data_digests(), before, "지금 데이터는 한 바이트도 바뀌지 않는다")
                    self.assertFalse((world.ctx.workspace.backups_dir / bf.SAFETY_FOLDER).exists(), "아무것도 시작하지 않았다")
                    count += 1
        self.assertEqual(count, len(KINDS) * len(JSON_SENSITIVE))


if __name__ == "__main__":
    unittest.main()
