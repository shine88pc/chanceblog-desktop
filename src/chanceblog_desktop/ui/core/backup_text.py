"""백업·복원 카드(설정 화면)의 문구 — `text.py` 의 `T` 에 합쳐진다(`T.update(BACKUP_T)`). 쉬운 한국어(해요체)로 새로 썼고, 결과를 약속하는 표현(`FORBIDDEN`)·영문 상태 이름·오류 코드는 쓰지 않는다.

이 파일에는 키·키의 일부·실제 블로그 이름·경로가 없다. 문장에 들어가는 `{…}` 자리는 시각·크기·개수·파일 종류 이름(글 보관함 …)·폴더 위치 글자뿐이고 키 값은 어느 문장에도 들어가지 않는다.
'Credential 제외됨' 과 '키·토큰·쿠키·세션은 이 백업에 없어요' 문장은 백업 목록 파일(`security/backup_note.py`)에 적히는 글과 같다(시험이 맞춰 본다).
"""
from __future__ import annotations

BACKUP_T = {
    # 카드 머리·안내
    "backup_title": "백업·복원", "backup_sample_tag": "예시", "backup_a11y": "백업·복원, 만들어 둔 백업 {n}개",
    "backup_desc": "글·저장한 초안·주제 후보·Seed·프로필·설정을 한 묶음으로 저장해 둬요. 키는 백업에 들어가지 않아요.",
    "backup_sample_note": "지금 보이는 백업은 모두 예시예요. 이 화면에서는 아무것도 저장하거나 바꾸지 않아요.",
    "backup_now": "지금 백업", "backup_now_a11y": "지금 전체 백업 만들기",
    "backup_location": "백업 위치: {path}",
    "backup_copy_tip": "이 백업은 이 컴퓨터 안에만 있어요. 컴퓨터가 고장 나도 되찾으려면 위 폴더를 USB 나 다른 PC 에 직접 복사해 두세요. 앱이 밖으로 보내지는 않아요.",
    "backup_keep": "가장 최근 {n}개까지만 남기고 더 오래된 것은 지워요.",
    "backup_credential_line": "자격 증명(키·토큰·쿠키·세션)은 이 백업에 들어 있지 않아요 — 복원한 뒤 키는 다시 등록하세요",
    "backup_credential_badge": "Credential 제외됨", "backup_credential_a11y": "Credential 제외됨 — 키·토큰·쿠키·세션은 이 백업에 들어 있지 않아요",
    "backup_excluded_show": "백업에 들어 있지 않은 것 보기", "backup_excluded_hide": "백업에 들어 있지 않은 것 접기", "backup_excluded_intro": "백업에는 아래 것이 들어 있지 않아요.",
    "backup_list_title": "만들어 둔 백업", "backup_list_note": "‘복원 직전 사본’ 은 복원하기 직전의 데이터를 앱이 자동으로 남겨 둔 것이에요. 잘못 복원했을 때 그 사본으로 다시 복원할 수 있어요.",
    # 줄
    "backup_row_backup": "{when} 백업", "backup_row_safety": "{when} 복원 직전 사본", "backup_row_unknown": "시각을 알 수 없는 {kind}",
    "backup_kind_backup": "백업", "backup_kind_safety": "복원 직전 사본",
    "backup_status_complete": "완료", "backup_status_partial": "부분", "backup_status_broken": "깨짐",
    "backup_status_desc_complete": "있는 것을 모두 담았어요", "backup_status_desc_partial": "일부는 담지 못했어요",
    "backup_size": "크기 {size}", "backup_contents": "담긴 것: {text}", "backup_skipped": "담지 못한 것: {text}", "backup_missing": "아직 없던 것: {text}",
    "backup_item_projects": "글 {n}개", "backup_item_drafts": "저장한 초안 {n}개", "backup_item_candidates": "주제 후보 {n}개", "backup_item_engine": "추천 후보 {n}개",
    "backup_item_profiles": "채널 프로필 {n}개", "backup_item_seeds": "Seed {n}개", "backup_item_calendar": "캘린더 항목 {n}개", "backup_item_settings": "설정", "backup_item_naver": "옛 네이버 프로필 {n}개",
    "backup_item_repo": "연결한 chanceblog 폴더 이름", "backup_item_nothing": "비어 있어요",
    "backup_why_unreadable": "읽을 수 없어요", "backup_why_newer": "더 새로운 프로그램이 만든 거예요", "backup_why_busy": "다른 곳에서 쓰고 있어요", "backup_why_pending": "정리 못 한 저장이 남아 있어요", "backup_why_other": "담지 못했어요",
    "backup_broken_manifest": "목록 파일을 읽을 수 없어요", "backup_broken_files": "파일이 빠졌거나 바뀌었어요", "backup_broken_other": "온전하지 않아요", "backup_broken_tail": "복원할 수 없어요.",
    # 행동
    "backup_restore": "복원", "backup_restore_a11y": "{title}(으)로 복원",
    "backup_busy_create": "백업하는 중이에요. 끝나면 눌러 주세요.", "backup_busy_restore": "복원하는 중이에요. 끝나면 눌러 주세요.", "backup_busy": "처리하는 중이에요. 끝나면 눌러 주세요.",
    "backup_no_write": "이 화면에서는 읽기만 할 수 있어요.", "backup_restore_broken": "깨진 백업이라 복원할 수 없어요.",
    # 상태 화면
    "backup_loading": "백업 목록을 읽는 중이에요…", "backup_loading_a11y": "백업 목록을 읽는 중",
    "backup_empty_title": "아직 만든 백업이 없어요.", "backup_empty_desc": "‘지금 백업’ 을 누르면 지금 데이터를 한 묶음으로 저장해요.",
    "backup_error_title": "백업 목록을 읽지 못했어요.", "backup_error_desc": "백업을 만드는 것은 그대로 할 수 있어요. 잠시 뒤 다시 읽어 보고, 계속되면 아래 진단 정보를 함께 알려 주세요.",
    "backup_load_failed": "백업 목록을 읽지 못했어요.", "backup_reload": "다시 읽기",
    # 진행
    "backup_progress_create": "백업하는 중이에요… {percent}%", "backup_progress_restore": "복원하는 중이에요… {percent}%", "backup_progress_a11y": "{text}",
    "backup_step_start": "백업을 시작해요", "backup_step_save": "파일을 담아요", "backup_step_check": "담은 것을 확인해요",
    "backup_step_keep": "지금 데이터를 안전 사본으로 남겨요", "backup_step_change": "백업 내용으로 바꿔요", "backup_step_read": "바뀐 것을 다시 읽어 확인해요",
    # 결과 안내(카드 위쪽 띠)
    "backup_ok_created": "백업을 만들었어요 — {when}. 키는 백업에 들어 있지 않아요.",
    "backup_ok_partial": "일부만 백업했어요. 담지 못한 것: {text}. 담은 것은 모두 확인했어요.",
    "backup_ok_restored": "복원을 마쳤어요. 복원하기 직전 데이터는 ‘복원 직전 사본’ 으로 남겨 뒀어요 — 잘못 복원했다면 그 사본으로 다시 복원하세요.",
    "backup_ok_restored_nosafety": "복원을 마쳤어요. 바꾸기 전에 남길 데이터가 이 컴퓨터에는 없었어요.",
    "backup_ok_restored_partial": "부분 복원이에요. 이 백업에 담기지 않았던 것은 지금 것을 그대로 뒀어요.",
    "backup_note_keys": "키는 백업에 없어요 — 복원한 뒤 설정에서 다시 등록해 주세요",
    # 실패 안내 — 종류별로 정해진 문장(서비스 오류의 세부·경로·입력한 값은 화면에 나가지 않는다)
    "backup_fail_blocked": "키나 토큰처럼 보이는 글이 있어 멈췄어요. 아래 위치의 글을 직접 지운 뒤 다시 해 주세요. 앱은 글을 자동으로 지우거나 바꾸지 않고 그냥 진행하는 선택지도 없어요. 아무것도 바뀌지 않았어요.",
    "backup_fail_nothing": "아직 담을 수 있는 데이터가 없어요. 아무것도 만들지 않았어요.",
    "backup_fail_busy": "다른 백업이나 복원이 진행 중이에요. 끝난 뒤 다시 눌러 주세요. 아무것도 바뀌지 않았어요.",
    "backup_fail_invalid": "이 백업은 바뀌었거나 깨져서 복원하지 않았어요. 지금 데이터는 그대로예요. 다른 백업을 골라 주세요.",
    "backup_fail_newer": "더 새로운 버전의 프로그램이 만든 데이터라 쓰지 않았어요. 프로그램을 최신 버전으로 업데이트해 주세요. 아무것도 바뀌지 않았어요.",
    "backup_fail_disk": "저장 공간이 모자라 마치지 못했어요. 공간을 만든 뒤 다시 해 주세요. 만들던 것은 남기지 않았고 지금 데이터는 그대로예요.",
    "backup_fail_io": "파일을 쓰지 못했어요(읽기 전용이거나 다른 프로그램이 쓰고 있을 수 있어요). 만들던 것은 남기지 않았고 지금 데이터는 그대로예요.",
    "backup_fail_restore": "복원하다 문제가 생겼어요. 지금까지 바꾼 것은 원래대로 돌려 두었어요.",
    "backup_fail_restore_left": "복원하다 문제가 생겼어요. 아래 것은 원래대로 돌리지 못했어요 — 원래 내용은 ‘복원 직전 사본’ 에 있으니 그 사본으로 다시 복원해 주세요.",
    "backup_restore_reason_disk": "이유: 저장 공간이 모자랐어요.", "backup_restore_reason_io": "이유: 파일을 쓰지 못했어요(읽기 전용이거나 다른 프로그램이 쓰고 있을 수 있어요).",
    "backup_restore_reason_corrupt": "이유: 바꾼 뒤 다시 읽어 보니 온전하지 않았어요.", "backup_restore_reason_busy": "이유: 다른 곳에서 데이터를 쓰고 있었어요.", "backup_restore_reason_other": "이유: 예상하지 못한 문제가 생겼어요.",
    "backup_fail_other": "처리하지 못했어요. 다시 시도해도 같으면 아래 진단 정보를 함께 알려 주세요.", "backup_fail_notes_sample": "예시 파일은 원래대로 돌리지 못했어요",
    "backup_fail_kind_blocked_where": "찾은 위치",
    # 복원 확인창
    "backup_restore_title": "이 백업으로 복원할까요?",
    "backup_restore_body": "지금 이 컴퓨터의 {what}이(가) {when} 백업의 내용으로 바뀌어요.\n\n바꾸기 직전 상태는 ‘복원 직전 사본’ 으로 자동으로 남겨요(위치: {where}). 잘못 복원했다면 목록에서 그 사본을 골라 다시 복원하면 돼요.\n\n"
                           "키는 백업에 없어서 그대로예요. 다른 PC 에서 복원했다면 복원한 뒤 설정에서 키를 다시 등록해 주세요. 복원하는 동안은 다른 화면에서 저장하지 마세요.",
    "backup_restore_partial": "\n\n이 백업은 일부만 담겨 있어서 담기지 않은 것은 지금 것을 그대로 둬요.",
    "backup_restore_ok": "복원하기", "backup_restore_cancel": "취소",
    "backup_restore_unknown_when": "시각을 알 수 없는",
    # 멈춘 복원(D-463) — 복원이 도중에 끊긴 흔적이 있을 때 카드 위쪽에 보이는 안내와 되돌리기
    "backup_interrupted_can": "복원이 중간에 멈췄어요 — 안전 사본으로 되돌릴 수 있어요. 지금 데이터는 일부만 바뀌었을 수 있어요.",
    "backup_interrupted_cannot": "복원이 중간에 멈췄어요 — 되돌릴 안전 사본을 찾을 수 없어요. 아래 목록에서 백업을 골라 다시 복원해 주세요. 지금 데이터는 일부만 바뀌었을 수 있어요.",
    "backup_interrupted_when": "복원을 시작한 때: {when}",
    "backup_revert": "안전 사본으로 되돌리기", "backup_revert_a11y": "멈춘 복원을 안전 사본으로 되돌리기",
    "backup_revert_title": "멈춘 복원을 되돌릴까요?",
    "backup_revert_body": "복원이 도중에 멈춰서 지금 데이터가 일부는 백업 내용이고 일부는 이전 내용일 수 있어요.\n\n복원 직전에 남겨 둔 안전 사본({when})으로 되돌려요. 되돌리기 직전 상태도 새 ‘복원 직전 사본’ 으로 남겨요(위치: {where}).\n\n"
                          "키는 백업에 없어서 그대로예요. 되돌리는 동안은 다른 화면에서 저장하지 마세요.",
    "backup_revert_ok": "되돌리기",
}
