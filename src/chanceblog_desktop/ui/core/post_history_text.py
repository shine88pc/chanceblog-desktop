"""발행 기록 화면과 작업 로그 카드(글 흐름 1b, 결정 D-649·D-650)의 문구 — `ui/core/text.py` 의 `T` 에 합쳐진다. 쉬운 한국어 해요체이고, 영문 오류 코드·개발자 낱말·결과를 약속하는 표현은 쓰지 않는다(시험이 모든 글에 대어 본다).
상태·플랫폼 이름은 글 검토 화면의 것(`post_status_*`·`post_platform_*`)을 그대로 쓴다 — 여기에는 글 검토가 다루지 않는 블로거 이름만 더한다.
"""
from __future__ import annotations

HIST_T = {
    # 머리·메뉴 — 메뉴 이름(`nav_history`)은 `text.py` 에 이미 있고 화면 제목과 같은 글자다
    "hist_title": "발행 기록",
    "hist_sub": "승인한 뒤의 글이 여기 모여요. 어느 플랫폼에서 어디까지 했는지와 직접 발행한 글의 주소를 볼 수 있어요. 이 화면은 읽기만 해요.",
    "hist_reload": "다시 읽기", "hist_reload_a11y": "발행 기록 다시 읽기",
    "hist_order_to_newest": "최신 순서로 보기", "hist_order_to_oldest": "오래된 순서로 보기",
    "hist_order_a11y_oldest": "발행 기록 순서. 지금은 오래된 순서예요. 누르면 최신 순서로 바뀌어요", "hist_order_a11y_newest": "발행 기록 순서. 지금은 최신 순서예요. 누르면 오래된 순서로 바뀌어요",
    "hist_order_now_oldest": "오래된 순서", "hist_order_now_newest": "최신 순서",
    "hist_sample_tip": "화면에 보이는 글과 주소는 모두 예시예요. 실제 기록이 아니에요.",
    "hist_sample_dialog_body": "지금 보이는 글, 상태, 주소, 작업 로그는 화면을 확인하려고 넣어 둔 예시예요. 실제 데이터를 읽으면 이 표시가 사라져요.",
    # 목록의 여섯 상태
    "hist_loading": "발행 기록을 읽고 있어요…", "hist_loading_a11y": "발행 기록을 읽는 중",
    "hist_empty_title": "아직 발행 기록이 없어요", "hist_empty_desc": "글을 승인하고 복사하거나 올리면 여기에 모여요.",
    "hist_empty_button": "글 검토로 가기", "hist_empty_button_a11y": "글 검토 화면으로 가기",
    "hist_error_title": "발행 기록을 읽지 못했어요.", "hist_error_desc": "잠시 뒤에 다시 시도해 주세요. 계속되면 아래 진단 정보를 함께 알려 주세요.", "hist_retry": "다시 시도",
    "hist_partial": "읽지 못한 글이 {n}개 있어요. 나머지 기록은 그대로 볼 수 있어요.",
    "hist_offline": "오프라인 상태예요. 이 PC 에 저장해 둔 기록만 보여 드려요.",
    "hist_count": "기록 {n}건", "hist_list_a11y": "발행 기록 목록",
    "hist_more": "더 보기", "hist_more_a11y": "발행 기록 더 보기",
    # 한 줄
    "hist_row_meta": "{platform} · {status} · {when}", "hist_when_unknown": "때 모름", "hist_row_url": "발행 주소: {url}", "hist_row_a11y": "{title}. {meta}",
    "hist_platform_blogger_en": "Blogger 영문", "hist_platform_blogger_ko": "Blogger 한글", "hist_platform_unknown": "알 수 없는 플랫폼",
    "hist_copy_url": "주소 복사", "hist_copy_url_a11y": "{title} 발행 주소를 클립보드에 복사",
    "hist_copied": "발행 주소를 복사했어요.", "hist_copy_failed": "복사하지 못했어요. 다른 프로그램이 클립보드를 쓰고 있는지 확인한 뒤 다시 눌러 주세요.",
    "hist_copy_blocked": "키·토큰처럼 보이는 글이 있어서 복사하지 않았어요.", "hist_copy_none": "복사할 주소가 없어요.",
    # 작업 로그 카드
    "hist_log_title": "작업 로그",
    "hist_log_sub": "앱이 처리하지 못한 오류가 났을 때 남긴 기록이에요. 오류 이름과 코드 위치만 있고 글이나 키는 없어요. 이 카드는 읽기만 해요.",
    "hist_log_a11y": "작업 로그", "hist_log_show": "작업 로그 보기", "hist_log_hide": "작업 로그 접기",
    "hist_log_show_a11y": "작업 로그 펼쳐서 읽기", "hist_log_hide_a11y": "작업 로그 접기",
    "hist_log_loading": "작업 로그를 읽고 있어요…", "hist_log_empty": "기록된 오류가 없어요.",
    "hist_log_error": "작업 로그를 읽지 못했어요. 파일은 고치거나 지우지 않았어요.", "hist_log_retry": "작업 로그 다시 읽기", "hist_log_retry_a11y": "작업 로그 다시 읽기",
    "hist_log_line": "{when} · {source} · {name} · {places}", "hist_log_places_none": "코드 위치 없음",
    "hist_log_source_main": "프로그램 본체", "hist_log_source_thread": "작업 스레드", "hist_log_source_unraisable": "정리 중", "hist_log_source_slot": "화면 반응", "hist_log_source_qt": "화면 도구",
    "hist_log_source_unknown": "알 수 없는 곳",
    "hist_log_count": "최근 {n}줄", "hist_log_skipped": "모양이 달라 건너뛴 것 {n}개", "hist_log_older": "더 오래된 {n}줄은 보이지 않아요",
}
