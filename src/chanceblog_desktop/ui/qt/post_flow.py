"""글 검토 화면(글 흐름 1a, 결정 D-620 이후)의 앱 틀 쪽 동작 — `AppShell` 에 섞어 쓰는 묶음(`PostFlowMixin`). 눌림을 컨트롤러(`PostsController`)로 넘기고 작업 스레드의 결과를 받아 화면·대화상자를 다시 그린다.
읽기(목록·글·파일)는 작업 스레드에서 돌고 쓰기(가져오기·검토 시작·승인·승인 취소)는 사용자가 단추를 눌렀을 때만 시작하는 작업 하나다 — 규칙(승인 조건·확인창·낡은 결과·입력 보존·복원 중 막기)은 모두 core 에 있고 여기에는 없다.
입력 대화상자 둘(가져오기·Pages 검토 값)은 앱 틀의 `dialog` 에 얹는다. 어느 길로든(취소·Esc·성공·다른 대화상자로 바뀜) 닫히면 정리 훅이 칸의 글을 비운다. 앱을 닫을 때 가져오기 칸에 입력이 있으면 같은 대화상자 안에서 확인 줄이 먼저다.
이 파일에는 파일을 만지는 호출·네트워크·하위 프로세스·표준 출력이 없다 — 서비스는 어댑터(`ui/posts_adapter.py`)만 부른다.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from ..core import posts_view as pv
from ..core.app_state import report_unexpected
from ..core.posts import PAGES
from ..core.text import T
from .post_package_parts import RecordDialog
from .post_parts import DIALOG_WIDTH, ImportDialog, PagesDialog
from .workers import JobBridge

IMPORT_FILTER = "*.md *.txt"                                                          # 가져올 글 파일의 종류(Markdown·메모장 글)
WRITE_CLOSE_WAIT = 10.0                                                               # 창을 닫을 때 글 쓰기가 돌고 있으면 끝나기를 기다리는 최대 시간(초) — 쓰기는 중간에 끊을 수 없다


class PostFlowMixin:
    # ---- 만들기 ----
    def _init_posts(self):
        """글 검토의 작업 다리 넷 — 목록 읽기·글 읽기·파일 읽기·쓰기가 따로 돈다(홈·설정·다른 화면의 읽기와도 따로다)."""
        self.post_import_form = None                                                  # 열려 있는 '글 가져오기' 대화의 안쪽 부품(없으면 None)
        self.post_pages_form = None                                                   # 열려 있는 'Pages 검토 값' 대화의 안쪽 부품(없으면 None)
        self.post_record_form = None                                                  # 열려 있는 '발행 주소 기록' 대화의 안쪽 부품(없으면 None — 글 흐름 1b)
        for name, loaded, failed, cancelled in (("posts_bridge", self._on_posts_loaded, self._on_posts_failed, self._on_posts_cancelled),
                                                ("post_detail_bridge", self._on_post_detail_loaded, self._on_post_detail_failed, self._on_post_detail_cancelled),
                                                ("post_file_bridge", self._on_post_file_loaded, self._on_post_file_failed, self._on_post_file_cancelled),
                                                ("posts_write_bridge", self._on_posts_written, self._on_posts_write_failed, self._on_posts_write_cancelled)):
            bridge = JobBridge(self)
            bridge.loaded.connect(loaded)
            bridge.failed.connect(failed)
            bridge.cancelled.connect(cancelled)
            setattr(self, name, bridge)

    # ---- 화면 ----
    def _render_posts(self):
        if self.state.page == "posts":                                                # 다른 화면을 보는 중이면 값만 받아 두고 다시 그리지 않는다
            self.render()
            if self.dialog.is_open and (self.post_import_form is not None or self.post_pages_form is not None or self.post_record_form is not None):
                self._trap_focus(True, self.dialog)                                   # 다시 그리면서 새로 생긴 위젯으로 Tab 이 대화상자 밖으로 새지 않게 다시 가둔다

    def _posts_opened(self):
        """글 검토 화면을 열 때마다 목록(과 열어 둔 글)을 읽는다(읽기만 — 파일도 폴더도 만들지 않는다). 쓰는 중이면 읽지 않는다."""
        self.state.posts.start_load(**self.posts_bridge.callbacks())
        if self.state.posts.open_id is not None:
            self.state.posts.reload_detail(**self.post_detail_bridge.callbacks())

    def reload_posts(self, *_):
        job = self.state.posts.start_load(**self.posts_bridge.callbacks())
        if job is None:
            self.notify(T["load_busy"])
            return False
        self.render()
        return True

    def post_open(self, project_id):
        """글 줄을 눌러 상세를 연다(읽기뿐 — 글을 읽는 동안 '읽는 중' 이 보인다)."""
        status, _job = self.state.posts.start_open(project_id, **self.post_detail_bridge.callbacks())
        if status == "started":
            self.render()
            self._restore_focus("post:back")
        elif status == "busy":
            self.notify(T["load_busy"])

    def post_close(self):
        closed = self.state.posts.close_post()
        self.render()
        if closed:
            self._restore_focus("post:row:" + closed)

    def post_reload_detail(self, *_):
        job = self.state.posts.reload_detail(**self.post_detail_bridge.callbacks())
        if job is not None:
            self.render()

    def post_platform(self, key):
        if self.state.posts.select_platform(key):
            self.render()
            self._restore_focus("post:platform:" + key)

    def post_more(self):
        self.state.posts.show_more()
        self.render()
        self._restore_focus("post:more")

    # ---- 대화상자 도우미 ----
    def _post_present(self, form, title, discard):
        """대화상자에 안쪽 부품을 얹고 연다 — 열려 있던 확인창이 있으면 바뀌고(정리 훅이 불린다), 어느 길로든 닫히면 `discard` 가 칸을 비운다."""
        previous_focus = None if self.dialog.is_open else QApplication.focusWidget()
        self.dialog.clear()
        self.dialog.cleanups.append(discard)
        self.dialog.setAccessibleName(title)
        self.dialog.layout_.addWidget(form)
        form.show()
        if previous_focus is not None:
            self._dialog_return = previous_focus
        self.dialog.present(DIALOG_WIDTH)
        self._trap_focus(True, self.dialog)

    def _post_import_live(self):
        form = self.post_import_form
        return form if form is not None and self.state.posts.import_open and self.dialog.is_open else None

    def _post_pages_live(self):
        form = self.post_pages_form
        return form if form is not None and self.state.posts.pages_open and self.dialog.is_open else None

    def _post_record_live(self):
        form = self.post_record_form
        return form if form is not None and self.state.posts.record_open and self.dialog.is_open else None

    # ---- 가져오기 대화 ----
    def post_import(self):
        """`글 가져오기` — 대화상자를 연다(다른 대화상자가 열려 있거나 쓰는 중이면 열지 않는다). 입력 칸은 비어 있고 아무것도 읽거나 쓰지 않는다."""
        if self.dialog.is_open:
            return None
        if not self.state.posts.open_import():
            self.notify(T["post_busy"])
            return None
        form = ImportDialog(self, self.state.posts)
        self.post_import_form = form
        self._post_present(form, T["post_im_title"], self._post_import_discard)
        form.refresh()
        form.focus_start()
        return form

    def _post_import_discard(self):
        """대화상자가 닫히거나 바뀔 때 — 제목·본문 칸을 비우고(되돌리기 기록까지) 컨트롤러의 대화 상태를 닫는다. 여러 번 불러도 같다."""
        form, self.post_import_form = self.post_import_form, None
        if form is not None:
            form.discard()
        self.state.posts.close_import()                                               # 앱 닫기를 기다리던 표시도 함께 내려간다

    def post_import_kind(self, key):
        form = self._post_import_live()
        if form is not None and self.state.posts.set_import_kind(key):
            form.refresh()

    def post_import_pick(self):
        """`파일에서 읽기` — 파일 고르기(위치만) → 작업 스레드에서 안전하게 읽기(읽기뿐) → 본문 칸에 채우기. 고르지 않으면 아무 일도 없다."""
        form = self._post_import_live()
        if form is None:
            return None
        path = self._file_picker(self, T["post_im_pick_title"], f"{T['post_im_pick_filter']} ({IMPORT_FILTER})")
        if not path:
            return None
        status, _job = self.state.posts.start_read_file(path, **self.post_file_bridge.callbacks())
        if status == "started":
            form.refresh()
        else:
            self.notify(T["post_busy"])
        return status

    def post_import_start(self):
        """`가져오기` — 칸의 글을 이때 한 번 읽어 컨트롤러에 넘기고 작업 스레드에서 서비스가 검사·저장한다. 실패하면 대화는 열려 있고 칸의 글은 그대로다."""
        form = self._post_import_live()
        if form is None:
            return None
        status, _detail = self.state.posts.start_import(form.title_text(), form.body_text(), **self.posts_write_bridge.callbacks())
        if status == "restoring":
            self._notify_restoring()
        elif status == "busy":
            self.notify(T["post_busy"])
        form.refresh()
        return status

    def post_import_cancel(self):
        """`취소` — 입력이 있으면 닫기 전에 버릴지 먼저 묻는다(같은 대화 안의 확인 줄 — 확인 줄이 떠 있을 때 또 눌러도 닫지 않는다). 없으면 닫는다."""
        form = self._post_import_live()
        if form is None:
            return None
        result = self.state.posts.request_close_import()
        if result == "closed":
            self.close_dialog()
        elif result == "ask":
            form.refresh()
            form.focus_confirm()
        return result

    def post_import_escape(self):
        """Esc — 확인 줄이 떠 있으면 계속 쓰고, 아니면 `취소` 와 같다."""
        form = self._post_import_live()
        if form is None:
            return None
        if self.state.posts.import_ask:
            return self.post_import_discard_no()
        return self.post_import_cancel()

    def post_import_discard_yes(self):
        """`그래도 닫기` — 입력을 버리고 닫는다(앱 닫기를 기다리던 중이면 이어서 앱도 닫는다)."""
        if self._post_import_live() is None:
            return None
        quitting = self.state.posts.import_quit                                       # 정리 훅이 표시를 내리기 전에 읽어 둔다(앱 닫기(X)가 시작한 확인 줄일 때만 참)
        self.state.posts.close_import()
        self.close_dialog()
        if quitting:
            self.close()
        return "closed"

    def post_import_discard_no(self):
        """`계속 쓰기` — 닫기를 그만두고 입력을 이어 간다(앱 닫기를 기다리던 것도 거둔다)."""
        form = self._post_import_live()
        if form is not None:
            self.state.posts.keep_import()
            form.refresh()
            form.focus_start()

    def posts_guard_quit(self):
        """창 닫기(X·Alt+F4)가 왔다 — 가져오기 칸에 입력이 있으면 닫지 않고 같은 대화 안에서 버릴지 먼저 묻는다 → 막았으면 True. 입력이 없으면 False(그대로 닫는다).
        가져오는 중이면 닫지 않고 한 줄로 알린다(쓰기는 끝난 뒤에 다시 닫는다)."""
        posts = self.state.posts
        if not posts.has_unsaved():
            return False
        form = self._post_import_live()
        if form is None:                                                              # 대화 부품이 없는데 입력이 있다고 알리는 길 — 일반 확인창으로 묻는다
            dialog = posts.close_dialog()
            self.show_dialog(dialog["title"], dialog["body"], ok=dialog["ok"], cancel=dialog["cancel"], on_ok=lambda: (posts.close_import(), self.close()), safe_focus=True)
            return True
        if posts.request_quit() == "busy":
            self.notify(T["post_busy"])
            return True
        form.refresh()
        form.focus_confirm()
        return True

    # ---- 읽은 파일·쓰기 결과 받기 ----
    def _on_post_file_loaded(self, outcome):
        self._guarded(self._show_post_file_loaded, outcome, recover=self._recover_posts_write)

    def _on_post_file_failed(self, failure):
        self._guarded(self._show_post_file_failed, failure, recover=self._recover_posts_write)

    def _on_post_file_cancelled(self):
        self._guarded(self._show_post_file_failed, None, recover=self._recover_posts_write)

    def _show_post_file_loaded(self, outcome):
        form = self._post_import_live()
        replaced = form is not None and form.body_has_text()                          # 이미 친 본문이 있으면 파일의 글로 바뀐다 — 안내 줄이 되돌리는 법을 알린다(Ctrl+Z)
        file = self.state.posts.apply_file(outcome, replaced=replaced)
        if form is not None:
            form.fill(file.name, file.text)                                           # 글은 칸에 채우고 컨트롤러는 쥐지 않는다(`file.name` 은 어댑터가 이미 확장자를 뗀 제목 제안이다)
            form.refresh()
            form.focus_start()

    def _show_post_file_failed(self, failure):
        if failure is not None:
            self.state.posts.apply_file_failed(failure)
        form = self._post_import_live()
        if form is not None:
            form.refresh()

    # ---- 검토 시작 ----
    def post_review(self, platform):
        """`검토 시작`·`다시 검토` — Pages 는 검토 값 대화를 먼저 열고(분야·언어·대표 이미지 주소), 네이버는 바로 시작한다. 시작하면 서비스가 글을 그 플랫폼용으로 만들어 '검토 중' 으로 보내고 검사 결과를 돌려준다."""
        posts = self.state.posts
        if platform == PAGES:
            if self.dialog.is_open:
                return None
            raw = posts.open_pages()
            if raw is None:
                self.notify(T["post_approve_why_restoring"] if self.state.save_blocked() else T["post_busy"])
                return None
            form = PagesDialog(self, posts, raw)
            self.post_pages_form = form
            self._post_present(form, T["post_pv_title"], self._post_pages_discard)
            form.refresh()
            form.focus_start()
            return form
        status, _job = posts.start_review(platform, None, **self.posts_write_bridge.callbacks())
        self._post_start_notice(status)
        return status

    def _post_start_notice(self, status):
        """쓰기를 시작하려다 못 시작했을 때의 한 줄 안내, 시작했으면 '하는 중' 모습으로 다시 그린다."""
        if status == "started":
            self.render()
        elif status == "restoring":
            self._notify_restoring()
        elif status == "profile":
            self.notify(T["post_fail_profile"])
        elif status in ("state", "refused", "unconfirmed"):
            self.notify(T["post_fail_state"])
        elif status == "busy":
            self.notify(T["post_busy"])

    def _post_pages_discard(self):
        """Pages 값 대화가 닫히거나 바뀔 때(어느 길로든) — 칸의 값을 한 번 읽어 컨트롤러에 맡기고(이 앱을 연 동안만 기억한다 — 키 모양이 든 값은 기억하지 않는다) 칸을 비운다. 여러 번 불러도 같다."""
        form, self.post_pages_form = self.post_pages_form, None
        raw = None
        if form is not None:
            try:
                raw = form.values()
            except RuntimeError:                                                      # 이미 지워진 부품 — 기억할 값이 없다
                raw = None
            form.discard()
        self.state.posts.close_pages(raw)

    def post_pages_start(self):
        """Pages 값 대화의 `검토 시작` — 칸의 값을 이때 한 번 읽어 검사하고(문제가 있으면 서비스를 부르지 않고 칸 옆에 문장) 작업 스레드에서 검토를 시작한다."""
        form = self._post_pages_live()
        if form is None:
            return None
        status, _detail = self.state.posts.start_review(PAGES, form.values(), **self.posts_write_bridge.callbacks())
        form.refresh()
        if status == "invalid":
            form.focus_problem()
        elif status == "started":
            self.render()
        else:
            self._post_start_notice(status)
        return status

    def post_pages_cancel(self):
        if self._post_pages_live() is not None and not self.state.posts.busy:
            self.close_dialog()

    # ---- 승인·승인 취소 ----
    def post_approve(self):
        """`승인하기` — 승인할 수 있을 때만 **확인창**을 먼저 띄운다(처음 포커스는 취소). '승인' 을 눌러야 시작하고 취소·Esc 로 닫으면 '확인창을 보였다' 표시도 거둔다."""
        posts = self.state.posts
        if self.state.save_blocked():
            self._notify_restoring()
            return None
        dialog = posts.approve_dialog()
        if dialog is None:
            _ok, why = posts.approval()
            self.notify(T[why] if why else T["post_busy"])
            return None
        self.show_dialog(dialog["title"], dialog["body"], ok=dialog["ok"], cancel=dialog["cancel"], on_ok=self.post_approve_confirmed, safe_focus=True, on_cancel=posts.discard_approve)
        return dialog

    def post_approve_confirmed(self):
        status, detail = self.state.posts.start_approve(**self.posts_write_bridge.callbacks())
        if status == "refused":
            self.notify(T[detail] if detail else T["post_fail_state"])
            self.render()
        else:
            self._post_start_notice(status)
        return status

    def post_revoke(self):
        """`승인 취소` — 검토 중으로 되돌린다(되돌릴 수 있는 일이라 확인창은 없다)."""
        status, _job = self.state.posts.start_revoke(**self.posts_write_bridge.callbacks())
        self._post_start_notice(status)
        return status

    def post_approve_similarity(self):
        """`그래도 승인하기` — 두 블로그 글이 많이 비슷한 것을 알고도 승인한다(글 흐름 1b, D-646). 막힘이 유사도 하나뿐일 때만 **센 확인창**이 먼저 뜨고(처음 포커스는 취소), `그래도 승인` 을 눌러야 시작한다.
        취소·Esc 로 닫으면 '확인창을 보였다' 표시도 거둔다."""
        posts = self.state.posts
        if self.state.save_blocked():
            self._notify_restoring()
            return None
        dialog = posts.similarity_dialog()
        if dialog is None:
            _ok, why = posts.similarity_approval()
            self.notify(T[why] if why else T["post_busy"])
            return None
        self.show_dialog(dialog["title"], dialog["body"], ok=dialog["ok"], cancel=dialog["cancel"], on_ok=self.post_approve_similarity_confirmed, safe_focus=True, on_cancel=posts.discard_approve)
        return dialog

    def post_approve_similarity_confirmed(self):
        status, detail = self.state.posts.start_approve(similarity=True, **self.posts_write_bridge.callbacks())
        if status == "refused":
            self.notify(T[detail] if detail else T["post_fail_state"])
            self.render()
        else:
            self._post_start_notice(status)
        return status

    # ---- 복사용 패키지(글 흐름 1b) — 복사 단추는 클립보드뿐이고 상태를 바꾸지 않는다 ----
    def post_copy(self, kind):
        """복사 단추(`title`·`body`·`tags`·`all`)와 `주소 복사`(`url`) — 컨트롤러가 정한 글을 **셸의 기존 복사 길**(`copy` — 클립보드에 쓰고 다시 읽어 본다)로 보낸다. 네이버에 접속하지 않고 **상태를 바꾸지 않는다**
        (`복사했어요` 를 눌러야 복사함이 된다). 키·토큰 모양이 든 글은 복사하지 않고 이유를 알린다 → 복사했으면 True."""
        text, why = self.state.posts.copy_payload(kind)
        if text is None:
            self.notify(T[why], "error")
            return False
        if not self.copy(text):
            self.notify(T["post_pkg_copy_failed"], "error")
            return False
        self.notify(T["post_published_copied"] if kind == "url" else T[pv.COPY_TEXT[kind][2]])
        return True

    def post_copied(self):
        """`복사했어요` — 복사 준비됨 → 복사함(사람이 눌러야만 바뀐다)."""
        status, _job = self.state.posts.start_copied(True, **self.posts_write_bridge.callbacks())
        self._post_start_notice(status)
        return status

    def post_uncopied(self):
        """`복사 표시 취소` — 복사함 → 복사 준비됨."""
        status, _job = self.state.posts.start_copied(False, **self.posts_write_bridge.callbacks())
        self._post_start_notice(status)
        return status

    # ---- 발행 주소 기록 대화(글 흐름 1b) ----
    def post_record(self):
        """`발행 주소 기록` — 창 안 대화상자를 연다(복사함에서만, 다른 대화상자가 열려 있거나 쓰는 중이면 열지 않는다). 주소 칸은 비어 있고 아무것도 읽거나 쓰지 않는다."""
        if self.dialog.is_open:
            return None
        if not self.state.posts.open_record():
            self.notify(T["post_approve_why_restoring"] if self.state.save_blocked() else T["post_busy"])
            return None
        form = RecordDialog(self, self.state.posts)
        self.post_record_form = form
        self._post_present(form, T["post_rec_title"], self._post_record_discard)
        form.refresh()
        form.focus_start()
        return form

    def _post_record_discard(self):
        """대화상자가 닫히거나 바뀔 때(어느 길로든) — 주소 칸을 비우고 컨트롤러의 대화 상태를 닫는다. 여러 번 불러도 같다."""
        form, self.post_record_form = self.post_record_form, None
        if form is not None:
            form.discard()
        self.state.posts.close_record()

    def post_record_start(self):
        """`기록` — 칸의 주소를 이때 한 번 읽어 컨트롤러가 검사한다(걸리면 서비스를 부르지 않고 칸 옆에 이유). 통과하면 작업 스레드에서 서비스가 한 번 더 거르고 기록한다. 실패하면 대화는 열려 있고 칸의 글은 그대로다."""
        form = self._post_record_live()
        if form is None:
            return None
        status, _detail = self.state.posts.start_record(form.value(), **self.posts_write_bridge.callbacks())
        form.refresh()
        if status == "invalid":
            form.focus_problem()
        elif status == "started":
            self.render()
        else:
            self._post_start_notice(status)
        return status

    def post_record_cancel(self):
        if self._post_record_live() is not None and not self.state.posts.busy:
            self.close_dialog()

    # ---- 읽기 결과 받기 ----
    def _on_posts_loaded(self, data):
        self._guarded(self._show_posts_loaded, data, recover=self._recover_posts)

    def _on_posts_failed(self, failure):
        self._guarded(self._show_posts_failed, failure, recover=self._recover_posts)

    def _on_posts_cancelled(self):
        self._guarded(self._show_posts_cancelled, recover=self._recover_posts)

    def _show_posts_loaded(self, data):
        if not self.state.posts.apply_loaded(data):                                   # 읽는 동안 쓰기가 끝났다 — 쓰기 전 목록이라 버리고 다시 읽는다
            self.state.posts.start_load(**self.posts_bridge.callbacks())
        self._render_posts()

    def _show_posts_failed(self, failure):
        self.state.posts.apply_load_failed(failure, self.clock.now())
        self._render_posts()

    def _show_posts_cancelled(self):
        self.state.posts.apply_cancelled()
        self._render_posts()

    def _on_post_detail_loaded(self, detail):
        self._guarded(self._show_post_detail_loaded, detail, recover=self._recover_posts)

    def _on_post_detail_failed(self, failure):
        self._guarded(self._show_post_detail_failed, failure, recover=self._recover_posts)

    def _on_post_detail_cancelled(self):
        self._guarded(self._render_posts, recover=self._recover_posts)

    def _show_post_detail_loaded(self, detail):
        posts = self.state.posts
        if posts.apply_detail(detail):
            self._render_posts()
        elif detail is not None and detail.project_id == posts.open_id and posts.is_stale(detail):
            posts.reload_detail(keep_notice=True, **self.post_detail_bridge.callbacks())   # 읽는 동안 쓰기가 끝났다 — 쓰기 전 모습이라 버리고 다시 읽는다(방금 쓰기 결과를 알린 안내는 남긴다)

    def _show_post_detail_failed(self, failure):
        posts = self.state.posts
        result = posts.apply_detail_failed(failure, self.clock.now())
        if result == "ignored":
            return
        if result == "gone":
            posts.start_load(**self.posts_bridge.callbacks())                          # 글이 사라졌다 — 목록을 다시 읽는다
        elif result == "stale":
            posts.reload_detail(keep_notice=True, **self.post_detail_bridge.callbacks())   # 읽는 동안 쓰기가 끝났다 — 다시 읽는다
            return
        self._render_posts()

    def _recover_posts(self, error):
        """글 검토 슬롯에서 예외가 났다 — 받아 둔 값을 버리고 쉬운 문장의 오류 상태로(예외 이름만 진단 정보에). 오류 화면마저 못 그리면 안내만 한다."""
        report_unexpected(type(error), error)
        self.state.posts.apply_unexpected(error, self.clock.now())
        try:
            self._render_posts()
        except Exception:
            self.notify(T["job_failed"])

    # ---- 쓰기 결과 받기 ----
    def _on_posts_written(self, outcome):
        self._guarded(self._show_posts_written, outcome, recover=self._recover_posts_write)

    def _on_posts_write_failed(self, failure):
        self._guarded(self._show_posts_write_failed, failure, recover=self._recover_posts_write)

    def _on_posts_write_cancelled(self):
        self._guarded(self._show_posts_write_failed, None, recover=self._recover_posts_write)

    def _show_posts_written(self, outcome):
        todo = self.state.posts.apply_write_ok(outcome)
        self._post_close_finished_forms()                                             # 가져왔다·검토를 시작했다 — 대화를 닫고(정리 훅이 칸을 비운다) 그 글의 상세를 보인다
        if todo.get("reload_list"):
            self.state.posts.start_load(**self.posts_bridge.callbacks())
        self._render_posts()
        self._restore_focus({"imported": "post:back", "reviewed": "post:approve", "approved": "post:revoke", "revoked": "post:review", "copied": "post:record", "uncopied": "post:copied", "recorded": "post:copy:url"}.get(outcome.kind, ""))

    def _show_posts_write_failed(self, failure):
        todo = self.state.posts.apply_write_failed(failure)
        for form in (self._post_import_live(), self._post_pages_live(), self._post_record_live()):
            if form is not None:
                form.refresh()                                                        # 이유는 대화 안에 보이고 칸의 글은 그대로다
        self._post_close_finished_forms()
        if todo.get("reload"):                                                        # 글이 바뀌었거나 사라졌거나 상태가 달라졌다 — 최신 모습을 다시 읽는다(읽기만)
            self.state.posts.start_load(**self.posts_bridge.callbacks())
            self.state.posts.reload_detail(keep_notice=True, **self.post_detail_bridge.callbacks())   # 왜 다시 읽는지 알리는 안내('글이 바뀌었어요 …')는 남긴다
        self._render_posts()

    def _post_close_finished_forms(self):
        """컨트롤러가 대화를 이미 닫은(가져오기 성공·검토 시작 성공·낡음) 뒤에도 대화 부품이 남아 있으면 닫는다 — 정리 훅이 칸을 비운다. 대화상자가 이미 다른 것으로 바뀌었으면 훅만 부른다."""
        finished = (self.post_import_form is not None and not self.state.posts.import_open) or (self.post_pages_form is not None and not self.state.posts.pages_open) or (self.post_record_form is not None and not self.state.posts.record_open)
        if not finished:
            return
        if self.dialog.is_open:
            self.close_dialog()
            return
        if self.post_import_form is not None and not self.state.posts.import_open:
            self._post_import_discard()
        if self.post_pages_form is not None and not self.state.posts.pages_open:
            self._post_pages_discard()
        if self.post_record_form is not None and not self.state.posts.record_open:
            self._post_record_discard()

    def _recover_posts_write(self, error):
        report_unexpected(type(error), "")
        self.state.posts.apply_write_unexpected(error)
        try:
            self._post_close_finished_forms()                                         # 컨트롤러가 이미 닫은 대화의 부품이 남아 있으면 닫는다(안 그러면 Esc·단추가 모두 무동작인 대화가 남는다)
            self._render_posts()
        except Exception:
            self.notify(T["job_failed"])

    def _posts_close_wait(self):
        """창을 닫을 때 글 쓰기가 돌고 있으면 끝나기를 기다린다(한 트랜잭션이라 중간에 끊지 않는다)."""
        if self.state.posts.busy:
            job = self.state.runner.job(pv.WRITE_KEY)
            if job is not None:
                job.join(WRITE_CLOSE_WAIT)
