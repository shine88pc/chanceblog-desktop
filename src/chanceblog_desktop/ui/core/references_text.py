"""'참고 글 보관함'(결정 D-490)의 문구 — `text.py` 의 `T` 에 합쳐진다(`T.update(REF_T)`). 쉬운 한국어로 새로 썼고, 결과를 약속하는 표현(`FORBIDDEN`)·영문 오류 코드·예외 글은 없다.
이 파일에는 보관한 글의 문장·제목이 없다(글은 보관함 파일과 편집 칸에만 있다). 거절·실패 문장은 서비스가 준 고정 문장이거나 여기의 고정 문장이다."""
from __future__ import annotations

REF_T = {
    # 진입 — '내 글 문체 참고값 보기' 대화상자 안의 단추 하나
    "ref_entry_open": "참고 글 보관함 열기", "ref_entry_open_a11y": "참고 글 보관함 열기 — 참고할 글을 보관하고 고쳐 쓰는 창",
    # 대화상자 머리
    "ref_title": "참고 글 보관함",
    "ref_intro": "참고하고 싶은 글을 이 컴퓨터에 보관해 두고, 다시 열어 고쳐 쓸 수 있어요. 프로그램을 닫아도 남아요. 글을 AI 나 인터넷으로 보내지 않아요.",
    "ref_limits": "글은 {n}개까지, 제목은 {title}자까지, 본문은 {body}자까지 보관해요. 전체 백업에는 담기지 않아요.",
    # 목록
    "ref_list_title": "보관한 글", "ref_list_a11y": "보관한 글 목록", "ref_list_loading": "보관한 글을 읽는 중이에요…",
    "ref_list_empty": "아직 보관한 글이 없어요. 아래에 글을 붙여 넣어 저장하거나 파일에서 올려 주세요.",
    "ref_row": "{title} · {chars}자 · {when}", "ref_row_a11y": "{title}, {chars}자, 고친 때 {when}", "ref_row_selected_a11y": "{title}, {chars}자, 고친 때 {when}, 지금 편집 중",
    "ref_open": "열기", "ref_open_a11y": "{title} 열어서 고치기",
    "ref_skipped": "읽을 수 없어 건너뛴 파일이 {n}개 있어요. 보관함 폴더에서 직접 확인해 주세요.",
    "ref_count": "{n}개 보관 중",
    # 편집 칸
    "ref_editor_new": "새 글 올리기", "ref_editor_edit": "글 고치기",
    "ref_title_label": "제목", "ref_title_a11y": "참고 글 제목", "ref_title_hint": "제목은 80자까지예요.",
    "ref_body_label": "본문", "ref_body_a11y": "참고 글 본문", "ref_body_hint": "붙여 넣거나 직접 고쳐 쓸 수 있어요. 10만 자까지예요.",
    "ref_body_count": "{n}자", "ref_body_count_a11y": "본문 글자 수 {n}자",
    "ref_dirty": "저장하지 않은 변경이 있어요.", "ref_clean": "저장된 상태예요.",
    # 단추
    "ref_save": "저장", "ref_save_a11y": "참고 글 저장",
    "ref_new": "새 글", "ref_new_a11y": "새 글 올리기 — 편집 칸 비우기",
    "ref_pick": "파일에서 올리기", "ref_pick_a11y": "글 파일에서 참고 글 올리기", "ref_pick_title": "참고 글 파일 고르기", "ref_pick_filter": "글 파일",
    "ref_delete": "지우기", "ref_delete_a11y": "열려 있는 참고 글 지우기",
    "ref_close": "닫기", "ref_close_a11y": "참고 글 보관함 닫기",
    # 지우기 확인(두 단계)
    "ref_delete_q1": "이 글을 보관함에서 지울까요?", "ref_delete_q2": "정말 지울까요? 지운 글은 되돌릴 수 없어요.",
    "ref_delete_next": "계속", "ref_delete_next_a11y": "지우기 계속 — 한 번 더 확인해요", "ref_delete_yes": "지우기", "ref_delete_yes_a11y": "참고 글을 지우기 — 되돌릴 수 없어요",
    "ref_delete_no": "그만두기", "ref_delete_no_a11y": "지우지 않고 그만두기",
    # 저장하지 않은 변경 확인
    "ref_discard_q": "저장하지 않은 변경이 있어요. 버리고 다른 글을 열까요?", "ref_discard_yes": "버리고 열기", "ref_discard_no": "계속 고치기",
    # 폴더 위치
    "ref_folder_label": "보관함 폴더 위치", "ref_folder_note": "글 하나가 파일 하나로 들어 있어요. 이 폴더의 파일을 직접 지우거나 고치지 마세요.",
    # 결과 안내
    "ref_done_added": "보관했어요.", "ref_done_saved": "저장했어요.", "ref_done_deleted": "지웠어요.", "ref_done_file": "파일에서 올렸어요.",
    "ref_note_cp949": "옛 메모장 글자 모양(CP949)으로 읽었어요. 글자가 깨져 보이면 UTF-8 로 저장해 다시 올려 주세요.",
    "ref_fail_load": "보관한 글을 읽지 못했어요. 파일은 고치거나 지우지 않았어요.", "ref_fail_open": "글을 열지 못했어요. 다시 목록을 불러와 주세요.",
    "ref_fail_other": "처리하지 못했어요. 잠시 뒤 다시 해 주세요.", "ref_none_selected": "먼저 목록에서 글을 열어 주세요.",
    "ref_running": "처리하는 중이에요…",
}
