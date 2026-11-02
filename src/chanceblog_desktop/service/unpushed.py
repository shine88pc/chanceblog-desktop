"""연결한 저장소에 '올리지 않은 commit' 이 있을 때 그것이 무엇인지 알아보고 **정확한 안내 한 가지**를 만든다(읽기만 한다 — 아무것도 바꾸지 않는다).

올리지 않은 commit 이 있으면 앱은 새 글을 올리지 않는다(PAGES_LOCAL_REPO_DIVERGED). 그런데 그 commit 의 정체에 따라 해야 할 일이 다르다:
  · resume   앱이 올리다 멈춘 글 하나의 것(기록(commit) 직후에 멈췄거나 push 가 막혔다) → 그 글의 같은 명령이 이어받아 올리거나 `--cancel --yes` 로 되돌린다.
  · overlap  앱이 올리다 멈춘 글이 둘 이상 겹쳐 있다(commit 이 쌓였다) → 앱은 맨 위(가장 나중에 기록한) 글부터만 되돌릴 수 있다. 나중 글부터 `--cancel --yes` 로 되돌린 뒤 앞 글을 올린다.
  · mixed    앱이 아는 글 기록과 앱이 만든 것이 아닌 commit 이 섞여 있다 → 앱은 직접 만든 commit 을 지우거나 되돌리지 않는다. 사람이 확인한다.
  · unknown  앱이 만든 글 기록이 하나도 아니다 → 사람이 확인한다.
`publish-pages`(미리 보기 포함)와 `doctor` 가 같은 분석을 쓰므로 같은 말을 한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..content import status as st
from ..errors import AppError
from .gate import split_post
from .journal import Journal
from .previews import PLATFORM_PAGES
from .projects import list_projects

KIND_COMMITTED = "committed"      # 발행 기록(COMMITTED)이 있는 글
KIND_ADOPT = "adopt"              # 기록 직후에 멈춰 기록 없이 commit 만 남은 승인된 글(같은 명령이 이어받는다)
RESUME, OVERLAP, MIXED, UNKNOWN = "resume", "overlap", "mixed", "unknown"
GIT_LOG = "git log origin/main..HEAD"


@dataclass(frozen=True)
class Entry:
    project_id: str
    title: str
    kind: str              # KIND_COMMITTED · KIND_ADOPT
    latest: bool           # 맨 위(가장 나중에 기록한) commit 이 이 글의 것인가(알 수 없으면 False)

    @property
    def short(self):
        return self.project_id[:8]


@dataclass(frozen=True)
class Situation:
    ahead: int             # 올리지 않은 commit 수(0 이면 없다)
    entries: tuple         # Entry — 앱이 아는 글 기록(맨 위 글이 알려져 있으면 맨 앞)

    @property
    def kind(self):
        if not self.ahead:
            return ""
        if not self.entries:
            return UNKNOWN
        if self.ahead == 1 and len(self.entries) == 1:
            return RESUME
        if self.ahead > len(self.entries):
            return MIXED
        return OVERLAP

    def top(self):
        """되돌릴 때 먼저 손댈 글(맨 위 commit 의 글). 알 수 없으면 None."""
        return next((entry for entry in self.entries if entry.latest), None)


def orphan_of(ctx, repo, project_id):
    """승인된 글의 commit 이 기록 없이 남아 있으면 그 commit(CommitInfo), 아니면 None — 읽기만 한다. 글·저장소를 읽을 수 없으면 None(그 문제는 다른 점검이 알린다)."""
    try:
        with ctx.store() as store:
            variant = store.load(project_id).variant(PLATFORM_PAGES)
        if not variant.rendered:
            return None
        header, _body = split_post(variant.rendered)
        return ctx.backend.orphan_commit(repo, variant.rendered, header["category"], header["lang"])
    except AppError:
        return None


def describe(ctx, repo):
    """올리지 않은 commit 이 무엇인지 → Situation(없으면 ahead 0). 알 수 없으면(git 이 답하지 않음) 없는 것으로 본다 — 그 문제는 다른 점검이 알린다."""
    ahead = ctx.backend.unpushed_count(repo)
    if not ahead:
        return Situation(0, ())
    try:
        head = ctx.backend.head_commit(repo)
    except AppError:
        head = ""
    journal = Journal(ctx.workspace.journal_dir)
    entries = []
    try:
        rows = list_projects(ctx)
    except AppError:
        rows = []                                              # 글 저장소를 읽을 수 없으면 앱이 아는 기록이 없는 것으로 본다 — 그 문제는 다른 점검(글 저장소)이 알린다
    for row in rows:
        if row.error:
            continue
        status = row.statuses.get(PLATFORM_PAGES)
        if status == st.COMMITTED:
            try:
                record = journal.read(row.project_id)
            except AppError:
                record = None
            if record is not None and ctx.backend.on_remote(repo, record.path):
                continue                                       # 이미 원격 main 에 올라가 있다(올림 기록만 남았다) — 올리지 않은 commit 이 아니다
            entries.append(Entry(row.project_id, row.title, KIND_COMMITTED, bool(head) and record is not None and record.commit == head))
        elif status == st.APPROVED and ahead == 1 and orphan_of(ctx, repo, row.project_id) is not None:
            entries.append(Entry(row.project_id, row.title, KIND_ADOPT, True))
    entries.sort(key=lambda entry: not entry.latest)                     # 맨 위 글이 알려져 있으면 맨 앞(sort 는 안정적이라 나머지는 그대로)
    return Situation(ahead, tuple(entries))


def _names(entries):
    return ", ".join(f"「{entry.title}」(번호 {entry.short})" for entry in entries)


def resume_commands(entry):
    how = "이어받아 올리거나" if entry.kind == KIND_ADOPT else "이어서 올리거나"
    return f"`publish-pages {entry.short} --yes` 로 {how} 올리지 않고 되돌리려면 `publish-pages {entry.short} --cancel --yes`"


def action_text(situation):
    """상황에 맞는 하실 일 — 한 가지 정확한 안내(쉬운 한국어). 올리지 않은 commit 이 없으면 ''."""
    kind = situation.kind
    if kind == RESUME:
        entry = situation.entries[0]
        what = ("올리다 기록(commit) 직후에 멈춘" if entry.kind == KIND_ADOPT else "올리다 멈춘")
        return f"앱이 {what} 글 「{entry.title}」(번호 {entry.short})의 기록입니다 — {resume_commands(entry)} 합니다."
    if kind == OVERLAP:
        top = situation.top()
        first = f"가장 나중에 기록한 글 「{top.title}」(번호 {top.short})부터" if top else f"가장 나중에 기록한 글(`{GIT_LOG}` 맨 위)부터"
        command = f"`publish-pages {top.short} --cancel --yes`" if top else "`publish-pages 그 글번호 --cancel --yes`"
        return (f"올리지 않은 글 기록 {situation.ahead}개가 겹쳐 있습니다: {_names(situation.entries)}. 앱은 맨 위(가장 나중에 기록한) 글부터만 되돌릴 수 있습니다 — {first} {command} 로 되돌리고"
                "(원격은 건드리지 않습니다), 남은 글을 `publish-pages 글번호 --yes` 로 올립니다. 되돌린 글은 `review` 로 다시 만들어 검토·승인한 뒤 올립니다.")
    if kind == MIXED:
        return (f"올리지 않은 commit {situation.ahead}개 중 앱이 올리다 멈춘 글의 기록은 {len(situation.entries)}개({_names(situation.entries)})뿐이고 나머지는 앱이 만든 것이 아닙니다. "
                f"앱은 직접 만든 commit 을 지우거나 되돌리지 않습니다 — 그 폴더에서 `{GIT_LOG}` 로 무엇인지 확인해 올리거나 정리한 뒤 다시 실행합니다.")
    if kind == UNKNOWN:
        return (f"앱이 만든 글 기록이 아닌 commit {situation.ahead}개가 있습니다. 앱은 직접 만든 commit 을 지우거나 되돌리지 않습니다 — "
                f"그 폴더에서 `{GIT_LOG}` 로 무엇인지 확인해 직접 올리거나(`git push`) 정리한 뒤 다시 실행합니다.")
    return ""


def entry_text(situation, entry):
    """doctor 의 '이어서 처리할 글' 한 줄에 쓸 이 글의 처리 방법(그 글 한 편에 대한 정확한 안내)."""
    kind = situation.kind
    if kind in (RESUME, ""):
        return f"{resume_commands(entry)} 합니다."
    if kind in (MIXED, UNKNOWN):
        return (f"이 글의 기록 위에 앱이 만든 것이 아닌 commit 이 있어 지금은 올리거나 되돌릴 수 없습니다 — 그 폴더에서 `{GIT_LOG}` 로 확인해 직접 정리한 뒤 "
                f"`publish-pages {entry.short} --yes` 로 이어서 올리거나 `publish-pages {entry.short} --cancel --yes` 로 되돌립니다.")
    top = situation.top()
    if entry.latest:
        return (f"올리지 않은 글 기록이 겹쳐 있고 이 글이 맨 위(가장 나중)입니다 — 지금은 올릴 수 없고, 되돌리려면 이 글부터 `publish-pages {entry.short} --cancel --yes` 입니다"
                "(되돌린 글은 `review` 로 다시 만들어 승인해야 올릴 수 있습니다).")
    where = f"먼저 맨 위 글 「{top.title}」(번호 {top.short})을 `publish-pages {top.short} --cancel --yes` 로 되돌립니다. " if top else "먼저 맨 위(가장 나중) 글을 되돌립니다. "
    return f"이 글 위에 다른 글의 기록이 쌓여 있어 지금은 올리거나 되돌릴 수 없습니다 — {where}그 뒤 `publish-pages {entry.short} --yes` 로 올립니다."
