"""'내 글 문체 참고값 보기'(N-3a)의 문구 — `text.py` 의 `T` 에 합쳐진다(`T.update(STYLE_T)`). 쉬운 한국어로 새로 썼고, 결과를 약속하는 표현(`FORBIDDEN`)·영문 오류 코드·예외 글·판정 라벨(`전문적`·`격식체` 같은 말)은 없다 —
`test_ui_style_core` 가 모든 문구에 대어 본다.

이 파일에는 글의 문장·낱말이 없다(고른 글은 이 PC 에서 메모리로만 읽고 숫자만 화면에 나간다). 숫자 이름은 **겉모양 그대로**다 — `‘…니다·…니까·…십시오’ 로 끝나는 문장` 처럼 어떻게 센 숫자인지만 말하고 글의 성격을 말하지 않는다.
숫자 옆 안내는 `style_trust` 하나이고 형태소 분석이 아니라 글자 모양을 세는 규칙이라 오차가 있다는 사실은 `style_rough` 가 말한다(문장 끝뿐 아니라 문장 나누기·문장 수·문단 수·질문형·목록 비율에도 오차가 있다 — D-432).
결과 표 아래에는 `style_yours_result` 한 줄이 더 있어, 직접 쓴 글만 골랐을 때의 숫자라는 것을 결과 화면만 봐도 알게 한다(D-434).
"""
from __future__ import annotations

STYLE_T = {
    # 설정 화면 맨 아래의 작은 카드(진입점) — 프로필·초안과 무관한 읽기 전용 대화상자 하나를 연다
    "style_entry_title": "내 글 문체 참고값 보기",
    "style_entry_desc": "직접 쓴 글 1–2개를 골라 문장 길이·문단·문장 끝 모양 같은 숫자를 참고용으로만 보여 드려요. 저장하지 않고 AI 도 쓰지 않아요.",
    "style_entry_open": "열기", "style_entry_open_a11y": "내 글 문체 참고값 보기 열기",
    # 대화상자 — 글 고르기
    "style_title": "내 글 문체 참고값 보기",
    "style_intro": "직접 쓴 글 1–2개를 이 컴퓨터 안에서만 읽어 숫자로 보여 드려요. 저장하지 않고 AI 도 쓰지 않으며, 창을 닫으면 모두 사라져요.",
    "style_only_yours": "직접 쓴 글만 골라 주세요. 다른 사람의 글이나 AI 가 쓴 글이면 이 숫자는 내 글의 모습이 아니에요.",
    "style_pick": "파일 고르기", "style_pick_a11y": "글 파일 고르기", "style_pick_title": "내 글 파일 고르기", "style_pick_filter": "글 파일",
    "style_pick_hint": "텍스트(txt)나 마크다운(md) 파일을 한 번에 하나씩 골라요. 글은 파일과 붙여 넣은 글을 모두 합쳐 최대 2개예요.",
    "style_pick_full": "글은 최대 2개까지 고를 수 있어요.",
    "style_slots_title": "고른 글", "style_slots_a11y": "고른 글 목록",
    "style_slot": "글 {n} · {kind}", "style_kind_file": "파일에서 가져옴", "style_kind_pasted": "붙여 넣은 글",
    "style_remove": "빼기", "style_remove_a11y": "글 {n} 빼기",
    "style_paste_label": "또는 직접 쓴 글을 여기에 붙여 넣어요", "style_paste_a11y": "붙여 넣을 글",
    "style_paste_hint": "10만 자까지예요. 숫자를 세고 나면 이 칸은 비워져요.", "style_paste_count": "{n}자", "style_paste_count_a11y": "붙여 넣은 글자 수 {n}자",
    "style_compute": "계산하기", "style_compute_a11y": "고른 글의 문체 숫자 계산하기",
    "style_close": "닫기", "style_close_a11y": "내 글 문체 참고값 보기 닫기",
    "style_again": "다른 글로 다시 하기", "style_again_a11y": "결과를 지우고 다른 글로 다시 하기",
    "style_none_yet": "글 파일을 고르거나 글을 붙여 넣은 뒤 ‘계산하기’ 를 눌러 주세요.",
    "style_running": "숫자를 세는 중이에요…", "style_running_a11y": "숫자를 세는 중",
    "style_fail_other": "숫자를 세지 못했어요. 글을 다시 골라 주세요.",
    "style_fail_toomany": "글은 최대 2개까지 계산할 수 있어요.",
    # 결과 표
    "style_result_title": "세어 본 숫자", "style_result_a11y": "문체 참고값 표",
    "style_col_item": "항목", "style_col_one": "글 {n}", "style_col_one_pasted": "글 {n} (붙여 넣음)", "style_col_range": "범위", "style_col_total": "두 글 합산",
    "style_unknown": "알 수 없음",
    "style_unit_chars": "자", "style_unit_sentences": "문장", "style_unit_count": "개",
    "style_row_sentence_length": "평균 문장 길이(공백 뺀 글자)", "style_row_per_paragraph": "문단당 문장 수", "style_row_headings": "소제목 수",
    "style_row_end_formal": "‘…니다·…니까·…십시오’ 로 끝나는 문장", "style_row_end_polite": "‘…요·…죠’ 로 끝나는 문장", "style_row_end_plain": "‘…다’ 로 끝나는 문장(위에 든 것 제외)", "style_row_end_other": "그 밖의 모양으로 끝나는 문장",
    "style_row_question": "질문형 문장", "style_row_list": "목록 사용(목록 ÷ (목록 + 문단))",
    "style_row_a11y": "{label}: {cells}", "style_cell_a11y": "{column} {value}", "style_range_a11y": "범위 {value}", "style_total_a11y": "두 글 합산 {value}",
    "style_counts": "글 {n} — 문장 {sentences}개 · 문단 {paragraphs}개 · 목록 {lists}개 · 글자 {chars}자(공백 뺀)",
    "style_counts_one": "문장 {sentences}개 · 문단 {paragraphs}개 · 목록 {lists}개 · 글자 {chars}자(공백 뺀)",
    "style_counts_title": "센 개수",
    "style_range_only": "글 사이 차이가 커서 평균 대신 범위만 보여 드려요.",
    "style_total_note": "합산은 두 글의 문장·문단을 모아서 센 값이에요.",
    # 안내 — 숫자 옆에는 이 한 문장, 오차와 흔들림은 아래 줄들
    "style_trust": "이 숫자는 고른 글을 세어 본 참고값이에요. 글의 성격이나 전문성을 판단하는 값이 아니에요.",
    "style_yours_result": "직접 쓴 글만 골랐을 때의 숫자예요. 다른 사람의 글이나 AI 가 쓴 글이면 이 숫자는 내 글의 모습이 아니에요.",
    "style_rough": "문장 나누기와 문장 끝은 글자 모양만 보고 세는 규칙이라, 문장 수·문단 수·질문형·목록 비율이 실제와 조금 다를 수 있어요.",
    "style_notes_title": "알아 두세요", "style_scope": "글 {n} — ",
    "style_notice_empty": "세어 볼 문장이 없어요. 표·그림·코드뿐인 글일 수 있어요.",
    "style_notice_short": "글이 짧아서(문장 10개 미만이거나 글자 600자 미만) 숫자가 흔들려요.",
    "style_notice_quote": "인용이 많으면 본인 글 숫자가 아닐 수 있어요.",
    "style_notice_low_hangul": "한글이 적은 글이라 문장 끝 비율이 맞지 않아요.",
    "style_notice_casual": "이모지나 ㅋㅋ 같은 것으로 끝나는 문장이 많아서 문장 끝 비율이 맞지 않을 수 있어요.",
    "style_notice_wrap": "줄바꿈 습관에 따라 문장 수 같은 숫자가 달라질 수 있어요.",
    "style_notice_cp949": "CP949 로 읽은 글이에요. 다른 글자표로 저장된 글이면 숫자가 어긋날 수 있으니 UTF-8 로 저장해 다시 골라 주세요.",
    "style_scroll_a11y": "문체 참고값 대화상자 내용",
}
