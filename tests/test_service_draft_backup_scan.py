"""저장한 초안이 든 글 보관함을 **백업하기 전의** Secret 모양 검사(`security/refuse.py` — PCSEC1 M3)가 저장한 초안을 풀어서 칸별로 훑는다(LOCALSAVE 독립 검증 D6, 결정 D-373).

저장한 초안(`dd-` 번호)은 글칸을 `ensure_ascii` JSON 한 줄로 보관함 `drafts` 표에 둔다 — 날것 그대로 훑으면 줄바꿈·탭·한글이 `\\n`·`\\t`·`\\uXXXX` 로 이스케이프돼 줄 맨 앞·탭 뒤·한글 바로 뒤의 키 모양이
앞 글자와 붙어 보여 놓친다(독립 검증이 여섯 종류 x 다섯 자리 30조합 중 14곳을 놓친다고 쟀다). 이제 `SavedDraft.from_text` 로 풀어 `text_fields()`·`base_fields()` 의 글을 칸별로 훑고, 위치는
'저장한 초안 N번째 · 칸 이름 N번째 줄' 이다(글 내용은 없다). 정상 경로로는 저장 직전 검사가 막으므로 키 모양이 든 저장한 초안은 생기지 않는다 — 옛 데이터·손으로 고친 파일을 흉내 내려고 보관함 표에 행을 직접 넣는다.

지키는 것:
  1) 여섯 종류 x 다섯 자리(공백 뒤·줄 처음·탭 뒤·한글 뒤 붙여·글 맨 앞) 30조합이 모두 백업을 멈추고(`SECRET_SHAPE_FOUND`) 백업 파일이 만들어지지 않으며 찾은 글이 어디에도 다시 나오지 않는다.
  2) 저장한 초안의 모든 칸(글칸 열한 곳·선택 입력·만든 초안 여섯 곳)이 각각 위치에 칸 이름으로 나온다. 정상 글은 막지 않는다.
  3) 풀 수 없는 기록도 날것으로나마 훑고(죽지 않는다) 번호 순서는 저장한 초안만 센다 — 저장한 초안이 아닌 초안 행은 예전 이름(`초안 #N`) 그대로다.
시험 입력의 키 모양은 `scan_samples` 가 실행할 때 조각을 이어 붙여 만든다(소스에 완성된 키가 없다).
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_samples as SS  # noqa: E402
import service_support as ss  # noqa: E402

from chanceblog_desktop.content import saved_draft as sd  # noqa: E402
from chanceblog_desktop.content.store import Store  # noqa: E402
from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.security import refuse, scan  # noqa: E402
from chanceblog_desktop.service import projects  # noqa: E402

PLACEMENTS = (("공백 뒤", lambda line: "앞 " + line + " 뒤"), ("줄 처음(개행 뒤)", lambda line: "첫 줄\n" + line + "\n끝"), ("탭 뒤", lambda line: "앞\t" + line),
              ("한글 뒤 붙여", lambda line: "한글" + line), ("글 맨 앞", lambda line: line + " 뒤"))


def record(number, **more):
    """보관함에 직접 넣을 저장한 초안 한 편(번호 `dd-` + 지문) — 서비스의 저장 직전 검사를 거치지 않는다."""
    stamp = f"2026-11-11T09:{number:02d}:00Z"
    fields = dict(title=f"정상 제목 {number}", body=f"정상 본문 {number}", blog="naver_a", post_type="정보형")
    fields.update(more)
    draft_id = sd.make_draft_id(stamp, fields.get("candidate_id", ""), fields["blog"], fields["title"], fields["body"])
    return sd.SavedDraft.build(draft_id=draft_id, revision=1, created_at=stamp, updated_at=stamp, **fields), stamp


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.ctx = ss.make_ctx(tmp.name)
        self.ctx.workspace.root.mkdir(parents=True, exist_ok=True)

    def plant(self, *drafts):
        with Store.open(self.ctx.workspace.store_path) as store:
            for draft, stamp in drafts:
                store.save_draft(draft.draft_id, draft.to_text(), now=stamp)

    def refused(self):
        with self.assertRaises(AppError) as caught:
            projects.backup_store(self.ctx)
        return caught.exception

    def shown(self, error):
        return " | ".join([str(error), repr(error), error.detail or "", " | ".join(getattr(error, "notes", ())), repr(error.slots), error.rendered().message, repr(getattr(error, "findings", ()))])

    def backups(self):
        folder = self.ctx.workspace.backups_dir
        return sorted(path.name for path in folder.rglob("*") if path.is_file()) if folder.exists() else []


class EveryPlacementTest(Base):
    def test_the_premise_the_decoded_text_has_every_kind_in_every_placement(self):
        for kind in SS.KINDS:
            for label, build in PLACEMENTS:
                with self.subTest(kind=kind, placement=label):
                    self.assertTrue(scan.scan_fields({"본문": build(SS.sample(kind)[1])}), "풀어 낸 글에서는 찾는다 — 이 시험의 전제")

    def test_every_kind_in_every_placement_in_a_saved_draft_stops_the_backup_and_names_the_field(self):
        for kind in SS.KINDS:
            token, line = SS.sample(kind)
            for label, build in PLACEMENTS:
                with self.subTest(kind=kind, placement=label):
                    folder = self.ctx.workspace.store_path
                    if folder.exists():
                        folder.unlink()
                    self.plant(record(1, body=build(line)))
                    error = self.refused()
                    self.assertEqual(error.code, "SECRET_SHAPE_FOUND")
                    self.assertIn("저장한 초안 1번째 · 본문", self.shown(error))
                    self.assertFalse(SS.leaked(self.shown(error), token), "찾은 글이 어디에도 다시 나오지 않는다")
                    self.assertEqual(self.backups(), [], "백업 파일이 만들어지지 않았다")


class EveryFieldTest(Base):
    def test_every_field_of_a_saved_draft_is_scanned_and_named(self):
        token, line = SS.sample("github_token")
        text_cases = (("제목", dict(title="앞 " + line)), ("본문", dict(body="본문\n" + line)), ("핵심 키워드", dict(core_keywords=("키워드", line))), ("보조 키워드", dict(sub_keywords=(line,))),
                      ("태그", dict(tags=("#태그", line))), ("카테고리", dict(category=line)), ("요약", dict(summary="요약 " + line)), ("후보 주제", dict(topic=line)),
                      ("선택 입력(실제 사용 경험)", dict(options={"experience": "써 보니 " + line})))
        for label, fields in text_cases:
            with self.subTest(field=label):
                path = self.ctx.workspace.store_path
                if path.exists():
                    path.unlink()
                self.plant(record(2, **fields))
                shown = self.shown(self.refused())
                self.assertIn(f"저장한 초안 1번째 · {label}", shown)
                self.assertFalse(SS.leaked(shown, token))

    def test_the_made_draft_fields_are_scanned_and_named_too(self):
        token, line = SS.sample("google_api_key")
        cases = (("만든 초안 제목", dict(title="앞 " + line)), ("만든 초안 제목 후보", dict(titles=("후보", line))), ("만든 초안 본문", dict(body="만든\n" + line)),
                 ("만든 초안 확인 권장", dict(checks=("확인", line))), ("만든 초안 바꾼 형식", dict(replaced=("후기형", "앞 " + line))))
        for label, fields in cases:
            with self.subTest(field=label):
                path = self.ctx.workspace.store_path
                if path.exists():
                    path.unlink()
                base = dict(title="만든 제목", titles=("만든 제목",), body="만든 본문", checks=(), domain="generic", replaced=None)
                base.update(fields)
                self.plant(record(3, base=sd.BaseDraft.build(**base)))
                shown = self.shown(self.refused())
                self.assertIn(f"저장한 초안 1번째 · {label}", shown)
                self.assertFalse(SS.leaked(shown, token))

    def test_the_candidate_number_and_the_made_drafts_domain_are_scanned_too(self):
        for label, fields in (("후보 번호", dict(candidate_id=SS.sample("github_token")[0])), ("만든 초안 분야", dict(base=sd.BaseDraft.build("만든 제목", ["만든 제목"], "만든 본문", [], SS.sample("aws_access_key")[0], None)))):
            with self.subTest(field=label):
                path = self.ctx.workspace.store_path
                if path.exists():
                    path.unlink()
                self.plant(record(4, **fields))
                self.assertIn(f"저장한 초안 1번째 · {label}", self.shown(self.refused()))


class OrderAndFallbackTest(Base):
    def test_the_number_counts_saved_drafts_only_and_a_clean_store_is_backed_up(self):
        clean = [record(5), record(6)]
        self.plant(*clean)
        path = projects.backup_store(self.ctx)
        self.assertTrue(Path(path).is_file(), "정상 글만 든 보관함은 막지 않는다")
        made = self.backups()
        token, line = SS.sample("bearer_token")
        self.plant(record(7, body="셋째\n" + line))
        error = self.refused()
        self.assertRegex(self.shown(error), r"저장한 초안 [123]번째 · 본문 2번째 줄")
        self.assertEqual(self.backups(), made, "새 백업은 만들어지지 않았다")

    def test_a_saved_draft_after_a_newer_plain_row_is_still_the_first_saved_draft(self):
        """번호는 저장한 초안끼리만 센다 — 더 최근에 저장된 저장한 초안이 아닌 행이 앞에 와도 이 저장한 초안은 '첫 번째' 다."""
        token, line = SS.sample("google_api_key")
        with Store.open(self.ctx.workspace.store_path) as store:
            store.save_draft("p1", "자동 저장 글", now="2026-11-11T23:00:00Z")
        self.plant(record(11, body="앞 " + line))
        shown = self.shown(self.refused())
        self.assertIn("저장한 초안 1번째 · 본문", shown)
        self.assertNotIn("저장한 초안 2번째", shown)
        self.assertFalse(SS.leaked(shown, token))

    def test_a_row_that_is_not_a_saved_draft_keeps_the_old_label(self):
        token, line = SS.sample("github_token")
        with Store.open(self.ctx.workspace.store_path) as store:
            store.save_draft("p1", "자동 저장 글 " + line, now="2026-11-11T09:00:00Z")
        shown = self.shown(self.refused())
        self.assertIn("초안 #1", shown)
        self.assertNotIn("저장한 초안", shown)
        self.assertFalse(SS.leaked(shown, token))

    def test_a_record_that_cannot_be_read_is_scanned_raw_and_does_not_stop_the_scan(self):
        token, line = SS.sample("google_api_key")
        broken_id = "dd-" + "a" * 20
        with Store.open(self.ctx.workspace.store_path) as store:
            store.save_draft(broken_id, "깨진 기록 아님 아무 글 key=" + token[:4], now="2026-11-11T09:00:00Z")
        self.assertTrue(Path(projects.backup_store(self.ctx)).is_file(), "읽을 수 없는 기록이 정상 글이면 백업은 막히지 않는다")
        with Store.open(self.ctx.workspace.store_path) as store:
            store.save_draft(broken_id, "깨진 기록 " + line, now="2026-11-11T09:00:01Z")
        shown = self.shown(self.refused())
        self.assertIn("저장한 초안 1번째", shown)
        self.assertFalse(SS.leaked(shown, token))

    def test_the_scan_reads_the_store_only(self):
        """백업 전 검사는 읽기뿐이다 — 거절한 뒤에도 보관함의 모든 행이 그대로다."""
        token, line = SS.sample("oauth_token")
        self.plant(record(8, body="앞\t" + line), record(9))
        path = self.ctx.workspace.store_path
        with sqlite3.connect(str(path)) as connection:
            before = connection.execute("SELECT project_id, text, saved_at FROM drafts ORDER BY project_id").fetchall()
        self.refused()
        with sqlite3.connect(str(path)) as connection:
            after = connection.execute("SELECT project_id, text, saved_at FROM drafts ORDER BY project_id").fetchall()
        self.assertEqual(before, after)

    def test_the_helper_that_names_a_saved_draft_field_never_holds_the_text(self):
        token, line = SS.sample("github_token")
        draft, stamp = record(10, body=line)
        with Store.open(self.ctx.workspace.store_path) as store:
            store.save_draft(draft.draft_id, draft.to_text(), now=stamp)
            findings = refuse.store_findings(store)
        self.assertEqual([(item.where, item.line, item.kind) for item in findings], [("저장한 초안 1번째 · 본문", 1, "github_token")])
        self.assertFalse(SS.leaked(repr(findings), token))


if __name__ == "__main__":
    unittest.main()
