"""'사진 정리' 화면(사진 연동 초안 2단계, 결정 D-499 이후)의 문구 — `text.py` 의 `T` 에 합쳐진다(`T.update(PHOTO_T)`). 쉬운 한국어(해요체)로 새로 썼고, 결과를 약속하는 표현(`FORBIDDEN`)·영문 오류 코드·`Traceback` 같은 글은 없다.
이 파일에는 사용자가 적은 글·파일 경로·파일 이름이 없다(글과 이름은 화면의 입력 칸·목록 줄에만 나타난다). 파일을 고르지 못한 이유는 `ui/core/imagerules.py` 의 문장(`img_local_*`)과 `content/photo_manifest.py` 가 낸 고정 문장을 그대로 쓴다.
"""
from __future__ import annotations

PHOTO_T = {
    # 초안 작성 화면 — 오른쪽 '사진' 카드와 '만드는 방법' 칸의 한 줄(둘 다 사진 정리 창을 연다)
    "pho_card_title": "사진", "pho_card_none": "넣은 사진이 없어요", "pho_card_count": "사진 {n}장 · 확인 {c}/{n}", "pho_card_count_a11y": "넣은 사진 {n}장 중 {c}장을 확인했어요",
    "pho_card_open": "사진 정리 열기", "pho_card_open_a11y": "사진 정리 열기 — 글에 넣을 사진을 고르고 설명을 적는 창", "pho_card_add": "사진 넣기", "pho_card_add_a11y": "사진 넣기 — 글에 넣을 사진을 고르는 창",
    "pho_card_hint": "사진은 이 컴퓨터 안에서만 쓰고 밖으로 보내지 않아요. 사진을 넣지 않아도 초안은 그대로 만들어져요.",
    "pho_card_unsaved": "사진 정보를 고쳤어요. 초안을 저장해야 사진 정보도 함께 저장돼요.",
    "pho_card_trash": "지운 초안의 사진 정보를 되돌릴 사본으로 남겨 뒀어요. 사진 파일은 그대로 있어요.",
    "pho_gate_photos": "사진 자리 {n}가지가 본문과 맞지 않아요",
    "pho_gate_dangling": "사진 정리에 없는 사진을 가리키는 자리가 있어요: {numbers}번",
    "pho_gate_unconfirmed": "‘확인했어요’ 를 켜지 않은 사진의 자리가 본문에 있어요: {numbers}번",
    "pho_gate_missing": "‘확인했어요’ 를 켠 사진인데 본문에 자리가 없어요: {numbers}번",
    "pho_gate_repeated": "같은 사진의 자리가 본문에 두 번 이상 있어요: {numbers}번",
    "pho_gate_order": "본문의 사진 자리 순서가 사진 정리의 순서와 달라요",
    "pho_gate_stray": "사진 자리가 아닌 ‘{{{{ }}}}’ 괄호가 {n}개 있어요 — 복사하면 글자 그대로 남아요",
    "pho_gate_uploads": "올릴 사진 {n}장 — 네이버 편집기에서 이 순서로 올려 주세요",
    "pho_gate_upload_line": "[이미지 {n}] 사진 {n}번 · {name}",
    "pho_gate_no_name": "이름을 보일 수 없어요",
    "pho_upload_title": "올릴 사진 순서를 알려 드려요",
    "pho_gate_paths": "본문에 파일 경로처럼 보이는 글이 있어요(사진 메모·설명에 붙여 넣은 경로일 수 있어요) — 복사하면 그대로 들어가요", "pho_paths_title": "복사하기 전에 알려 드려요",
    "pho_upload_tail": "복사하면 본문의 사진 자리가 [이미지 N] 표시로 바뀌어요. 편집기에서 그 자리에 사진을 올리고 표시 글을 지워 주세요. 사진 파일은 앱이 올리지 않아요.",
    "pho_upload_ok": "복사하기",
    "pho_card_remake": "사진 정보를 바꿨어요. 본문에 반영하려면 ‘만드는 방법 바꾸기’ 를 열고 ‘다시 만들기’ 를 눌러 주세요.",
    "pho_make_blocked": "사진 정보에 키처럼 보이는 글이 있어 초안을 만들지 않았어요. 사진 정리에서 그 글을 지운 뒤 다시 시도해 주세요.",
    "pho_restore_blocked": "지금 사진이 있어서 되돌릴 수 없어요. 사진을 모두 지운 뒤에 되돌려 주세요(저장해 둔 사진 정보에 사진이 있으면 그때도 되돌릴 수 없어요).",
    "pho_restore_btn": "사진 정보 되돌리기", "pho_restore_btn_a11y": "되돌릴 사본에서 사진 정보 되돌리기", "pho_trash_clear_btn": "사진 정보 사본 비우기", "pho_trash_clear_btn_a11y": "사진 정보 사본 비우기 — 비우면 되돌릴 수 없어요",
    "pho_trash_clear_ask": "사진 정보 사본을 비울까요? 비우면 사진 정보를 되돌릴 수 없어요. 사진 파일은 그대로 있어요.", "pho_trash_clear_yes": "사본 비우기", "pho_trash_clear_no": "그만두기",
    "pho_restored_notice": "사진 정보를 되돌렸어요.", "pho_trash_cleared_notice": "사진 정보 사본을 비웠어요.", "pho_restore_fail": "사진 정보를 되돌리지 못했어요.", "pho_restore_missing": "되돌릴 사진 정보 사본이 없어요.", "pho_trash_clear_fail": "사진 정보 사본을 비우지 못했어요.",
    "pho_savefail_leave_title": "사진 정보를 저장하지 못했어요", "pho_savefail_leave_tail": "그래도 나가면 고친 사진 정보가 사라져요. 계속 고치기를 누르면 이 화면에서 다시 저장할 수 있어요.",
    "pho_choice_discard_leave": "사진 정보 없이 나가기", "pho_choice_discard_close": "사진 정보 없이 닫기",
    "pho_save_fail": "초안은 저장했지만 사진 정보는 저장하지 못했어요. 다시 저장해 보세요.", "pho_deleted_trash": "사진 정보는 되돌릴 사본으로 남겨 뒀어요. 이 초안을 백업에서 되살리면 되돌릴 수 있어요.", "pho_deleted_trash_fail": "사진 정보를 사본으로 옮기지 못했어요. 사진 정보 파일은 그대로 남아 있어요.",
    "pho_card_lost_broken": "저장해 둔 사진 정보 파일을 읽을 수 없어서 이 초안의 사진 정보는 저장되지 않아요. 지금 넣은 사진 정보는 이 화면을 떠나면 사라져요.",
    "pho_card_lost_unreadable": "저장해 둔 사진 정보 파일을 지금은 열 수 없어서 사진 정보를 저장하지 않아요. 지금 넣은 사진 정보는 이 화면을 떠나면 사라져요. 초안을 다시 열면 저장할 수 있게 될 수 있어요.",
    "pho_leave3_lost": "넣어 둔 사진 정보는 저장해 둔 사진 정보 파일을 읽을 수 없어서 저장되지 않아요.",
    "pho_restore_blocked_file": "저장해 둔 사진 정보 파일을 읽을 수 없는 상태라서 지금은 되돌릴 수 없어요.",
    "pho_saved_without_photos": "사진 정보는 저장하지 않았어요.", "pho_saved_with_note": "{saved} · {note}",
    "pho_open_broken": "저장한 사진 정보 파일을 읽을 수 없어요. 파일은 그대로 두었어요.", "pho_open_unreadable": "저장한 사진 정보 파일을 지금은 열 수 없어요. 잠시 뒤에 다시 열어 주세요.",
    "pho_row_title": "사진 넣기(선택)", "pho_row_desc": "글에 넣을 사진을 고르고 사진마다 한마디를 적어 두면 돼요.",
    # 창 머리
    # 3단계(초안 연결)가 열려 N-1 의 세 문구(`STAGE3_RESTORE_KEYS`: pho_intro·pho_all_ask·pho_confirm)를 사실이 되는 원래 글로 되돌렸다
    "pho_title": "사진 정리", "pho_intro": "글에 넣을 사진을 고르고, 사진마다 무엇인지 적어 주세요. 확인했다고 표시한 사진만 초안에 쓰여요. 사진 파일은 복사하지 않고, 이 컴퓨터 안에서만 쓰고, 밖으로 보내지 않아요.",
    "pho_limits": "사진은 {n}장까지 넣을 수 있어요. 대상은 {subject}자, 메모는 {note}자, 설명 글은 {caption}자까지예요.",
    "pho_count": "사진 {n}장 · 확인 {c}/{n}", "pho_count_a11y": "넣은 사진 {n}장, 그중 {c}장을 확인했어요",
    "pho_empty": "아직 넣은 사진이 없어요. 아래 ‘사진 추가’ 를 눌러 JPG·PNG·WebP 사진을 골라 주세요.",
    "pho_full": "사진이 {n}장이라 더 넣을 수 없어요. 쓰지 않을 사진을 지운 뒤 다시 추가해 주세요.",
    # 단추
    "pho_add": "사진 추가", "pho_add_a11y": "사진 추가 — 파일 선택 창에서 사진을 여러 장 고르기", "pho_pick_title": "넣을 사진 고르기", "pho_pick_filter": "사진 파일",
    "pho_confirm_all": "모두 확인했어요", "pho_confirm_all_a11y": "모든 사진을 확인했다고 표시하기",
    "pho_close": "닫기", "pho_close_a11y": "사진 정리 닫기", "pho_undo": "지운 사진 되돌리기", "pho_undo_a11y": "방금 지운 사진 되돌리기",
    # 한꺼번에 확인하는 확인 줄
    # 3단계(초안 연결)가 열려 사실이 되는 원래 글로 되돌렸다 — N-1
    "pho_all_ask": "사진 {n}장을 모두 ‘확인했어요’ 로 표시할까요? 표시한 사진의 대상·설명 글·메모가 초안에 쓰여요(‘다시 만들기’ 를 누르면 들어가요).", "pho_all_yes": "{n}장 모두 확인", "pho_all_yes_a11y": "사진 {n}장을 모두 확인했다고 표시하기", "pho_all_no": "그만두기", "pho_all_no_a11y": "한꺼번에 확인하지 않고 그만두기",
    "pho_all_none": "확인하지 않은 사진이 없어요.", "pho_all_done": "사진 {n}장을 확인했다고 표시했어요.",
    # 못 넣은 파일
    "pho_rejected_title": "넣지 못한 파일", "pho_rejected_row": "{name} — {reason}", "pho_rejected_clear": "목록 지우기", "pho_rejected_clear_a11y": "넣지 못한 파일 목록 지우기",
    "pho_rejected_dup": "이미 넣은 사진이에요.", "pho_rejected_full": "사진은 {n}장까지만 넣을 수 있어요.", "pho_added": "사진 {n}장을 넣었어요.",
    "pho_rejected_more_full": "외 {n}개는 사진을 {max}장까지만 넣을 수 있어서 넣지 못했어요.", "pho_rejected_more_other": "외 {n}개도 넣지 못했어요.",
    "pho_chip_hint": "{n}개 중 {m}번째예요. 방향키로 옮기고 스페이스나 엔터로 골라요.",
    # 사진 한 줄
    "pho_row_label": "사진 {n}", "pho_row_a11y": "사진 {n}, 종류 {type}, {confirm}", "pho_row_confirmed": "확인했어요", "pho_row_unconfirmed": "아직 확인하지 않았어요",
    "pho_type": "종류", "pho_type_a11y": "사진 {n} 종류", "pho_setting": "장소 분위기", "pho_setting_a11y": "사진 {n} 장소 분위기", "pho_setting_none": "정하지 않음",
    "pho_subject": "이 사진은 무엇인가요?", "pho_subject_a11y": "사진 {n} 대상 — 이 사진은 무엇인가요", "pho_subject_example": "예: {example}",
    "pho_note": "한마디 메모(선택)", "pho_note_a11y": "사진 {n} 한마디 메모", "pho_note_example": "예: 비 오는 날 갔어요. 사진 앞뒤에 넣고 싶은 말을 적어요.",
    "pho_count_text": "{n}/{limit}", "pho_over": "{limit}자까지만 적을 수 있어요. 지금 {n}자예요.",
    "pho_place_open": "자리 정하기 ▸", "pho_place_close": "자리 정하기 ▾", "pho_place_a11y": "사진 {n} 들어갈 곳과 자리 정하기",
    "pho_section": "들어갈 곳", "pho_section_a11y": "사진 {n} 들어갈 곳", "pho_section_auto": "자동", "pho_section_intro": "도입", "pho_section_content": "내용 소제목", "pho_section_mood": "분위기 소제목", "pho_section_closing": "마무리",
    "pho_place": "자리", "pho_place_kind_a11y": "사진 {n} 자리", "pho_place_auto": "자동", "pho_place_top": "글 맨 앞", "pho_place_after_heading": "소제목 바로 뒤", "pho_place_after_paragraph": "문단 뒤", "pho_place_between_sentences": "문장 사이",
    "pho_nth": "몇 번째", "pho_nth_less": "−", "pho_nth_less_a11y": "사진 {n} 몇 번째 하나 줄이기", "pho_nth_more": "+", "pho_nth_more_a11y": "사진 {n} 몇 번째 하나 늘리기", "pho_nth_value": "{k}번째",
    "pho_caption": "설명 글(선택)", "pho_caption_a11y": "사진 {n} 설명 글", "pho_caption_example": "예: 기본 반찬",
    # 3단계(초안 연결)가 열려 사실이 되는 원래 글로 되돌렸다 — N-1
    "pho_confirm": "확인했어요 — 이 내용을 초안에 써요", "pho_confirm_a11y": "사진 {n} 확인했어요", "pho_unconfirmed_note": "내용을 고쳐서 확인 표시를 풀었어요. 다시 확인해 주세요.",
    "pho_up": "위로", "pho_up_a11y": "사진 {n} 위로 옮기기", "pho_down": "아래로", "pho_down_a11y": "사진 {n} 아래로 옮기기", "pho_remove": "지우기", "pho_remove_a11y": "사진 {n} 목록에서 지우기",
    "pho_removed": "사진 {n}번을 목록에서 지웠어요. 파일은 그대로 있어요.", "pho_restored": "지운 사진을 되돌렸어요.",
    # 파일 상태 배지
    "pho_file_ok": "파일 있음", "pho_file_ok_size": "파일 있음 · {w}×{h}", "pho_file_missing": "파일 없음", "pho_file_link": "링크라서 쓰지 않아요", "pho_file_cloud": "내려받지 않은 파일이에요", "pho_file_toobig": "너무 커요(20MB까지)",
    "pho_file_unsupported": "지원하지 않는 형식이에요", "pho_file_notimage": "사진 파일이 아니에요", "pho_file_notfile": "파일이 아니에요", "pho_file_unreadable": "읽지 못했어요", "pho_file_unknown": "아직 확인하지 않았어요",
    "pho_file_a11y": "사진 {n} 파일 상태 {status}", "pho_relink": "다시 찾기", "pho_relink_a11y": "사진 {n} 파일 다시 찾기", "pho_relink_title": "다시 찾을 사진 고르기", "pho_relinked": "사진 파일을 다시 연결했어요.",
    # 미리보기
    "pho_preview_blocked": "너무 커서 미리보기를 못 만들어요", "pho_preview_failed": "미리보기를 만들지 못했어요", "pho_preview_wait": "미리보기를 만드는 중이에요", "pho_preview_a11y": "사진 {n} 미리보기", "pho_preview_none": "미리보기 없음",
    # 목록 고치기(이 앱을 켜 두는 동안만 — 저장하지 않는다)
    "pho_lists_open": "종류·장소 분위기 목록 고치기 ▸", "pho_lists_close": "종류·장소 분위기 목록 고치기 ▾", "pho_lists_a11y": "종류와 장소 분위기 목록 고치기",
    "pho_lists_note": "여기서 더하고 지운 목록은 앱을 닫으면 처음 목록으로 돌아가요.", "pho_lists_type_title": "사진 종류", "pho_lists_setting_title": "장소 분위기",
    "pho_lists_new_type": "새 종류 이름", "pho_lists_new_type_a11y": "새 사진 종류 이름", "pho_lists_add_type": "종류 더하기", "pho_lists_add_type_a11y": "새 사진 종류 더하기",
    "pho_lists_new_setting": "새 장소 분위기 이름", "pho_lists_new_setting_a11y": "새 장소 분위기 이름", "pho_lists_add_setting": "분위기 더하기", "pho_lists_add_setting_a11y": "새 장소 분위기 더하기",
    "pho_lists_remove_a11y": "{name} 목록에서 지우기", "pho_lists_in_use": "사진에서 쓰고 있어서 지울 수 없어요.", "pho_lists_dup": "이미 있는 이름이에요.", "pho_lists_keep": "‘기타’ 는 지울 수 없어요.",
    "pho_lists_full": "목록에는 {n}개까지 둘 수 있어요.", "pho_lists_added": "목록에 더했어요.", "pho_lists_removed": "목록에서 지웠어요.",
    # 안내·거절
    "pho_over_close": "반영하지 못한 글이 있어요({fields}). 고치거나 줄여 주세요. 그대로 한 번 더 닫기를 누르면 그 글은 버리고 닫아요.",
    "pho_field_of": "사진 {n} {field}", "pho_field_more": "외 {n}곳", "pho_field_user_subject": "대상", "pho_field_user_note": "한마디 메모", "pho_field_caption": "설명 글",
    # 넣지 못한 파일이 있을 때의 안내(상태 줄) — 넣지 못한 파일의 목록은 사진 줄들 아래에 있다(N-5)
    "pho_added_some": "사진 {n}장을 넣었어요. {m}개는 넣지 못했어요 — 아래 ‘넣지 못한 파일’ 에서 이유를 확인해 주세요.", "pho_added_none": "고른 파일 {m}개를 넣지 못했어요 — 아래 ‘넣지 못한 파일’ 에서 이유를 확인해 주세요.",
    # 초안 화면을 떠나거나 앱을 닫을 때의 확인창 — 초안이 아직 없거나 저장할 수 없는 상태(깨졌거나 못 연 사진 정보 파일)라 사진 정보를 저장할 길이 없으면 떠날 때 사라진다(N-2, 3단계 PS-2)
    "pho_leave_title": "사진 정보가 사라져요", "pho_leave_body": "넣어 둔 사진 {n}장의 정보는 아직 저장되지 않아서 다른 화면으로 가면 사라져요. 사진 파일은 그대로 있어요. 그래도 이동할까요?",
    "pho_close_body": "넣어 둔 사진 {n}장의 정보는 아직 저장되지 않아서 앱을 닫으면 사라져요. 사진 파일은 그대로 있어요. 그래도 닫을까요?", "pho_bad_photo": "그 사진을 찾을 수 없어요.", "pho_bad_value": "그 값은 쓸 수 없어요.", "pho_bad_order": "더 옮길 수 없어요.", "pho_fail_other": "사진 정보를 바꾸지 못했어요. 다시 해 주세요.",
}

# 2단계 수정(검증 Q N-1)은 초안 연결이 없는 동안 세 문구를 '다음 단계에서 열려요' 로 적어 두었다. 3단계(초안 연결 — `draft_inputs` 를 쓰는 `drafts_view`)가 열려 아래 세 문구는 사실이 되는 원래 글로 되돌렸다.
# 이 키 목록은 시험이 두 문구가 서로 어긋나지 않는지 보는 자리로 남겨 둔다.
STAGE3_RESTORE_KEYS = ("pho_intro", "pho_all_ask", "pho_confirm")
