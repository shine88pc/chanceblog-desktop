"""초안 작성 화면의 문구 — `text.py` 의 `T` 에 합쳐진다(`T.update(DRAFT_T)`). 쉬운 한국어(`~해요`)로 새로 썼고, 결과를 약속하는 표현(`FORBIDDEN`)·월 검색량 같은 말·영문 오류 코드·예외 글·명령줄 글은 없다 — `test_ui_drafts_core` 가 모든 문구에 대어 본다.

이 파일에는 실제 블로그 이름·후보 제목·키워드·글이 없다(후보와 블로그 이름은 이 PC 의 보관함·프로필에서 런타임에 읽고, 초안은 서비스가 만든다). 문장에 들어가는 이름·낱말은 모두 비밀 모양을 가린 뒤에 줄인 값이다.
선택 입력 칸의 이름은 여기에 없다 — 서비스(`DraftOptions`)의 이름을 그대로 쓴다(서비스의 확인 권장 문장이 '‘실제 사용 경험’ 칸' 처럼 그 이름으로 가리키기 때문이다).
"""
from __future__ import annotations

DRAFT_T = {
    # 화면 머리·빈 화면·거절·오류
    "drf_title": "초안 작성", "drf_sub": "후보 하나로 AI 없이 초안을 만들어요. 확인하고 고친 뒤 항목별로 복사해요. 저장은 하지 않아요.",
    "drf_back": "← 주제 후보", "drf_back_a11y": "주제 후보로 돌아가기", "drf_to_topics": "주제 후보로 가기",
    "drf_sample_tip": "화면에 보이는 후보·블로그 이름·글은 모두 예시예요. 실제 후보가 아니에요.",
    "drf_sample_dialog_body": "지금 보이는 후보·블로그 이름·초안은 모두 화면을 확인하려고 만든 예시예요. 실제 후보나 실제 블로그가 아니에요. 실제 후보로 초안을 만들면 이 표시가 사라져요.",
    "drf_empty_title": "주제 후보에서 후보를 골라 '이 주제로 만들기' 를 눌러 주세요",
    "drf_refused_title": "이 후보는 초안을 자동으로 만들지 않아요.", "drf_refused_desc": "안전 판정에서 ‘자동 초안 중지’ 로 표시된 후보라 본문을 만들지 않았어요. 주제 후보에서 이유를 확인해 주세요.",
    "drf_channel_title": "이 후보는 네이버 블로그용이 아니에요.", "drf_channel_desc": "지금은 네이버 블로그 A·B 후보만 초안을 만들 수 있어요.",
    "drf_notfound_title": "후보를 찾지 못했어요.", "drf_notfound_desc": "보관함에서 이 후보가 없어졌을 수 있어요. 주제 후보에서 다시 골라 주세요.",
    "drf_error_title": "초안을 만들지 못했어요.", "drf_error_desc": "잠시 뒤에 다시 시도해 주세요. 계속되면 아래 진단 정보를 함께 알려 주세요.", "drf_error_btn": "다시 만들기",
    "drf_loading": "초안을 만드는 중이에요…", "drf_loading_a11y": "초안을 만드는 중", "drf_making": "새 초안을 만드는 중이에요…", "drf_made_again": "새 초안을 만들었어요.",
    "drf_note_rejected": "이 후보는 ‘제외’ 상태예요. 초안만 만들었고 후보 상태는 바꾸지 않았어요.", "drf_note_other_blog": "이 후보는 {channel} 용으로 골랐지만 {blog} 용으로 만들었어요.",
    "drf_fail_io": "후보 보관함이나 설정 파일을 읽지 못했어요. 파일을 쓰고 있는 프로그램이 없는지 확인한 뒤 다시 시도해 주세요.",
    "drf_fail_newer": "더 새로운 프로그램이 만든 후보 보관함이라 이 프로그램으로는 읽을 수 없어요.",
    "drf_fail_corrupt": "후보 보관함이나 설정 파일을 읽지 못했어요. 파일은 고치거나 지우지 않았어요.",
    "drf_fail_invalid": "이 후보의 글을 초안에 쓸 수 없어요. 주제 후보에서 내용을 확인해 주세요.", "drf_fail_other": "초안을 만들지 못했어요. 잠시 뒤에 다시 시도해 주세요.",
    "drf_fail_notfound": "보관함에서 이 후보를 찾지 못했어요. 주제 후보에서 다시 골라 주세요.",
    "drf_fail_option": "‘{field}’ 칸을 다시 확인해 주세요 — {reason}", "drf_fail_option_plain": "선택 입력의 한 칸을 다시 확인해 주세요.",
    # 초안 화면 — 맥락·제목·본문
    "drf_ctx_candidate": "후보: {title}", "drf_ctx_made": "{blog} 용 · 글 유형 {post_type}", "drf_ctx_a11y": "이 초안을 만든 후보와 블로그",
    "drf_title_label": "제목", "drf_title_input_a11y": "제목 입력 — 직접 고칠 수 있어요", "drf_title_picks": "제목 후보", "drf_title_pick": "후보 {n}", "drf_pick_selected": "선택됨", "drf_title_pick_a11y": "제목 후보 {n}: {text}",
    "drf_body_label": "본문", "drf_body_a11y": "본문 편집기 — 글자를 직접 고칠 수 있어요", "drf_count": "본문 {n}자(공백 제외) · 공백 포함 {m}자",
    "drf_edit_none": "고친 부분이 없어요", "drf_edit_some": "고친 부분이 있어요(약 {n}자)",
    "drf_edit_locked": "새 초안을 만드는 동안에는 고칠 수 없어요.",
    # 만드는 방법(선택 입력·블로그·글 유형)
    "drf_options_open": "만드는 방법 바꾸기", "drf_options_close": "만드는 방법 접기", "drf_options_title": "만드는 방법(선택)",
    "drf_options_note": "모두 선택이에요. 비워 두면 후보와 블로그 기본값으로 만들어요. 바꾼 뒤 ‘다시 만들기’ 를 눌러야 새 초안에 들어가요.",
    "drf_blog_label": "블로그", "drf_blog_a11y": "{name} 용으로 만들기", "drf_type_label": "글 유형", "drf_type_auto": "후보 기준", "drf_type_a11y": "글 유형 {name}",
    "drf_remake": "다시 만들기", "drf_remake_tip": "위 설정으로 새 초안을 만들어요. 고친 제목·본문이 있으면 먼저 물어봐요.",
    "drf_options_pending": "적은 선택 입력을 아직 반영하지 않았어요 — ‘다시 만들기’ 를 눌러야 새 초안에 들어가요.", "drf_opt_a11y": "{label} 입력(선택)",
    "drf_hint_message": "독자에게 꼭 전하고 싶은 말을 한 줄로 적어요. 적은 그대로 본문에 들어가요.",
    "drf_hint_experience": "직접 써 보거나 다녀온 일이 있을 때만 적어요. 적지 않으면 경험은 넣지 않아요.",
    "drf_hint_opinion": "내 의견을 한 줄로 적어요. 적은 그대로 들어가요.", "drf_hint_conclusion": "글의 결론을 한 줄로 적어요.",
    "drf_hint_audience": "누구를 위한 글인지 적어요. 비우면 블로그의 기본 독자를 써요.", "drf_hint_must_include": "꼭 넣고 싶은 문장을 줄마다 하나씩 적어요.",
    "drf_hint_price_date": "직접 확인한 가격이나 날짜만 줄마다 하나씩 적어요.", "drf_hint_urls": "https 로 시작하는 공개 주소를 줄마다 하나씩 적어요. 앱은 그 주소를 열어 보지 않아요.",
    # 오른쪽 칸
    "drf_side_inspect": "검사 결과", "drf_inspect_btn": "검사하기", "drf_inspect_btn_a11y": "제목과 본문 검사하기", "drf_inspect_hint": "글을 고친 뒤 눌러 보세요. 복사할 때도 자동으로 확인해요.",
    "drf_inspect_before": "아직 검사하지 않았어요.", "drf_inspect_stale": "글을 고쳤어요 — 다시 검사해 주세요.", "drf_inspect_secret": "키나 토큰처럼 보이는 글이 있어요. 지우기 전에는 복사할 수 없어요.",
    "drf_inspect_claims": "확인이 필요한 곳이 {n}곳 있어요.", "drf_inspect_unchanged": "거의 고치지 않은 초안이에요(고친 글자 약 {n}자). 직접 경험·사실을 보태 주세요.",
    # 검사 카드는 **무엇을 봤는지**를 밝힌다(독립 검증 V3 — 걸린 곳이 없다는 말이 '아무 문제 없다' 로 읽히지 않게). 초록 문구는 점검 범위 안에서만 말한다
    "drf_inspect_ok": "경험·방문·가격·날짜·통계 표시와 키 모양, 건강 단정 낱말은 걸리지 않았어요 — 숫자로 말한 효과나 협찬 표시처럼 이 검사가 보지 못하는 것은 직접 확인해 주세요.",
    "drf_inspect_health_stop": "건강 효과를 단정하거나 약속하는 표현이 있어요(주의를 주려고 쓴 문장도 막힐 수 있어요). 고치기 전에는 복사할 수 없어요.",
    "drf_inspect_health_check": "건강과 관련된 말이 있어요 — 효과를 단정하거나 약속하지 않았는지 읽어 보세요.",
    "drf_side_keywords": "키워드", "drf_kw_core": "핵심", "drf_kw_sub": "보조", "drf_copy_keywords": "키워드 복사", "drf_copied_keywords": "✓ 키워드 복사됨",
    "drf_side_tags": "태그", "drf_copy_tags": "태그 복사", "drf_copied_tags": "✓ 태그 복사됨",
    "drf_side_category": "추천 카테고리", "drf_category_none": "정하지 못했어요 — 블로그에서 직접 골라 주세요.",
    "drf_side_summary": "한 줄 요약", "drf_copy_summary": "요약 복사", "drf_copied_summary": "✓ 요약 복사됨",
    "drf_side_image": "대표 이미지", "drf_image_before": "이미지 검색 전", "drf_image_skip": "이미지 없이 진행", "drf_image_desc": "이미지 검색은 다음 단계에서 연결해요. 지금은 이미지 없이 진행할 수 있어요.",
    "drf_image_btn": "이미지 없이 진행", "drf_image_btn_a11y": "이미지 없이 진행하기", "drf_image_undo": "되돌리기", "drf_image_undo_a11y": "이미지 검색 전 상태로 되돌리기",
    # 확인 권장
    "drf_side_checks": "확인 권장", "drf_chk_specific": "이 글에만 해당", "drf_chk_specific_none": "이 글에만 해당하는 확인 권장은 없어요.", "drf_chk_common": "모든 글 공통", "drf_chk_count": "{n}건",
    "drf_chk_domain": "주제의 분야를 읽지 못했어요 — 일반적인 확인 순서만 담았으니 글이 주제에 맞는지 읽어 보세요.",
    "drf_chk_replaced": "후보의 ‘{old}’ 형식은 ‘{new}’ 으로 바꿔 구성했어요 — 경험을 지어내지 않아요.",
    "drf_chk_profile": "이 블로그의 프로필이 아직 없어 공통 기본값으로 만들었어요 — 블로그 관리에서 프로필을 정하면 그 값이 먼저 적용돼요.",
    # 출처와 확인 필요 상태(P4e 완료 조건 ⑭) — 확인 권장 카드 맨 위 한 줄: 이 글이 기대는 출처(규칙 기반이라 외부 자료는 없고, 사용자가 적은 참고 주소만 있다)와 확인할 줄 수
    "drf_chk_status": "출처: {source} · 확인 필요 {total}건(이 글에만 해당 {specific}건)",
    "drf_chk_source_none": "참고 주소 없음 — 사실·가격·날짜는 직접 확인해 주세요",
    "drf_chk_source_some": "참고 주소 {n}개(앱은 주소를 열어 보지 않아요)",
    # 직접 쓴 글(선택 입력·고친 글)에 건강 낱말이 있을 때 확인 권장에 더하는 줄 — 후보 글은 서비스가 이미 줄을 붙이므로 직접 쓴 글만 본다(독립 검증 V3)
    "drf_chk_health_mark": "직접 쓴 글에 건강과 관련된 말이 있어요 — 효과나 결과를 단정하지 않았는지 읽어 보세요.",
    "drf_chk_health_evidence": "직접 쓴 글에 건강 효과와 관련된 말이 있어요 — 근거를 확인할 수 없는 내용은 빼 주세요.",
    # 아래 고정 행동 줄
    "drf_copy_title": "제목 복사", "drf_copy_body": "본문 복사", "drf_copy_all": "전체 복사", "drf_copied_title": "✓ 제목 복사됨", "drf_copied_body": "✓ 본문 복사됨", "drf_copied_all": "✓ 전체 복사됨",
    "drf_copy_tip_title": "제목을 복사해요. 고친 그대로 복사돼요.", "drf_copy_tip_body": "본문을 복사해요. 고친 그대로 복사돼요.", "drf_copy_tip_all": "제목과 본문을 이어서 복사해요.",
    "drf_open_naver": "네이버 글쓰기 열기", "drf_open_tip": "브라우저로 글쓰기 주소만 열어요. 로그인·입력·발행은 하지 않아요.",
    "drf_open_why_profile": "블로그 관리에서 이 블로그의 주소를 정하면 열 수 있어요.", "drf_open_why_wait": "초안을 만든 뒤에 열 수 있어요.", "drf_actions_a11y": "복사와 열기 행동 줄",
    "drf_copy_failed": "복사하지 못했어요. 다시 시도해 주세요.", "drf_open_failed": "주소를 열지 못했어요.",
    # 확인창들
    "drf_cancel": "취소", "drf_gate_title": "확인 권장 {n}건을 읽었나요?", "drf_gate_checks": "이 글에만 해당하는 확인 권장 {n}건", "drf_gate_domain": "분야 확인 {n}건",
    "drf_gate_claims": "고친 글에서 확인이 필요한 곳 {n}곳", "drf_gate_unchanged_head": "고친 정도", "drf_gate_unchanged": "거의 고치지 않은 초안이에요 — 직접 경험·사실을 보태 주세요(막지는 않아요).",
    "drf_soft_title": "거의 고치지 않은 초안이에요", "drf_soft_body": "직접 겪은 경험이나 확인한 사실을 보태면 더 믿을 수 있는 글이 돼요. 이대로 복사해도 막지는 않아요.",
    "drf_gate_line": "· {text}", "drf_gate_more": "… 외 {n}건", "drf_gate_ok": "그래도 복사", "drf_gate_tail": "읽어 본 뒤에 그래도 복사할 때만 ‘그래도 복사’ 를 눌러 주세요. 취소하면 복사하지 않아요.",
    "drf_secret_title": "복사할 수 없어요", "drf_secret_body": "키나 토큰처럼 보이는 글이 들어 있어서 복사하지 않았어요. 그 부분을 지운 뒤 다시 눌러 주세요.", "drf_secret_ok": "확인",
    # 막을 때는 어느 부분이 걸렸는지 앞부분만 짚어 준다(독립 검증 V2 — 정상 주소가 걸려도 어디가 문제인지 알 수 있게). 비밀 모양은 가리고 보인다
    "drf_health_body": "건강 효과를 단정하거나 약속하는 표현이 들어 있어서 복사하지 않았어요. 효과가 없다고 알리거나 주의를 주는 문장도 같은 낱말 때문에 막힐 수 있어요. 건너뛰는 단추는 없으니 그 문장을 고치거나 지운 뒤 다시 눌러 주세요.",
    "drf_where_head": "걸린 곳(앞부분만 보여요)", "drf_where_title": "제목", "drf_where_body": "본문",
    "drf_spot_hidden": "[가림]",                              # 이름·모양으로 알아본 비밀(주소 인자의 긴 값·웹훅 …)은 글자를 보이지 않고 어디서부터인지만 짚는다(독립 검증 D1). 공백이 없어야 가림 규칙이 한 덩어리로 읽는다
    "drf_leave_title": "고친 내용이 사라져요", "drf_leave_body": "이 초안은 저장하지 않아서 다른 화면으로 가면 고친 내용이 사라져요. 그래도 이동할까요?", "drf_leave_ok": "그래도 이동",
    "drf_close_body": "이 초안은 저장하지 않아서 앱을 닫으면 고친 내용이 사라져요. 그래도 닫을까요?", "drf_close_ok": "그래도 닫기",
    "drf_regen_title": "고친 내용이 사라져요 — 다시 만들까요?", "drf_regen_body": "새 초안을 만들면 지금 고친 제목·본문이 사라져요. 적어 둔 선택 입력은 새 초안에 들어가요.", "drf_regen_ok": "다시 만들기",
    "drf_pick_title": "제목을 바꿀까요?", "drf_pick_body": "고친 제목이 사라지고 고른 제목 후보로 바뀌어요.", "drf_pick_ok": "제목 바꾸기",
    # 후보 상세의 아래 고정 행동 줄
    "drf_make": "이 주제로 만들기", "drf_make_a11y": "이 주제로 초안 만들기", "drf_make_tip": "이 후보로 AI 없이 초안을 만들어요. 아무것도 저장하지 않아요.",
    "drf_make_why_stop": "자동 초안 중지로 표시된 후보라 초안을 만들지 않아요.", "drf_make_why_channel": "지금은 네이버 블로그 후보만 초안을 만들 수 있어요.", "drf_make_why_wait": "후보를 만드는 중에는 쓸 수 없어요.",
    "drf_detail_actions_a11y": "후보 행동 줄",
}
