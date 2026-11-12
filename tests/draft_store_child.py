"""저장한 초안 시험이 **새 프로세스**로 돌리는 도우미(시험이 아니다) — 같은 임시 데이터 폴더를 다른 파이썬 프로세스가 읽고 쓴다(재실행 뒤 복원·두 프로세스 동시 저장·쓰다가 죽은 프로세스).

사용: python -X utf8 -I draft_store_child.py <동작> <데이터 폴더> [인자…]
  dump <폴더> <번호>            그 초안의 칸을 `ensure_ascii` JSON 한 줄로 찍는다(글자 하나도 바뀌지 않았는지 부모가 견준다)
  list <폴더>                   저장한 초안의 (번호, 제목) 목록을 JSON 한 줄로
  save <폴더> <JSON 파일>        파일에 적힌 인자들(`save_draft` 의 이름 붙은 인자)로 저장하고 번호를 찍는다
  many <폴더> <접두사> <개수> <신호 파일>  신호 파일이 생길 때까지 기다렸다가 제목이 `<접두사>-<번호>` 인 초안을 개수만큼 저장한다(두 프로세스가 동시에 쓰게)
  crash <폴더> <번호>           보관함에 쓰기 트랜잭션을 열고 글을 바꾼 뒤 **커밋하지 않고** 프로세스를 죽인다(`os._exit`)
  same <폴더> <번호> <횟수> <신호 파일> <free|expect> <접두사>  신호 파일이 생길 때까지 기다렸다가 **같은 초안**을 횟수만큼 저장한다 — free 는 번호만 주고, expect 는 방금 불러온 저장 횟수를
                                `expected_revision` 으로 준다(충돌은 세어 둔다). 성공·충돌 횟수를 JSON 한 줄로 찍는다
  crash_big <폴더> <번호>       쪽 캐시를 아주 작게 하고 아주 큰 글로 바꾸는 쓰기 트랜잭션을 연 채 죽는다 — 커밋 전에 파일로 넘쳐 쓰여 **저널이 남는다**(읽기 전용 열기가 만나는 STORE_RECOVERY_PENDING 상황)
`-I`(격리) 모드라 이 파일이 소스 폴더를 직접 경로에 올린다.
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.service import draft_store  # noqa: E402
from chanceblog_desktop.service.context import make_context  # noqa: E402

FIXED = "2026-11-11T09:30:15Z"


def context(folder):
    import datetime
    return make_context(data_dir=folder, clock=lambda: datetime.datetime(2026, 11, 11, 9, 30, 15, tzinfo=datetime.timezone.utc))


def fields_of(draft):
    base = None if draft.base is None else draft.base.to_dict()
    return {"draft_id": draft.draft_id, "revision": draft.revision, "title": draft.title, "body": draft.body, "core_keywords": list(draft.core_keywords), "sub_keywords": list(draft.sub_keywords),
            "tags": list(draft.tags), "category": draft.category, "summary": draft.summary, "candidate_id": draft.candidate_id, "topic": draft.topic, "blog": draft.blog, "post_type": draft.post_type,
            "options": draft.options_dict(), "created_at": draft.created_at, "updated_at": draft.updated_at, "base": base}


def main(argv):
    mode, folder = argv[0], argv[1]
    ctx = context(folder)
    if mode == "dump":
        print(json.dumps(fields_of(draft_store.load_draft(ctx, argv[2])), ensure_ascii=True))
    elif mode == "list":
        print(json.dumps([[entry.draft_id, entry.title] for entry in draft_store.list_drafts(ctx).entries], ensure_ascii=True))
    elif mode == "save":
        arguments = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        print(draft_store.save_draft(ctx, **arguments).draft_id)
    elif mode == "many":
        prefix, count, signal = argv[2], int(argv[3]), Path(argv[4])
        deadline = time.monotonic() + 60
        while not signal.exists() and time.monotonic() < deadline:
            time.sleep(0.005)
        saved = []
        for number in range(count):
            saved.append(draft_store.save_draft(ctx, title=f"{prefix}-{number}", body=f"{prefix} 본문 {number}", blog="naver_a", post_type="정보형").draft_id)
        print(json.dumps(saved))
    elif mode == "same":
        draft_id, count, signal, how = argv[2], int(argv[3]), Path(argv[4]), argv[5]
        deadline = time.monotonic() + 60
        while not signal.exists() and time.monotonic() < deadline:
            time.sleep(0.002)
        done, conflicts = 0, 0
        for number in range(count):
            try:
                expected = draft_store.load_draft(ctx, draft_id).revision if how == "expect" else None
                draft_store.save_draft(ctx, title=f"{argv[6]}-{number}", body=f"{argv[6]} 본문 {number}", blog="naver_a", post_type="정보형", draft_id=draft_id, expected_revision=expected)
                done += 1
            except AppError as error:
                if error.code != "STORE_CONFLICT":
                    raise
                conflicts += 1
        print(json.dumps({"done": done, "conflicts": conflicts}))
    elif mode == "crash_big":
        connection = sqlite3.connect(str(Path(folder) / "chanceblog.db"), isolation_level=None)
        connection.execute("PRAGMA cache_size = 16")                    # 쪽 캐시를 아주 작게 — 큰 글이 커밋 전에 파일로 넘쳐 쓰이게(저널이 남는다)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE drafts SET text = ? WHERE project_id = ?", ("큰 글" * 400000, argv[2]))
        os._exit(3)
    elif mode == "crash":
        connection = sqlite3.connect(str(Path(folder) / "chanceblog.db"), isolation_level=None)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE drafts SET text = ? WHERE project_id = ?", ("부분만 쓴 기록", argv[2]))
        connection.execute("INSERT INTO drafts (project_id, text, saved_at) VALUES (?, ?, ?)", ("dd-" + "e" * 20, "반쯤 쓴 새 기록", FIXED))
        os._exit(3)
    else:
        sys.exit("알 수 없는 동작")


if __name__ == "__main__":
    main(sys.argv[1:])
