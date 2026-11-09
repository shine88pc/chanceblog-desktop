"""주제 후보 화면의 문구 — `text.py` 의 `T` 에 합쳐진다(`T.update(CAND_T)`). 쉬운 한국어(`~해요`)로 새로 썼고, 결과를 약속하는 표현(`FORBIDDEN`)·월 검색량 같은 말·영문 오류 코드·예외 글은 없다 — `test_ui_candidates_core` 가 모든 문구에 대어 본다.

이 파일에는 실제 블로그 이름·후보 제목·키워드가 없다(후보와 채널 이름은 이 PC 의 보관함·프로필에서 런타임에 읽는다). 채널·상태·구간·글 종류 같은 이름은 서비스의 쉬운 이름 표(`topics/wording.py`·`content/candidates.py`)와 홈의 구간 이름(`ui/core/gauges.py`)에서 오고
여기에는 화면 문장만 둔다. 문장에 들어가는 이름·낱말은 모두 비밀 모양을 가린 뒤에 줄인 값이다. 관심도(Trend)는 늘 `최근 관심도(상대값)` 이고 검색한 횟수가 아니다.
"""
from __future__ import annotations

CAND_T = {
    # 화면 머리
    "cand_title": "주제 후보", "cand_sub": "엔진이 만든 후보를 비교하고, 점수와 이유를 살펴봐요.",
    "cand_refresh": "후보 다시 불러오기", "cand_make": "후보 만들기",
    "cand_make_tip": "승인한 Seed 로 새 후보를 만들어요. 먼저 미리 보고, 확인한 뒤에만 저장해요.",
    "cand_make_why_loading": "후보를 읽는 중에는 쓸 수 없어요.", "cand_make_why_busy": "저장하거나 미리 보는 중에는 쓸 수 없어요.", "cand_make_why_error": "후보를 읽은 뒤에 쓸 수 있어요.",
    "cand_plan_working": "만들 후보를 미리 보는 중이에요…", "cand_make_working": "후보를 만드는 중이에요…",
    # 읽는 중·오류·예시
    "cand_loading": "후보를 읽고 있어요…", "cand_loading_a11y": "후보를 읽는 중", "cand_error_title": "후보를 읽지 못했어요.", "cand_error_btn": "다시 읽기",
    "cand_error_desc": "후보 보관함은 고치거나 지우지 않았어요. 잠시 뒤에 다시 읽어 보세요. 계속되면 아래 진단 정보를 함께 알려 주세요.",
    "cand_sample_tip": "화면에 보이는 후보는 모두 예시예요. 후보를 만들어도 이 PC 의 파일에는 아무것도 쓰지 않아요.",
    "cand_sample_dialog_body": "지금 보이는 후보·점수·채널 이름은 화면을 확인하려고 넣어 둔 예시예요. 여기서 후보를 만들어도 이 PC 의 파일에는 아무것도 쓰지 않아요. 내 후보 보관함을 읽으면 이 표시가 사라져요.",
    # 빈 화면 — 서로 다른 안내(보관함 없음·옛 구조·후보 없음·거른 결과 없음·점수를 못 믿어 뺌)
    "cand_empty_nostore_title": "후보를 보관하는 파일이 아직 없어요.", "cand_empty_nostore_desc": "이 화면은 읽기만 해서 새로 만들지 않았어요. 위의 ‘후보 만들기’ 를 눌러 처음 만들 수 있어요.",
    "cand_empty_old_title": "후보 보관함이 옛 구조라 읽지 않았어요.", "cand_empty_old_desc": "이 화면은 읽기만 해서 바꾸지 않았어요. ‘후보 만들기’ 를 하면 새 구조로 올리고 옛 모양 사본을 남겨요.",
    "cand_empty_none_title": "아직 후보가 없어요.", "cand_empty_none_desc": "승인한 Seed 가 있으면 위의 ‘후보 만들기’ 로 만들 수 있어요.",
    "cand_empty_skipped_title": "보여 줄 수 있는 후보가 없어요.", "cand_empty_skipped_desc": "저장된 후보의 점수를 확인할 수 없어 모두 뺐어요. 블로그 관리의 채널 가중치를 확인해 주세요.",
    "cand_none_found": "조건에 맞는 후보가 없어요. 거르기를 풀어 보세요.", "cand_skipped_note": "점수를 확인할 수 없어 뺀 후보가 {n}개 있어요.",
    "cand_store_missing_note": "아직 후보 보관함이 없어요. 후보를 만들면 이 PC 의 데이터 폴더에 파일이 한 번 만들어져요.",
    # 거르기
    "cand_filter_a11y": "후보 거르기", "cand_filter_channel": "채널", "cand_filter_status": "작업 상태", "cand_filter_band": "점수 구간", "cand_filter_cluster": "주제 묶음",
    "cand_all": "전체", "cand_band_none": "점수 계산 전", "cand_filter_more": "더 거르기", "cand_filter_less": "더 거르기 닫기",
    "cand_filter_channel_a11y": "채널 {name} {n}개", "cand_filter_status_a11y": "작업 상태 {name} {n}개", "cand_filter_band_a11y": "점수 구간 {name} {n}개", "cand_filter_cluster_a11y": "주제 묶음 {name} {n}개",
    "cand_search_label": "후보 찾기", "cand_search_placeholder": "제목이나 키워드로 찾아요", "cand_filter_result": "{shown}장을 보여 줘요(조건에 맞는 후보 {found}개 · 전체 {total}개)",
    "cand_filter_reset": "거르기 풀기", "cand_more": "{n}개 더 보기", "cand_more_a11y": "후보 {n}개 더 보기", "cand_grid_a11y": "후보 카드 목록",
    # 카드
    "cand_card_a11y": "{title}, {channel}, 점수 {score}점 {band}", "cand_card_a11y_none": "{title}, {channel}, 점수 계산 전", "cand_card_sample": "예시",
    "cand_card_hint": "누르면 점수와 이유가 열려요.", "cand_card_state": "작업 상태 {status}", "cand_card_selected": "선택됨",
    "cand_badge_caution": "주의", "cand_badge_stop": "자동 초안 중지", "cand_image_state": "이미지 검색 전", "cand_summary_none": "추천 이유가 아직 없어요", "cand_more_keywords": "+{n}",
    # 상세 창
    "cand_detail_title": "후보 상세", "cand_detail_a11y": "후보 상세 정보", "cand_detail_close": "상세 닫기",
    "cand_detail_empty_title": "후보를 골라 보세요", "cand_detail_empty_desc": "카드를 누르면 점수와 추천 이유, 점수 구성을 여기에서 볼 수 있어요.",
    "cand_number": "번호 {ref}", "cand_copy": "번호 복사", "cand_copy_a11y": "후보 번호 {ref} 복사", "cand_copied": "후보 번호를 복사했어요.", "cand_copy_failed": "복사하지 못했어요. 다시 시도해 주세요.",
    "cand_sec_score": "점수 구성", "cand_sec_reason": "추천 이유", "cand_sec_trend": "최근 관심도(상대값)", "cand_sec_seed": "Seed 출처", "cand_sec_safety": "안전 표시", "cand_sec_hold": "다시 볼 기한",
    "cand_sec_tags": "협업 가능 유형", "cand_sec_info": "기본 정보", "cand_sec_keywords": "키워드",
    "cand_score_none": "점수 계산 전", "cand_score_final": "최종 점수 {n}점", "cand_factor_missing": "평가 전", "cand_factor_value": "{n}점", "cand_factor_weight": "가중치 {n}",
    "cand_factor_row_a11y": "{name} {value}", "cand_factor_row_a11y_weight": "{name} {value}, 가중치 {n}",
    "cand_factor_note": "평가하지 못한 항목은 0점이 아니에요. 계산에서 빼고 나머지 항목의 가중치로 다시 나눠요.", "cand_factor_none": "점수 구성 정보가 없어요.",
    "cand_reason_none": "추천 이유가 아직 없어요.",
    "cand_trend_value": "{n} (0~100 사이의 상대값)", "cand_trend_label_value": "관심도 값", "cand_trend_label_change": "변화", "cand_trend_label_period": "비교 기간", "cand_trend_label_group": "비교 키워드",
    "cand_trend_label_day": "조회일", "cand_trend_missing": "데이터 부족", "cand_trend_unavailable": "조회하지 못했어요",
    "cand_trend_note": "이 값은 비교한 기간 안의 상대적인 관심도예요. 검색한 횟수가 아니에요.", "cand_trend_note_missing": "관심도 값이 아직 없어요. 0 이 아니라 모르는 값이에요.",
    "cand_seed_route": "후보가 생긴 경로", "cand_seed_word": "Seed", "cand_seed_path": "{major} › {minor}", "cand_seed_unknown": "Seed 정보를 찾지 못했어요", "cand_seed_none": "Seed 없이 만들어진 후보예요",
    "cand_safety_none": "확인이 필요한 표시는 없어요.", "cand_level_info": "참고", "cand_level_warning": "확인 필요", "cand_level_error": "자동 초안 중지",
    "cand_safety_stop": "이 후보는 자동으로 초안을 만들지 않아요. 내용을 직접 확인한 뒤 정해 주세요.",
    "cand_hold_text": "{date}", "cand_hold_note": "점수가 보류 구간이라 이 날짜까지 보관하며 다시 평가해요.",
    "cand_info_type": "후보 종류", "cand_info_intent": "검색 의도", "cand_info_content": "글 종류", "cand_info_cluster": "주제 묶음", "cand_info_reader": "대상 독자", "cand_info_lang": "언어",
    "cand_info_created": "만든 때", "cand_info_dup": "중복 판정", "cand_info_similar": "비슷한 글", "cand_info_similar_value": "{n}개", "cand_info_channel": "채널", "cand_info_none": "없음",
    # 후보 만들기 — 미리 보기·확인창·준비 안내·결과
    "cand_make_title": "후보를 최대 {n}개 만들까요?", "cand_make_ok": "만들기", "cand_make_cancel": "취소",
    "cand_make_counts": "새 후보를 최대 {total}개 만들어요: {rows}", "cand_make_row": "{name} {n}개",
    "cand_make_seeds": "승인한 Seed {used}개에서 만들어요. 승인 전 Seed {proposed}개는 쓰이지 않아요.", "cand_make_seeds_none_proposed": "승인한 Seed {used}개에서 만들어요.",
    "cand_make_skips": "건너뛰는 것: {items}", "cand_make_skip_dup": "이미 있는 후보와 같아서 건너뛰는 후보 {n}개", "cand_make_skip_more": "외 {n}가지",
    "cand_make_adds": "후보는 이 PC 의 후보 보관함에 더해져요. 지금 있는 후보는 지워지거나 바뀌지 않아요.",
    "cand_make_store_missing": "후보를 보관하는 파일이 아직 없어서 처음 한 번 새로 만들어요. 그 밖의 파일은 만들지 않아요.",
    "cand_make_store_empty": "비어 있는 후보 보관함 파일을 새로 채워요. 그 밖의 파일은 만들지 않아요.",
    "cand_make_store_old": "후보 보관함이 옛 구조라 새 구조로 올려요. 올리기 전에 옛 모양 사본을 남겨요. 지금 있는 후보는 올린 뒤에 세기 때문에 만들 개수가 달라질 수 있어요.",
    "cand_make_nokey": "키나 네트워크는 쓰지 않아요. 관심도(Trend)는 아직 연결 전이라 조회하지 않아요.",
    "cand_made": "후보 {n}개를 만들었어요.", "cand_made_dup": "같은 후보 {n}개는 건너뛰었어요.", "cand_made_withheld": "키·토큰처럼 보이는 글이 든 후보 {n}개는 저장하지 않았어요.", "cand_made_none": "새로 만든 후보가 없어요.",
    "cand_prep_title": "아직 후보를 만들 수 없어요", "cand_prep_lead": "아무것도 만들지 않았고 파일도 바꾸지 않았어요.",
    "cand_prep_no_channel": "후보 생성이 켜진 채널이 없어요. 블로그 관리에서 채널의 후보 생성을 켜 주세요.",
    "cand_prep_no_seed": "승인한 Seed 가 없어요. Seed 관리에서 Seed 를 승인해 주세요.", "cand_prep_proposed": "승인 전 Seed {n}개는 승인하기 전에는 쓰이지 않아요.",
    "cand_prep_full": "채널마다 정해 둔 목표 개수가 이미 찼어요.", "cand_prep_none": "지금은 새로 만들 수 있는 후보가 없어요. 이미 있는 후보와 같거나 시기가 아니에요.",
    "cand_prep_seed": "Seed 관리 열기", "cand_prep_blogs": "블로그 관리 열기", "cand_prep_close": "닫기", "cand_prep_a11y": "후보를 만들 수 없는 이유와 이동 단추",
    # 실패 — 종류별 쉬운 문장(오류의 세부·경로·입력한 값은 화면에 나가지 않는다). 후보 보관함은 쓰기 전 상태 그대로다
    "cand_fail_busy": "다른 창에서 후보 보관함을 쓰고 있어서 만들지 못했어요. 잠시 뒤에 다시 해 주세요. 지금 있는 후보는 그대로예요.",
    "cand_fail_disk": "저장 공간이 부족해서 후보를 만들지 못했어요. 지금 있는 후보는 그대로예요. 공간을 확보한 뒤 다시 해 주세요.",
    "cand_fail_io": "후보 보관함에 쓰지 못했어요. 읽기 전용이거나 다른 프로그램이 쓰고 있을 수 있어요. 지금 있는 후보는 그대로예요.",
    "cand_fail_newer": "더 새로운 프로그램이 만든 후보 보관함이라 열지 않았어요. 프로그램을 최신 버전으로 올려 주세요. 지금 있는 후보는 그대로예요.",
    "cand_fail_corrupt": "후보 보관함을 읽지 못해서 만들지 않았어요. 파일은 고치거나 지우지 않았어요. 계속되면 진단 정보를 함께 알려 주세요.",
    "cand_fail_invalid": "주제 엔진 설정 파일을 읽지 못해서 만들지 않았어요. 파일은 고치거나 지우지 않았어요. 계속되면 진단 정보를 함께 알려 주세요.",
    "cand_fail_other": "후보를 만들지 못했어요. 지금 있는 후보는 그대로예요. 계속되면 진단 정보를 함께 알려 주세요.",
    "cand_plan_failed": "만들 후보를 미리 보지 못했어요. 아무것도 바뀌지 않았어요.",
}
