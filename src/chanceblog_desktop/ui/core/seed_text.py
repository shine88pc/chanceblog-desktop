"""Seed 관리 화면의 문구 — `text.py` 의 `T` 에 합쳐진다(`T.update(SEED_T)`). 쉬운 한국어(`~해요`)로 새로 썼고, 결과를 약속하는 표현(`FORBIDDEN`)·영문 오류 코드·예외 글은 없다 — `test_ui_core` 가 모든 문구에 대어 본다.

이 파일에는 실제 Seed 낱말·분류·블로그 이름이 없다(사용자가 등록하거나 불러온 값은 이 PC 의 데이터 폴더에만 저장된다). 상태·소속·중요도·대상 유형·채널 이름은 서비스의 쉬운 이름 표(`topics/wording.py`·`topics/seeds.py`)에서 오고
여기에는 화면 문장만 둔다. 문장에 들어가는 이름·낱말은 모두 비밀 모양을 가린 뒤에 줄인 값이다.
"""
from __future__ import annotations

SEED_T = {
    # 화면 머리
    "seeds_title": "Seed 관리", "seeds_sub": "후보 주제를 만드는 출발 낱말(Seed)을 승인하고 정리해요.",
    "seeds_refresh": "Seed 다시 불러오기", "seeds_import": "제안 파일 불러오기", "seeds_new": "새 Seed 등록",
    # 개수 요약
    "seeds_sum_proposed": "승인 전 {n}개 — 승인하기 전에는 후보 생성에 쓰이지 않습니다", "seeds_sum_no_proposed": "승인을 기다리는 Seed 는 없어요.",
    "seeds_sum_active": "사용 중 {n}개", "seeds_sum_inactive": "쉬는 중 {n}개", "seeds_sum_total": "전체 {n}개", "seeds_sum_a11y": "Seed 개수 요약",
    "seeds_channel_chip": "{name} {n}개 · {gen}", "seeds_channel_a11y": "{name}, 쓸 수 있는 Seed {n}개, {gen}", "seeds_gen_on": "후보 생성 켜짐", "seeds_gen_off": "후보 생성 꺼짐", "seeds_gen_unknown": "후보 생성 확인 못 함",
    "seeds_channels_caption": "채널마다 쓸 수 있는 Seed 수예요. 사용 중이고 그 채널을 허용한 Seed 만 세요. 후보 생성이 꺼진 채널은 Seed 를 승인해도 후보를 만들지 않아요.", "seeds_channels_a11y": "채널별 쓸 수 있는 Seed 수",
    # 거르기
    "seeds_filter_a11y": "Seed 거르기", "seeds_filter_status": "상태", "seeds_filter_scope": "소속", "seeds_filter_importance": "중요도",
    "seeds_all": "전체", "seeds_status_proposed": "승인 전", "seeds_status_active": "사용 중", "seeds_status_inactive": "쉬는 중", "seeds_scope_all": "모든 소속", "seeds_importance_all": "모든 중요도",
    "seeds_filter_more": "더 거르기", "seeds_filter_less": "더 거르기 닫기",
    "seeds_search_label": "Seed 찾기", "seeds_search_placeholder": "낱말·대분류·중분류로 찾아요", "seeds_filter_result": "{shown}개를 보여 줘요(조건에 맞는 Seed {found}개 · 전체 {total}개)",
    "seeds_filter_reset": "거르기 풀기",
    # 목록
    "seeds_list_a11y": "Seed 목록", "seeds_row_path": "{major} › {minor}", "seeds_row_meta": "{scope} · {importance} · {target}", "seeds_row_channels": "허용 채널 {names}",
    "seeds_target_none": "대상 유형 미정", "seeds_flag_priority": "우선 표시", "seeds_flag_region": "지역 값 필요", "seeds_flag_brand": "브랜드 예외", "seeds_flag_unsaved": "저장 전 변경",
    "seeds_idle_badge": "쉬게 할까요?", "seeds_row_a11y": "{title}, {status}, {scope}, {importance}", "seeds_row_a11y_idle": "{base}, 쉬게 할지 정해 보세요", "seeds_row_a11y_unsaved": "{base}, 저장 전 변경이 있어요",
    "seeds_check_a11y": "{title} 고르기", "seeds_row_open_hint": "누르면 자세한 내용이 열려요",
    "seeds_empty_title": "아직 Seed 가 없어요.", "seeds_empty_desc": "제안 파일을 불러오거나 새 Seed 를 등록해 보세요. 등록한 Seed 는 모두 승인 전으로 시작해요.",
    "seeds_none_found": "조건에 맞는 Seed 가 없어요. 거르기를 풀어 보세요.", "seeds_more": "{n}개 더 보기", "seeds_more_a11y": "Seed {n}개 더 보기",
    # 일괄 변경 줄
    "seeds_bulk_a11y": "고른 Seed 한꺼번에 바꾸기", "seeds_bulk_none": "고른 Seed 가 없어요", "seeds_bulk_selected": "{n}개 골랐어요",
    "seeds_bulk_select_all": "조건에 맞는 {n}개 모두 고르기", "seeds_bulk_clear": "고른 것 풀기",
    "seeds_bulk_activate": "사용 중으로 바꾸기 {n}", "seeds_bulk_rest": "쉬게 하기 {n}",
    "seeds_bulk_no_pick": "먼저 바꿀 Seed 를 골라 주세요.", "seeds_bulk_no_target": "고른 Seed 중에 이 일로 바꿀 수 있는 것이 없어요.", "seeds_bulk_working": "저장하는 중에는 쓸 수 없어요.",
    # 일괄 변경 확인창
    "seeds_bulk_title": "고른 Seed {n}개를 바꿀까요?", "seeds_bulk_ok_activate": "사용 중으로 바꾸기", "seeds_bulk_ok_rest": "쉬게 하기",
    "seeds_bulk_dlg_activate": "{parts}를 사용 중으로 바꿉니다.", "seeds_bulk_dlg_rest": "{parts}를 쉬는 중으로 바꿉니다.",
    "seeds_bulk_part_proposed": "승인 전 {n}개", "seeds_bulk_part_inactive": "쉬는 중 {n}개", "seeds_bulk_part_active": "사용 중 {n}개",
    "seeds_bulk_names": "처음 {shown}개: {names}", "seeds_bulk_names_more": "처음 {shown}개: {names} 외 {rest}개",
    "seeds_bulk_effect_activate": "사용 중이 되면 그때부터 후보 생성에 쓰여요. 나중에 쉬는 중으로 되돌릴 수 있어요.",
    "seeds_bulk_effect_rest": "쉬는 중인 Seed 는 후보 생성에 쓰이지 않아요. 나중에 다시 사용 중으로 바꿀 수 있어요.",
    "seeds_bulk_skipped": "고른 것 중 {n}개는 이 일로 바뀌지 않아요(이미 그 상태이거나 바꿀 수 없는 상태예요).",
    "seeds_bulk_counts": "바꾼 뒤 채널마다 쓸 수 있는 Seed 수: {rows}", "seeds_bulk_count_row": "{name} {before}개 → {after}개", "seeds_bulk_all_or_nothing": "한 번에 모두 바뀌거나 하나도 안 바뀌어요.",
    "seeds_bulk_cancel": "취소",
    # 상세 서랍
    "seeds_detail_title": "Seed 상세", "seeds_detail_a11y": "Seed 상세와 고치기", "seeds_info_scope": "소속", "seeds_info_importance": "중요도", "seeds_info_target": "대상 유형", "seeds_info_channels": "허용 채널",
    "seeds_info_tag": "협찬 가능 분야", "seeds_info_registered": "등록일", "seeds_info_since": "사용 시작일", "seeds_info_selected": "마지막 선택일", "seeds_info_none": "없음",
    "seeds_info_channel_only": "{name} 한 곳", "seeds_info_region": "이 Seed 는 지역 값이 필요해요. 블로그 관리에서 지역을 정하기 전에는 후보를 만들지 않아요.",
    "seeds_info_brand": "브랜드 이름이 든 예외 Seed 예요. 허용한 이유를 제안 이유에 적어 두었어요.", "seeds_info_unused": "아직 한 번도 고르지 않았어요",
    "seeds_sched_title": "계절 일정", "seeds_sched_prepare": "준비 시작일", "seeds_sched_publish": "발행 기간", "seeds_sched_peak": "피크 기간", "seeds_sched_repeat": "반복", "seeds_sched_state": "지금 상태",
    "seeds_sched_range": "{first} 부터 {last} 까지", "seeds_sched_note": "계절 일정은 여기서 고치지 않아요. 보여 주기만 해요. 계절형 Seed 는 비수기라고 해서 쉬게 하자고 제안하지 않아요.",
    "seeds_idle_note": "마지막으로 쓴 때부터 {days}일이 지났어요. 쉬게 할지는 직접 정해요. 자동으로 바뀌지 않아요.", "seeds_stateline_proposed": "승인하기 전이라 후보 생성에 쓰이지 않아요.",
    "seeds_stateline_active": "사용 중이에요. 허용한 채널의 후보 생성에 쓰여요.", "seeds_stateline_inactive": "쉬는 중이에요. 후보 생성에 쓰이지 않아요.",
    # 폼 칸
    "sf_label_priority": "우선 표시", "sf_label_excluded_keywords": "제외 키워드", "sf_label_priority_keywords": "우선 키워드", "sf_label_allowed_channels": "허용 채널", "sf_label_reason": "제안 이유",
    "sf_label_keyword": "Seed 낱말", "sf_label_major": "대분류", "sf_label_minor": "중분류", "sf_label_seed_type": "중요도", "sf_label_target_type": "대상 유형", "sf_label_scope": "소속",
    "sf_label_sponsor_tag": "협찬 가능 분야",
    "sf_hint_priority": "켜면 같은 조건에서 앞쪽에 놓여요.", "sf_hint_excluded_keywords": "이 Seed 에서 만든 후보에 들어가면 안 되는 낱말이에요. 쉼표로 나눠 적어요({count}개까지, 낱말마다 {limit}자까지).",
    "sf_hint_priority_keywords": "후보를 만들 때 먼저 붙이고 싶은 낱말이에요. 쉼표로 나눠 적어요({count}개까지, 낱말마다 {limit}자까지). 제외 키워드와 겹치면 안 돼요.",
    "sf_hint_allowed_channels": "공통 Seed 는 하나 이상 골라야 해요. 사용 중인 Seed 의 채널을 바꾸면 그 채널의 후보 생성에 바로 반영돼요.",
    "sf_hint_reason": "왜 이 Seed 가 필요한지 한 줄로 적어요({limit}자까지).", "sf_hint_keyword": "후보 주제의 출발이 되는 낱말이에요({limit}자까지). 등록한 뒤에는 고칠 수 없어요.",
    "sf_hint_major": "큰 분류 이름이에요({limit}자까지).", "sf_hint_minor": "작은 분류 이름이에요({limit}자까지).", "sf_hint_seed_type": "후보를 만드는 방식이에요. 계절형은 일정이 있어서 여기서 만들 수 없어요.",
    "sf_hint_target_type": "어떤 종류의 낱말인지 골라요. 종류에 따라 붙는 확장어가 달라져요.", "sf_hint_scope": "공통은 여러 채널에서 쓸 수 있고, 채널을 고르면 그 채널에서만 써요.",
    "sf_hint_sponsor_tag": "협찬 가능 Seed 는 분야를 하나 골라야 해요.", "sf_placeholder_words": "쉼표로 나눠서 적어요", "sf_placeholder_keyword": "예) 출발 낱말 하나", "sf_placeholder_name": "예) 분류 이름",
    "sf_placeholder_reason": "예) 이런 글감이 필요해서",
    # 칸 옆의 오류·주의 문장(블로그 관리와 같은 문장은 `bf_err_*` 를 함께 쓴다)
    "sf_err_overlap": "제외 키워드에 있는 낱말은 우선 키워드로 쓸 수 없어요.", "sf_err_no_letters": "글자나 숫자가 하나는 있어야 해요.", "sf_err_claim": "결과를 약속하는 표현은 쓸 수 없어요.",
    "sf_err_same_word": "같은 소속에 같은 낱말이 이미 있어요.", "sf_err_channels_none": "허용 채널을 하나 이상 골라 주세요.", "sf_err_tag_needed": "협찬 가능 Seed 는 분야를 하나 골라야 해요.",
    "sf_err_brand_reason": "브랜드 예외 Seed 는 이유를 꼭 적어야 해요.", "sf_warn_active_channels": "사용 중인 Seed 라서 채널을 바꾸면 그 채널의 후보 생성에 바로 반영돼요.",
    # 행동 줄
    "seeds_actions_a11y": "Seed 행동 줄", "seeds_act_approve": "승인하기", "seeds_act_rest_proposed": "쉬게 두기", "seeds_act_rest": "쉬게 하기", "seeds_act_resume": "다시 쓰기", "seeds_act_save": "저장",
    "seeds_act_revert": "되돌리기", "seeds_act_create": "승인 전으로 등록", "seeds_act_cancel": "취소",
    "seeds_act_approve_hint": "승인하면 사용 중이 되고 그때부터 후보 생성에 쓰여요.", "seeds_act_rest_proposed_hint": "승인하지 않고 쉬는 중으로 둬요. 나중에 다시 쓸 수 있어요.",
    "seeds_act_unsaved": "저장하지 않은 변경이 있어요. 먼저 저장하거나 되돌려 주세요.", "seeds_act_working": "저장하는 중에는 쓸 수 없어요.", "seeds_act_nothing": "바꾼 내용이 없어요.",
    "seeds_act_revert_nothing": "되돌릴 변경이 없어요.",
    "seeds_saving": "저장하는 중이에요…", "seeds_save_invalid": "입력한 값 중에 확인할 곳이 있어요. 표시된 칸을 고쳐 주세요.",
    # 새 Seed 서랍
    "seeds_new_title": "새 Seed 등록", "seeds_new_a11y": "새 Seed 등록 입력", "seeds_new_note": "등록한 Seed 는 승인 전으로 시작해요. 승인하기 전에는 후보 생성에 쓰이지 않아요. 번호는 프로그램이 정해요.",
    # 결과·실패
    "seeds_saved": "저장했어요.", "seeds_unchanged": "바뀐 내용이 없어요.", "seeds_approved": "승인했어요. 이제 후보 생성에 쓰여요.", "seeds_rested": "쉬게 했어요. 후보 생성에서 빠져요.", "seeds_resumed": "다시 쓰기로 했어요.",
    "seeds_bulk_done_activate": "{n}개를 사용 중으로 바꿨어요.", "seeds_bulk_done_rest": "{n}개를 쉬는 중으로 바꿨어요.",
    "seeds_created": "승인 전 Seed 로 등록했어요. 승인하기 전에는 후보 생성에 쓰이지 않아요.", "seeds_imported": "{n}개를 승인 전 Seed 로 등록했어요. 항목마다 승인하기 전에는 후보 생성에 쓰이지 않아요.",
    "seeds_stale_reloaded": "다른 곳에서 바뀐 내용을 다시 불러왔어요. 입력한 내용은 그대로 두었어요. 확인한 뒤 다시 해 주세요.",
    "seeds_fail_conflict": "다른 곳에서 먼저 바뀌었어요. 입력한 내용은 그대로 두었어요. 최신 내용을 불러오는 중이에요.",
    "seeds_fail_busy": "다른 창에서 저장하는 중이에요. 잠시 뒤에 다시 해 주세요. 입력한 내용은 그대로예요.",
    "seeds_fail_io": "파일을 저장하지 못했어요. 쓸 수 없는 폴더이거나 다른 프로그램이 파일을 쓰고 있을 수 있어요. 기존 내용은 그대로이고 입력한 내용도 남아 있어요.",
    "seeds_fail_disk": "저장 공간이 부족해서 저장하지 못했어요. 기존 내용은 그대로예요. 공간을 확보한 뒤 다시 해 주세요.",
    "seeds_fail_invalid": "입력한 값 중에 확인할 곳이 있어요. 표시된 칸을 고친 뒤 다시 해 주세요. 아무것도 바뀌지 않았어요.",
    "seeds_fail_corrupt": "Seed 파일을 읽지 못해서 저장하지 않았어요. 파일은 고치거나 지우지 않았어요. 계속되면 진단 정보를 함께 알려 주세요.",
    "seeds_fail_other": "저장하지 못했어요. 기존 내용은 그대로이고 입력한 내용도 남아 있어요.",
    # 제안 파일 불러오기
    "seeds_pick_title": "제안 파일 고르기", "seeds_pick_filter": "제안 파일", "seeds_imp_title": "제안 파일을 불러올까요?", "seeds_imp_title_blocked": "제안 파일을 불러올 수 없어요", "seeds_imp_title_none": "새로 등록할 Seed 가 없어요",
    "seeds_imp_counts": "파일 안 Seed {total}개 · 새로 등록할 Seed {new}개 · 이미 있어 건너뜀 {skipped}개 · 읽을 수 없어 뺀 Seed {rejected}개(지금 등록된 Seed {existing}개)",
    "seeds_imp_all_proposed": "새로 등록하는 Seed 는 모두 승인 전이에요. 승인하기 전에는 후보 생성에 쓰이지 않아요. 이미 있는 Seed 는 건드리지 않아요.",
    "seeds_imp_channels": "승인하면 채널마다 쓸 수 있게 되는 Seed 수: {rows}", "seeds_imp_channel_row": "{name} {n}개({gen})", "seeds_imp_reasons": "{title}: {rows}", "seeds_imp_reason_row": "‘{name}’ {reason}",
    "seeds_imp_title_skipped": "이미 있어 건너뜀", "seeds_imp_title_rejected": "읽을 수 없어 뺌", "seeds_imp_more": "외 {n}건",
    "seeds_imp_blocked": "읽을 수 없는 Seed 가 있어서 아무것도 저장하지 않아요. 파일을 고친 뒤 다시 불러와 주세요.", "seeds_imp_none": "저장할 것이 없어서 아무것도 바뀌지 않아요.",
    "seeds_imp_ok": "승인 전으로 등록", "seeds_imp_cancel": "취소", "seeds_imp_close": "닫기", "seeds_imp_failed": "제안 파일을 읽지 못했어요. 파일이 있는지, 제안 파일 모양이 맞는지 확인해 주세요. 아무것도 바뀌지 않았어요.",
    "seeds_imp_reading": "제안 파일을 읽는 중이에요…",
    # 읽는 중·오류·예시·처음
    "seeds_loading": "Seed 를 읽고 있어요…", "seeds_loading_a11y": "Seed 를 읽는 중", "seeds_error_title": "Seed 를 읽지 못했어요.",
    "seeds_error_desc": "Seed 파일은 고치거나 지우지 않았어요. 잠시 뒤에 다시 읽어 보세요. 계속되면 아래 진단 정보를 함께 알려 주세요.", "seeds_error_btn": "다시 읽기",
    "seeds_sample_tip": "화면에 보이는 Seed 는 모두 예시예요. 바꿔도 이 PC 의 파일에는 쓰지 않아요.",
    "seeds_sample_dialog_body": "지금 보이는 Seed 낱말과 분류는 화면을 확인하려고 넣어 둔 예시예요. 여기서 승인하거나 고쳐도 이 PC 의 파일에는 아무것도 쓰지 않아요.",
    "seeds_missing_note": "아직 저장한 Seed 가 없어요. 제안 파일을 불러오거나 새 Seed 를 등록하면 이 PC 의 데이터 폴더에 파일이 만들어져요.",
    "seeds_profiles_unknown": "채널 프로필을 읽지 못해서 후보 생성이 켜져 있는지는 확인하지 못했어요.",
}
