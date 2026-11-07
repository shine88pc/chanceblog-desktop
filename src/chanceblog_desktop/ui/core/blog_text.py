"""블로그 관리 화면(P4b)의 문구 — `text.py` 의 `T` 에 합쳐진다(`T.update(BLOG_T)`). 쉬운 한국어(`~해요`)로 새로 썼고, 결과를 약속하는 표현(`FORBIDDEN`)·영문 오류 코드·예외 글은 없다 — `test_ui_core` 가 모든 문구에 대어 본다.

이 파일에는 실제 블로그 이름·아이디·카테고리가 없다(사용자가 화면에서 넣은 값은 이 PC 의 데이터 폴더에만 저장된다). 슬롯 이름·색 프리셋 이름·협찬 분야 이름은 서비스의 쉬운 이름 표(`topics/wording.py`)와 같은 글이다(시험이 견준다).
"""
from __future__ import annotations

BLOG_T = {
    # 화면 머리·슬롯 목록
    "blogs_title": "블로그 관리", "blogs_sub": "블로그 정보를 등록하고 고칠 수 있어요. 저장하기 전에는 아무것도 바뀌지 않아요.", "blogs_refresh": "블로그 정보 다시 불러오기",
    "blogs_list_title": "내 블로그", "blogs_list_desc": "슬롯은 다섯 개예요. 쓰지 않는 슬롯은 비워 두면 돼요.", "blogs_list_a11y": "블로그 슬롯 목록",
    "blogs_slot_github_pages": "GitHub Pages", "blogs_slot_blogger_en": "Blogger 영문", "blogs_slot_blogger_ko": "Blogger 한글", "blogs_slot_naver_a": "네이버 A", "blogs_slot_naver_b": "네이버 B",
    "blogs_kind_naver": "네이버 블로그", "blogs_kind_blogger": "Blogger", "blogs_kind_github": "GitHub Pages",
    "blogs_status_registered": "등록됨", "blogs_status_empty": "비어 있음", "blogs_status_unsaved": "저장 전 변경",
    "blogs_gen_on": "후보 만들기 켜짐", "blogs_gen_off": "후보 만들기 꺼짐", "blogs_gen_none": "후보 만들기 지원 전",
    "blogs_lang_ko": "한국어", "blogs_lang_en": "영어",
    "blogs_card_empty_title": "블로그를 등록해 보세요", "blogs_card_empty_desc": "눌러서 이름과 블로그 ID 를 넣어요.", "blogs_card_ref": "블로그 {ref}", "blogs_card_preset": "색 {name}",
    "blogs_card_a11y": "{slot}, {state}, {name}", "blogs_card_a11y_empty": "{slot}, 비어 있음, 눌러서 등록", "blogs_card_selected": "{base}, 선택됨",
    # 폼 머리·구역
    "blogs_form_new": "{slot} 등록", "blogs_form_edit": "{slot} 정보", "blogs_form_a11y": "{slot} 프로필 입력",
    "blogs_sec_basic": "기본 정보", "blogs_sec_basic_desc": "필수 칸만 채우면 저장할 수 있어요.",
    "blogs_sec_more": "자세한 정보(선택)", "blogs_sec_more_desc": "비워 둬도 돼요. 주제를 고를 때 참고해요.",
    "blogs_sec_look": "모양(선택)", "blogs_sec_look_desc": "색은 배지와 카드 테두리에만 써요. 앱 전체 색은 그대로예요.",
    "blogs_required": "필수",
    # 칸 이름·안내
    "bf_label_display_name": "표시 이름", "bf_label_blog_ref": "블로그 ID 또는 주소", "bf_label_language": "언어", "bf_label_generation_enabled": "후보 만들기",
    "bf_label_alias": "별명", "bf_label_channel_role": "채널 역할", "bf_label_main_topics": "주요 주제", "bf_label_audience": "대상 독자", "bf_label_tone": "문체",
    "bf_label_categories": "카테고리", "bf_label_intro": "소개글", "bf_label_monetization_focus": "협찬 가능 분야", "bf_label_color_preset": "색 프리셋",
    "bf_label_profile_image": "프로필 이미지", "bf_label_cover_image": "커버 이미지",
    "bf_hint_display_name": "화면에 보이는 블로그 이름이에요({limit}자까지).", "bf_hint_blog_ref": "블로그 ID 나 https 로 시작하는 주소를 공백 없이 써요.", "bf_hint_language": "글을 쓰는 언어예요.",
    "bf_hint_generation_enabled": "켜면 이 블로그의 주제 후보를 만들어요. 끄면 만들지 않아요.", "bf_hint_generation_off": "이 채널의 주제 후보 만들기는 아직 지원하지 않아요(네이버 A·B 에서만 켤 수 있어요).",
    "bf_hint_alias": "다른 이름이 있으면 적어요({limit}자까지).", "bf_hint_channel_role": "이 블로그가 맡는 역할을 한 줄로 적어요({limit}자까지).",
    "bf_hint_main_topics": "쉼표로 나눠 적어요({count}개까지, 낱말마다 {limit}자까지).", "bf_hint_audience": "누구를 위한 글인지 적어요({limit}자까지).",
    "bf_hint_tone": "글의 말투나 분위기를 적어요({limit}자까지).", "bf_hint_categories": "쉼표로 나눠 적어요({count}개까지, 낱말마다 {limit}자까지).",
    "bf_hint_intro": "블로그 소개글을 한 줄로 적어요({limit}자까지).", "bf_hint_monetization_focus": "협찬을 받을 수 있는 분야를 골라요. 여러 개 골라도 돼요.",
    "bf_hint_color_preset": "블로그를 구분하는 색이에요. 색을 직접 고르는 칸은 없어요.", "bf_hint_profile_image": "이미지 파일은 복사하거나 올리지 않고 위치만 기억해요.",
    "bf_hint_cover_image": "이미지 파일은 복사하거나 올리지 않고 위치만 기억해요.", "bf_extra_tags": "목록에 없는 분야 {n}개는 그대로 보관돼요.",
    "bf_placeholder_display_name": "예) 내 블로그 이름", "bf_placeholder_blog_ref": "블로그 ID 또는 https 주소", "bf_placeholder_words": "쉼표로 나눠서 적어요",
    "bf_placeholder_path": "고른 파일의 위치가 여기에 보여요",
    "bf_pick": "파일 고르기", "bf_pick_a11y": "{label} 파일 고르기", "bf_pick_title": "{label} 고르기", "bf_pick_filter": "이미지 파일", "bf_clear": "지우기", "bf_clear_a11y": "{label} 지우기",
    "bf_on": "켜짐", "bf_off": "꺼짐",
    "bf_preset_none": "정하지 않음", "bf_preset_warm_lifestyle": "따뜻한 생활 톤", "bf_preset_cool_technology": "차분한 기술 톤",
    "bf_tag_small_appliance": "소형가전", "bf_tag_pc_peripheral": "PC 주변기기", "bf_tag_lodging_travel": "숙박·여행", "bf_tag_ai_service": "AI 서비스", "bf_tag_pc_parts": "PC 부품",
    "bf_tag_work_automation": "업무 자동화",
    # 칸 옆의 오류·주의 문장
    "bf_err_required": "이 칸은 꼭 채워 주세요.", "bf_err_too_long": "{limit}자까지 쓸 수 있어요(지금 {now}자).", "bf_err_too_many": "{limit}개까지 쓸 수 있어요(지금 {now}개).",
    "bf_err_item_too_long": "낱말 하나는 {limit}자까지 쓸 수 있어요.", "bf_err_duplicate": "같은 낱말이 두 번 들어 있어요.",
    "bf_err_markup": "꺾쇠 괄호 태그나 스크립트·템플릿 표기는 쓸 수 없어요.", "bf_err_ref": "블로그 ID(영문·숫자와 . _ - 만, 64자까지)나 https 로 시작하는 주소를 공백 없이 써 주세요.",
    "bf_err_choice": "목록에서 골라 주세요.", "bf_err_path": "파일 위치만 쓸 수 있어요. 이미지 내용을 직접 넣을 수는 없어요.",
    "bf_err_key_shape": "키나 토큰처럼 보이는 글이 들어 있어요. 이 칸에는 키를 적지 않아요.", "bf_err_invalid": "이 칸의 값을 확인해 주세요.",
    "bf_warn_same_ref": "다른 슬롯에도 같은 블로그가 등록되어 있어요.",
    # 행동 줄
    "blogs_actions_a11y": "블로그 프로필 행동 줄", "blogs_save": "저장", "blogs_revert": "되돌리기", "blogs_clone": "복제", "blogs_delete": "삭제",
    "blogs_saving": "저장하는 중이에요…",
    "blogs_save_nothing": "바꾼 내용이 없어요.", "blogs_revert_nothing": "되돌릴 변경이 없어요.", "blogs_working": "저장하는 중에는 쓸 수 없어요.",
    "blogs_clone_no_source": "블로그를 먼저 등록해야 복제할 수 있어요.", "blogs_clone_no_target": "같은 종류의 비어 있는 슬롯이 없어요.", "blogs_clone_unsaved": "저장하지 않은 변경이 있어요. 먼저 저장하거나 되돌려 주세요.",
    "blogs_delete_empty": "지울 내용이 없어요.", "blogs_clone_hint": "{target} 슬롯으로 값을 복사해요.",
    "blogs_save_invalid": "입력한 값 중에 확인할 곳이 있어요. 표시된 칸을 고쳐 주세요.",
    # 삭제 확인창
    "blogs_del_title": "이 프로필을 지울까요?",
    "blogs_del_body": "‘{name}’ 슬롯에 넣은 이름·블로그 ID·주제 같은 내용이 모두 비워져요.\n슬롯은 사라지지 않고 비어 있는 상태로 돌아가요. 지우면 되돌릴 수 없어요.\n이 프로필로 만든 후보·초안·발행 기록은 지워지지 않아요.",
    "blogs_del_ok": "지우기", "blogs_del_cancel": "취소", "blogs_del_unnamed": "이름 없는 블로그",
    # 결과·실패
    "blogs_saved": "저장했어요.", "blogs_unchanged": "바뀐 내용이 없어요.", "blogs_cloned": "복제했어요. 이름과 블로그 ID 를 이 블로그에 맞게 바꿔 주세요.", "blogs_cleared": "프로필을 지웠어요. 슬롯은 비어 있는 상태예요.",
    "blogs_stale_reloaded": "다른 곳에서 바뀐 내용을 다시 불러왔어요. 입력한 내용은 그대로 두었어요. 확인한 뒤 다시 저장해 주세요.",
    "blogs_fail_conflict": "다른 곳에서 먼저 바뀌었어요. 입력한 내용은 그대로 두었어요. 최신 내용을 불러오는 중이에요.",
    "blogs_fail_busy": "다른 창에서 저장하는 중이에요. 잠시 뒤에 다시 저장해 주세요. 입력한 내용은 그대로예요.",
    "blogs_fail_io": "파일을 저장하지 못했어요. 쓸 수 없는 폴더이거나 다른 프로그램이 파일을 쓰고 있을 수 있어요. 기존 내용은 그대로이고 입력한 내용도 남아 있어요.",
    "blogs_fail_disk": "저장 공간이 부족해서 저장하지 못했어요. 기존 내용은 그대로예요. 공간을 확보한 뒤 다시 저장해 주세요.",
    "blogs_fail_invalid": "입력한 값 중에 확인할 곳이 있어요. 표시된 칸을 고친 뒤 다시 저장해 주세요.",
    "blogs_fail_corrupt": "프로필 파일을 읽지 못해서 저장하지 않았어요. 파일은 고치거나 지우지 않았어요. 계속되면 진단 정보를 함께 알려 주세요.",
    "blogs_fail_other": "저장하지 못했어요. 기존 내용은 그대로이고 입력한 내용도 남아 있어요.",
    # 읽는 중·오류·예시·처음
    "blogs_loading": "블로그 정보를 읽고 있어요…", "blogs_loading_a11y": "블로그 정보를 읽는 중",
    "blogs_error_title": "블로그 정보를 읽지 못했어요.", "blogs_error_desc": "프로필 파일은 고치거나 지우지 않았어요. 잠시 뒤에 다시 읽어 보세요. 계속되면 아래 진단 정보를 함께 알려 주세요.", "blogs_error_btn": "다시 읽기",
    "blogs_sample_tip": "화면에 보이는 블로그 정보는 예시예요. 저장해도 이 PC 의 파일에는 쓰지 않아요.",
    "blogs_sample_dialog_body": "지금 보이는 블로그 이름과 ID 는 화면을 확인하려고 넣어 둔 예시예요. 여기서 저장해도 이 PC 의 파일에는 아무것도 쓰지 않아요.",
    "blogs_missing_note": "아직 저장한 블로그 정보가 없어요. 처음 저장하면 이 PC 의 데이터 폴더에 파일이 만들어져요.",
}
