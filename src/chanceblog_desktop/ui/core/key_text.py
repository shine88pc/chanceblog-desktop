"""키 연결(P4f)의 문구 — `text.py` 의 `T` 에 합쳐진다(`T.update(KEY_T)`). 쉬운 한국어(`~해요`)로 새로 썼고, 결과를 약속하는 표현(`FORBIDDEN`)·영문 상태 이름·오류 코드는 쓰지 않는다.

이 파일에는 키·키의 일부·실제 블로그 이름이 없다. 문장에 들어가는 `{…}` 자리는 서비스 이름·제공자 이름·사용자가 붙인 별칭(가린 뒤 줄인 글)·숫자뿐이고 키 값은 어느 문장에도 들어가지 않는다.
"""
from __future__ import annotations

KEY_T = {
    # 설정 화면(쓰기 가능한 공급자일 때) — 읽기만 하는 공급자의 글(`conn_desc`·`conn_keys_note`)은 그대로 둔다
    "conn_desc_write": "서비스를 용도별로 묶어 보여 드려요. 키를 등록하고 지우고, 쓸지 말지와 순서·이름을 바꿀 수 있어요.",
    "conn_keys_note_write": "저장한 키는 이 컴퓨터의 Windows 자격 증명 관리자에만 있고, 저장한 뒤에는 화면에 다시 보여 드리지 않아요. 키가 없어도 모든 핵심 기능은 그대로 써요.",
    # 카드 — 키 목록·등록
    "keys_none": "연결 안 됨 — 키 없이도 쓸 수 있어요",
    "keys_register": "키 등록", "keys_register_a11y": "{service} 키 등록",
    "keys_full_one": "{service}는 키를 {n}개까지만 둘 수 있어요. 바꾸려면 기존 키를 먼저 지워 주세요.",
    "keys_full_many": "{service}에 둘 수 있는 키 자리가 모두 찼어요. 바꾸려면 기존 키를 먼저 지워 주세요.",
    "keys_store_missing": "이 컴퓨터에서는 키 저장소를 쓸 수 없어요.",
    "keys_store_missing_why": "Windows 자격 증명 관리자를 열지 못했어요. 키 등록·지우기·연결 시험은 할 수 없지만 프로그램은 키 없이 그대로 써요.",
    "keys_busy": "저장하는 중이에요. 끝나면 눌러 주세요.", "keys_busy_status": "저장하는 중이에요…",
    "keys_row_a11y": "{name}, {state}",
    "keys_row_provider": "제공자: {name}", "keys_row_last_ok": "마지막 성공: {when}", "keys_row_no_ok": "마지막 성공: 아직 없어요", "keys_row_priority": "우선순위 {n}",
    "keys_row_missing": "보관소에서 이 키를 찾지 못했어요. 지우고 다시 등록해 주세요.",
    "keys_check_ok": "마지막 확인: 연결을 확인했어요", "keys_check_auth": "마지막 오류: 서비스가 키를 거절했어요. 키를 다시 확인해 주세요.", "keys_check_error": "마지막 오류: 연결을 확인하지 못했어요. 잠시 뒤 다시 시험해 보세요.",
    "keys_state_badge_active": "사용", "keys_state_badge_standby": "예비", "keys_state_badge_off": "꺼짐",
    # 행동
    "keys_act_test": "연결 시험", "keys_act_rename": "별칭 바꾸기", "keys_act_delete": "삭제", "keys_act_up": "우선순위 올리기", "keys_act_down": "우선순위 내리기",
    "keys_act_to_active": "사용으로 바꾸기", "keys_act_to_standby": "예비로 바꾸기", "keys_act_to_off": "끄기", "keys_act_turn_on": "켜기",
    "keys_act_a11y": "{action} — {name}", "keys_actions_a11y": "{name} 키 행동",
    "keys_why_prep": "아직 시험할 수 없어요(준비 중). 이 서비스는 아직 실제 연결 기능이 없어요.", "keys_why_terms": "이용 약관을 확인하기 전이라 연결 시험을 하지 않아요.",
    "keys_why_first": "이미 맨 위예요.", "keys_why_last": "이미 맨 아래예요.", "keys_why_nokey": "보관소에서 키를 찾지 못했어요.",
    "keys_why_readonly": "이 화면에서는 읽기만 할 수 있어요.",
    # 결과 안내(화면 위쪽 띠)
    "keys_ok_added": "키를 저장했어요. 키는 이 컴퓨터의 Windows 자격 증명 관리자에만 있고 다시 보여 드리지 않아요.", "keys_ok_removed": "키를 지웠어요.", "keys_ok_state": "키 사용 설정을 바꿨어요.",
    "keys_ok_renamed": "별칭을 바꿨어요.", "keys_ok_moved": "우선순위를 바꿨어요.", "keys_ok_unchanged": "바뀐 것이 없어요.",
    "keys_testing": "연결을 시험하는 중이에요…",
    "keys_test_ok": "연결을 확인했어요. 키가 정상으로 보여요.", "keys_test_auth": "서비스가 키를 거절했어요. 키를 지우고 새로 등록해 주세요. 다른 키로 바꿔 시도하지 않았어요.",
    "keys_test_limit": "서비스가 요청 한도에 닿았다고 답했어요. 잠시 뒤 다시 시험해 주세요.", "keys_test_error": "연결을 확인하지 못했어요. 잠시 뒤 다시 시험해 주세요.",
    "keys_test_notready": "아직 시험할 수 없어요(준비 중).", "keys_test_soon": "같은 키는 {n}초 뒤에 다시 시험할 수 있어요.", "keys_test_novalue": "보관소에서 키를 찾지 못했어요. 지우고 다시 등록해 주세요.",
    # 실패 안내 — 종류별로 정해진 문장(서비스 오류의 세부·경로·입력한 값은 화면에 나가지 않는다)
    "keys_fail_limit": "키를 더하지 못했어요. 이 서비스는 키를 더 둘 수 없어요. 기존 키를 지운 뒤 다시 등록해 주세요.",
    "keys_fail_duplicate_name": "같은 별칭이 이미 있어요. 다른 별칭을 써 주세요.", "keys_fail_duplicate_value": "같은 키가 이미 저장돼 있어요. 같은 키를 두 번 넣을 필요는 없어요.",
    "keys_fail_invalid": "입력한 내용을 다시 확인해 주세요. 어느 칸이 문제인지는 칸 옆에 적었어요. 키는 다시 입력해 주세요.",
    "keys_fail_terms": "같은 서비스에 키를 하나 더 두려면 약관을 확인해야 해요. 확인 칸을 눌러 주세요.",
    "keys_fail_store": "키 보관소(Windows 자격 증명 관리자)를 쓰지 못했어요. 아무것도 바뀌지 않았어요. 잠시 뒤 다시 시도해 주세요.",
    "keys_fail_leftover": "키를 저장하다 문제가 생겼고, 보관소에 넣은 키를 지우지도 못했어요. Windows 자격 증명 관리자에서 이름이 ChanceBlogDesktop 으로 시작하고 이 앱의 목록에 없는 항목을 직접 지워 주세요.",
    "keys_fail_notfound": "그 키는 이미 지워졌거나 바뀌었어요. 목록을 다시 읽어 드릴게요.",
    "keys_fail_busy": "다른 곳에서 연결 설정을 바꾸는 중이에요. 잠시 뒤 다시 눌러 주세요.",
    "keys_fail_io": "연결 설정 파일에 저장하지 못했어요. 바뀐 것은 없어요. 키는 보관소에 남지 않았으니 다시 입력해 주세요.",
    "keys_fail_io_edit": "연결 설정 파일에 저장하지 못했어요. 바뀐 것은 없어요. 잠시 뒤 다시 시도해 주세요.",         # 키를 새로 넣는 일이 아닌 쓰기(지우기·상태·순서·별칭)의 같은 실패 — 다시 입력할 키가 없다
    "keys_fail_invalid_edit": "입력한 내용을 다시 확인해 주세요. 바뀐 것은 없어요.",
    "keys_fail_disk": "디스크 공간이 모자라 저장하지 못했어요. 바뀐 것은 없어요. 공간을 만든 뒤 다시 시도해 주세요.",
    # 삭제 도중의 저장 실패(독립 검증 M1) — 키 저장소의 키를 이미 지운 뒤 파일 쓰기에서 실패했을 수도, 그 앞 단계에서 실패해 아무것도 안 바꿨을 수도 있는데 오류 종류만으로는 구별할 수 없다.
    # 그래서 '바뀐 것은 없어요' 라고 하지 않고 어느 쪽이어도 참인 말만 한다: 목록을 다시 읽는다 · 키가 이미 지워졌다면 그 줄에 '찾지 못했어요' 가 보인다 · 그 줄에서 삭제를 한 번 더 누르면 정리된다.
    "keys_fail_remove_io": "키를 지우다가 연결 설정 파일에 저장하지 못했어요. 키가 이미 지워졌을 수도 있어서 목록을 다시 읽어 드릴게요. 그 줄에 '보관소에서 이 키를 찾지 못했어요' 가 보이면 삭제를 한 번 더 눌러 정리해 주세요. 키가 그대로면 잠시 뒤 다시 지워 주세요.",
    "keys_fail_remove_disk": "키를 지우다가 디스크 공간이 모자라 저장하지 못했어요. 키가 이미 지워졌을 수도 있어서 목록을 다시 읽어 드릴게요. 그 줄에 '보관소에서 이 키를 찾지 못했어요' 가 보이면 삭제를 한 번 더 눌러 정리해 주세요. 키가 그대로면 공간을 만든 뒤 다시 지워 주세요.",
    "keys_fail_corrupt": "연결 설정 파일을 읽지 못했어요. 파일은 고치거나 지우지 않았어요. 아래 진단 정보를 함께 알려 주세요.",
    "keys_fail_other": "처리하지 못했어요. 아무것도 바뀌지 않았어요. 다시 시도해도 같으면 진단 정보를 함께 알려 주세요.",
    # 입력 칸 문제(칸 옆 문장) — 입력한 글은 들어 있지 않다
    "keys_problem_empty": "{field} 칸이 비어 있어요.", "keys_problem_hidden": "{field} 칸에 공백이나 눈에 안 보이는 글자가 있어요. 다시 복사해서 붙여 넣어 주세요.",
    "keys_problem_short": "{field} 칸이 너무 짧아요. 끝까지 복사됐는지 확인해 주세요.", "keys_problem_min": "{field} 칸이 너무 짧아요(최소 {n}자). 끝까지 복사됐는지 확인해 주세요.",
    "keys_problem_long": "{field} 칸이 너무 길어요. 설명 글이나 여러 줄이 함께 붙지 않았는지 확인해 주세요.", "keys_problem_chars": "{field} 칸에 키에 쓸 수 없는 글자가 있어요. 따옴표·괄호·한글 같은 설명 글이 함께 붙지 않았는지 확인해 주세요.",
    "keys_problem_unprintable": "{field} 칸에 표시할 수 없는 글자가 있어요. 다시 복사해서 붙여 넣어 주세요.", "keys_problem_other": "{field} 칸을 다시 확인해 주세요.",
    "keys_alias_empty": "별칭을 적어 주세요.", "keys_alias_long": "별칭이 너무 길어요({n}자까지 쓸 수 있어요).", "keys_alias_hidden": "별칭에 줄바꿈이나 눈에 안 보이는 글자가 있어요.",
    "keys_alias_keyish": "별칭에 키처럼 보이는 글이 있어요. 별칭에는 키를 적지 않아요.", "keys_alias_value": "별칭에 저장한 키가 그대로 들어 있어요. 별칭에는 키를 적지 않아요.",
    "keys_alias_duplicate": "이 서비스에 같은 별칭이 이미 있어요.", "keys_alias_other": "별칭을 다시 확인해 주세요.",
    "keys_alias_label": "별칭", "keys_alias_name": "별칭",
    # 등록 대화상자
    "keys_reg_title": "키 등록 — {service}", "keys_reg_intro": "키는 이 컴퓨터의 Windows 자격 증명 관리자에만 저장해요. 저장한 뒤에는 화면에 다시 보여 드리지 않아요.",
    "keys_reg_alias_hint": "이 키를 알아보기 쉬운 이름이에요(예: 기본). 키는 적지 마세요.", "keys_reg_provider": "제공자", "keys_reg_provider_full": "자리가 가득 찼어요",
    "keys_reg_field_hint": "붙여 넣어도 돼요. 입력한 글은 점으로만 보여요.", "keys_reg_secret_a11y": "{field} 입력(글자는 가려져요)", "keys_reg_alias_a11y": "별칭 입력",
    "keys_reg_next": "다음", "keys_reg_back": "이전", "keys_reg_cancel": "취소", "keys_reg_save": "저장", "keys_reg_close": "닫기",
    "keys_reg_clipboard": "붙여 넣은 키가 클립보드에 그대로 남아 있으면 저장하거나 닫을 때 지워요.",
    "keys_reg_confirm_title": "이 키를 저장할까요?", "keys_reg_confirm_service": "서비스: {name}", "keys_reg_confirm_provider": "제공자: {name}", "keys_reg_confirm_alias": "별칭: {name}",
    "keys_reg_confirm_note": "키는 화면에 보이지 않아요. 저장하면 Windows 자격 증명 관리자에 보관되고, 저장한 키는 다시 볼 수 없어요.",
    "keys_reg_terms": "같은 서비스의 무료 한도를 여러 계정이나 프로젝트로 나눠 쓰는 것은 서비스 약관에서 금지될 수 있어요. 본인 소유의 정당한 키에만 쓰세요.",
    "keys_reg_terms_check": "서비스 약관을 확인했어요", "keys_reg_a11y": "{service} 키 등록 {step}", "keys_reg_step_input": "1단계 입력", "keys_reg_step_confirm": "2단계 확인",
    # 삭제·별칭 바꾸기 확인창
    "keys_del_title": "키를 지울까요?", "keys_del_ok": "지우기", "keys_del_cancel": "취소", "keys_del_unnamed": "이름 없는 키",
    "keys_del_body": "「{name}」 키를 지워요. 이 컴퓨터의 Windows 자격 증명 관리자에 저장된 키가 지워지고 되돌릴 수 없어요. 키가 다시 필요하면 서비스 사이트에서 새로 받아 등록해야 해요. 다른 키나 블로그 글에는 영향이 없어요.",
    "keys_ren_title": "별칭 바꾸기", "keys_ren_body": "「{name}」 키의 별칭을 바꿔요. 키 자체는 바뀌지 않아요.", "keys_ren_label": "새 별칭", "keys_ren_ok": "바꾸기", "keys_ren_cancel": "취소", "keys_ren_a11y": "새 별칭 입력",
}
