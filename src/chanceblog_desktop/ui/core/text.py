"""화면 문구(한국어)와 숫자·날짜 서식. 문구는 운영자 요구서·명세·목업의 문장을 옮기지 않고 새로 썼다(메뉴·단추·지표 이름처럼 짧은 이름은 그대로).
결과를 약속하는 표현(상위노출 보장·노출 확률·검색 1위 가능성·수익 보장)은 쓰지 않는다 — `FORBIDDEN` 을 시험이 모든 문구에 대어 본다.
영문 오류 코드·스택 트레이스는 이 표에 없다 — 진단 정보 영역(`diagnostic_text`)에만 나간다."""
from __future__ import annotations

import datetime

NO_DATA = "데이터 없음"
SAMPLE_TAG = "예시 데이터"

T = {
    "app_name": "ChanceBlog", "brand_line": "고르고 · 만들고 · 복사하기", "brand_version": "ChanceBlog Desktop",
    # 새 틀(UI-C1a) — 상단 앱 바의 시계, 사이드바 묶음·'다음 단계' 목록, 버전
    "clock_a11y": "현재 날짜와 시간 {text}", "topbar_a11y": "상단 앱 바", "dev_version": "개발 버전",
    "version_release_error": "설치된 프로그램의 버전 정보를 읽지 못했어요. 프로그램을 다시 설치하거나 최신 설치 파일로 업데이트한 뒤 다시 열어 주세요.",
    "nav_group_core": "핵심 작업", "nav_group_data": "데이터·관리", "nav_group_system": "시스템",
    "nav_soon_title": "다음 단계", "nav_soon_a11y": "준비 중 — 아직 열 수 없는 화면", "nav_soon_item_a11y": "{name}, 준비 중",
    "window_title": "ChanceBlog Desktop",
    "nav_home": "홈", "nav_topics": "주제 후보", "nav_draft": "초안 작성", "nav_history": "발행 기록", "nav_seed": "Seed 관리", "nav_blogs": "블로그 관리", "nav_settings": "설정",
    "nav_menu": "주 메뉴", "body_area": "본문", "nav_a11y": "{name} 메뉴로 이동",
    # 예시 데이터 표시와 설명 대화상자
    "sample_tag": SAMPLE_TAG, "sample_tip": "화면에 보이는 주제와 숫자는 예시예요. 실제 수치가 아닙니다.",
    "sample_dialog_title": "예시 데이터예요",
    "sample_dialog_body": "지금 보이는 주제와 숫자는 화면을 확인하려고 넣어 둔 예시예요. 내 블로그의 실제 후보를 불러오면 이 표시가 사라져요.",
    "ok": "확인", "cancel": "취소", "close": "닫기",
    # 홈
    "home_title": "오늘은 어떤 주제로 써 볼까요?", "home_sub": "블로그에 어울리는 주제를 고르면 바로 초안까지 만들어 드려요.",
    "sum_topics": "추천 주제", "sum_done": "작성 완료", "sum_pub": "발행 완료", "sum_ideas": "저장된 아이디어",
    "sum_unavailable": "아직 집계하지 않아요",
    "blog_a": "블로그 A", "blog_b": "블로그 B",
    "make_small": "초안 만들기", "unit_demand": "회", "unit_docs": "건",                  # `make_small` 은 상세 서랍의 초안 단추가 '다음 단계' 안내에 쓰는 이름, `unit_*` 는 서랍의 월간 검색량·검색 결과 수 단위다(홈에는 둘 다 없다)
    "trend_up": "상승", "trend_flat": "보통", "trend_down": "하락",
    "priority": "작성 우선도",
    "refresh": "다시 불러오기", "last_fetch": "마지막 조회 {when}",
    # 홈(UI-C1c·UI-C1d) — 뷰모델(`board_view.py`)이 쓰고 새 홈 화면(UI-C1d)이 그리는 글. 월 검색량·문서 수 글은 없다(가져오지도 보이지도 않는다).
    "board_sample_tag": "예시", "board_score_none": "점수 계산 전", "board_on": "켜짐", "board_off": "꺼짐",
    "board_interest_rising": "관심도 상승", "board_interest_flat": "관심도 보통", "board_interest_falling": "관심도 하락", "board_interest_none": "관심도 데이터 부족",
    "board_rec_title": "{name} 추천", "board_count": "후보 {n}개", "board_rec_empty_title": "아직 추천할 후보가 없어요.", "board_rec_empty_desc": "후보가 만들어지면 점수가 높은 순서로 여기에 보여요.",
    "board_rec_nostore": "후보를 보관하는 파일이 아직 없어요. 이 화면은 읽기만 해서 새로 만들지 않았어요.", "board_rec_oldstore": "후보 보관함이 옛 구조라 읽지 않았어요. 이 화면은 읽기만 해서 바꾸지 않았어요.",
    "board_rec_off": "이 채널은 후보 생성이 꺼져 있어요.", "board_rec_error_title": "추천 후보를 읽지 못했어요.", "board_rec_skipped": "점수를 확인할 수 없어 뺀 후보가 {n}개 있어요.",
    "board_draft_title": "작성 중인 초안", "board_draft_empty_title": "작성 중인 초안이 없어요.", "board_draft_empty_desc": "초안을 만들면 여기에서 이어서 볼 수 있어요.", "board_draft_error_title": "작성 중인 초안을 읽지 못했어요.",
    "board_stage_generated": "초안 생성됨", "board_stage_review": "검토 필요",
    "board_recent_title": "최근 발행", "board_recent_empty_title": "아직 발행한 글이 없어요.", "board_recent_empty_desc": "글을 발행하면 여기에 날짜와 함께 보여요.", "board_recent_error_title": "발행한 글을 읽지 못했어요.",
    "board_date_unknown": "발행일 확인 불가", "board_posts_skipped": "읽지 못해 건너뛴 글이 {n}개 있어요.",
    "board_before_connect": "연결 전", "board_before_count": "집계 전", "board_kpi_connect_sub": "아직 연결하지 않았어요",
    "board_conn_title": "연결 상태", "board_conn_before": "연결 상태를 아직 읽지 않았어요. 설정에서 확인할 수 있어요.", "board_conn_loading": "연결 상태를 읽고 있어요…",
    "board_conn_error": "연결 상태를 읽지 못했어요.", "board_conn_nothing": "연결된 서비스가 아직 없어요.",
    "board_unavailable_title": "아직 불러오지 않았어요.", "board_unavailable_desc": "다시 불러오면 이 자리에 보여요.",
    "board_connect_title": "아직 연결하지 않았어요.", "board_connect_desc": "읽을 수 있게 연결되면 이 자리에 보여요.",
    "board_row_hint": "누르면 상세 정보가 열려요.", "board_section_a11y": "{title}, {count}",
    # 주제 엔진을 읽다 난 오류의 화면용 문장 — 카탈로그 안내문에는 명령줄 글이 섞여 있어 이 문장으로 바꾼다(오류 코드는 진단 정보에 그대로)
    "board_err_store": "후보 보관함을 읽지 못했어요. 파일은 고치거나 지우지 않았어요. 계속되면 진단 정보를 함께 알려 주세요.",
    "board_err_newer": "더 새로운 버전의 프로그램이 만든 후보 보관함이라 열지 않았어요. 프로그램을 최신 버전으로 업데이트해 주세요.",
    "board_err_locked": "후보 보관함을 다른 곳에서 쓰고 있어 잠시 열지 못했어요. 끝난 뒤 다시 읽어 주세요.",
    "board_err_pending": "후보 보관함에 정리하지 못한 저장이 남아 있어 읽지 못했어요. 파일은 바뀌지 않았어요.",
    "board_err_profiles": "주제 엔진 설정 파일을 읽지 못했어요. 파일은 고치거나 지우지 않았어요. 계속되면 진단 정보를 함께 알려 주세요.",
    # 상세 서랍
    "drawer_title": "주제 상세", "drawer_close": "상세 닫기", "d_demand": "월간 검색량", "d_split": "PC·모바일 검색 비중", "d_docs": "관련 블로그 검색 결과 수", "d_trend": "최근 트렌드",
    "d_season": "계절성", "d_written": "기존 작성 여부", "d_sub": "보조 키워드", "d_date": "데이터 조회일", "d_reason": "추천 이유",
    "written_yes": "이미 쓴 글이 있어요", "written_no": "아직 쓴 글이 없어요", "split_value": "PC {pc}% · 모바일 {mobile}%",
    "draft_a": "블로그 A 초안", "draft_b": "블로그 B 초안", "hold": "보류", "more": "더보기",
    # 상태 화면
    "loading": "후보를 불러오고 있어요…", "loading_a11y": "후보를 불러오는 중",
    "error_title": "주제 후보를 불러오지 못했어요.", "error_desc": "잠시 뒤에 다시 시도해 주세요. 계속되면 아래 진단 정보를 함께 알려 주세요.", "retry": "다시 시도",
    "partial": "검색 추세는 불러오지 못했지만 나머지 정보는 그대로 쓸 수 있어요.", "offline": "오프라인 상태예요. 저장해 둔 초안은 계속 고칠 수 있어요.",
    "diag_show": "진단 정보 보기", "diag_hide": "진단 정보 숨기기", "diag_title": "진단 정보", "diag_note": "도움을 받을 때 함께 알려 주세요. 키와 입력한 글은 담기지 않아요.",
    "diag_code": "code", "diag_when": "time",                                  # 진단 정보는 고정폭 글꼴 영역이라 영문·숫자만 둔다(한글은 글꼴이 바뀌어 모양이 달라진다)
    # 안내(토스트)
    "soon_toast": "'{name}' 은(는) 다음 단계에서 열려요.", "load_cancelled": "불러오기를 취소했어요. 보이던 내용은 그대로예요.", "load_busy": "이미 불러오는 중이에요.",
    "load_failed_toast": "불러오지 못했어요. 다시 시도해 주세요.", "job_failed": "작업을 마치지 못했어요. 입력한 내용은 그대로 남아 있어요.", "job_cancelled": "작업을 취소했어요. 입력한 내용은 그대로예요.",
    "data_dir_missing": "지정한 데이터 폴더를 찾지 못했어요. 폴더 이름을 확인한 뒤 다시 열어 주세요.",
    "data_unreadable": "데이터 폴더를 읽지 못했어요. 다른 프로그램이 쓰고 있지 않은지 확인한 뒤 다시 시도해 주세요.",
    "unexpected_line": "화면에서 처리하지 못한 오류가 있었어요",                           # 표준 오류에 한 줄로만 남는다(예외 이름 + 비밀·경로를 가린 짧은 글)
    "cancel_job": "작업 취소", "load_cancel": "불러오기 취소",
    # 이미지 자리 표시·출처(Unsplash)·내 사진
    "credit_line": "Photo by {name} on Unsplash", "credit_copy": "출처 복사", "credit_copied": "출처 복사됨", "credit_failed": "복사하지 못했어요. 다시 시도해 주세요.", "credit_a11y": "사진 출처",
    "credit_copy_a11y": "사진 출처 두 줄 복사",
    "img_local_unsupported": "지원하지 않는 파일이에요. JPG·PNG·WebP 사진만 쓸 수 있어요.", "img_local_not_image": "사진 파일이 아니에요. 이름만 사진처럼 보이는 파일일 수 있어요.",
    "img_local_too_big": "파일이 너무 커요(20MB 까지). 더 작게 줄여서 다시 골라 주세요.", "img_local_long_side": "사진이 아주 커요(긴 변 12,000px 초과). 쓸 수는 있지만 화면이 느려질 수 있어요.",
    "img_local_unreadable": "사진을 읽지 못했어요. 다른 파일로 다시 시도해 주세요.", "img_local_missing": "파일을 찾지 못했어요.",
    # 설정 — 연결 관리(P4a, 읽기만 한다). 용도 이름은 서비스 표(`connections.PURPOSES`)에서 오고, 여기에는 설명 문장만 둔다
    "settings_title": "설정", "settings_sub": "키를 쓰는 서비스가 지금 어떤 상태인지 한눈에 볼 수 있어요.",
    "conn_title": "연결 관리", "conn_desc": "서비스를 용도별로 묶어 보여 드려요. 이 화면은 읽기만 해요.", "conn_refresh": "연결 상태 다시 읽기",
    "conn_keys_note": "화면에서 키를 넣는 기능은 아직 없어요.",
    "conn_group_data": "데이터 Provider", "conn_group_image": "이미지", "conn_group_ai": "AI 보조", "conn_group_publish": "발행·연결", "conn_group_info": "정보", "info_version": "버전",       # 새 기준 이름(UI-C1b — 운영자 확인 요청 004 의 답 7)
    "conn_group_open": "펼쳐져 있어요", "conn_group_closed": "접혀 있어요",
    "conn_chip_prep": "준비 중 {n}", "conn_chip_status": "{status} {n}",
    # 용도 카드의 '준비' 배지(호출 코드가 있나)와 '연결' 배지(서비스가 알려 주는 상태 다섯 가지) — 둘은 따로 보인다
    "ready_caption": "준비", "conn_caption": "연결",
    "ready_prep": "준비 중", "ready_ok": "사용할 수 있어요", "ready_nokey": "키 없음", "ready_legacy": "옛 항목",
    "status_not_connected": "연결 안 됨", "status_needs_check": "연결 확인 필요", "status_connected": "연결됨", "status_auth_error": "인증 정보 오류", "status_rate_limited": "요청 한도 도달",
    "state_active": "사용", "state_standby": "예비", "state_off": "꺼짐",
    "prep_note": "아직 연결 기능이 없어요. 키가 없어도 핵심 기능은 그대로예요.",                               # 카드 글 줄이기(UI-C1b, D-183): 뜻·안전 안내는 그대로, 군말만 뺐다
    "nokey_note": "키를 받지 않고 컴퓨터의 Git 로그인을 써요. 로그인 확인은 아직 못 해요.",
    "legacy_note": "호출하지 않아요. 새 키는 더할 수 없고 저장된 키는 지우지 않았어요.",
    "policy_single": "키는 1개만 써요 · 한도에 닿아도 다른 키로 넘어가지 않아요",
    "limit_naver_apihub": "한도 도달 시 저장된 데이터로 계속", "limit_desc_naver_apihub": "새 API 호출을 중지하고 Seed, 캘린더와 기존 발행 이력으로 후보를 생성합니다.",
    "policy_never": "자동으로 다른 키로 넘어가지 않아요. 한도에 닿으면 저장된 값이나 기본 값으로 계속해요.",
    "policy_failover": "예비: 한도·일시 오류일 때만 다음 키로 넘어가요(용도당 최대 {n}개)",
    "purpose_naver_apihub": "최근 관심도 변화를 가져와 주제를 고를 때 참고하는 서비스예요.",
    "purpose_naver_searchad": "월간 검색 수 같은 지표를 가져올 때 쓸 수 있는 서비스예요.",
    "purpose_naver_openapi": "예전 버전이 쓰던 네이버 검색·데이터 서비스예요.",
    "purpose_image_provider": "대표 이미지를 찾을 때 쓰는 서비스예요. 사진은 원본 주소로만 보여 줘요.",
    "purpose_ai_assist": "요약이나 설명을 돕는 선택 기능이에요. 기본은 꺼짐이에요.",
    "purpose_blogger": "Blogger 에 초안을 저장할 때 쓰는 서비스예요.",
    "purpose_github_repo": "글을 GitHub 저장소에 올릴 때 쓰는 연결이에요.",
    "choices_label": "키 사용 설정 종류", "entries_title": "저장된 키", "entry_state": "키 사용 설정: {state}", "entry_missing": "보관소에서 이 키를 찾지 못했어요.",
    "usage_title": "사용량", "usage_unit": "회", "usage_console": "서비스 콘솔 월 한도 {n}회", "usage_attempts_note": "실패한 호출도 세어요",
    "usage_unreadable": "확인할 수 없어요. 사용량 기록을 읽지 못했어요.", "usage_unreadable_closed": "확인할 수 없어요. 새 조회를 멈추고 저장된 정보로 계속해요.",
    "usage_sample": "예시", "entry_unnamed": "이름 없는 키",
    "conn_sample_tip": "화면에 보이는 키 이름·연결 상태·숫자는 모두 예시예요. 실제 값이 아니에요.",
    "conn_sample_dialog_body": "지금 보이는 키 이름, 연결 상태('연결됨' 포함), 사용량 숫자는 모두 화면을 확인하려고 넣어 둔 예시예요. 실제 연결 정보를 읽으면 이 표시가 사라져요.",
    "conn_loading": "연결 상태를 읽고 있어요…", "conn_loading_a11y": "연결 상태를 읽는 중",
    "conn_empty_title": "보여 드릴 연결 정보가 없어요.", "conn_empty_desc": "잠시 뒤에 다시 읽어 보세요.", "conn_empty_btn": "다시 읽기",
    "conn_error_title": "연결 설정을 읽지 못했어요.", "conn_error_desc": "잠시 뒤에 다시 시도해 주세요. 계속되면 아래 진단 정보를 함께 알려 주세요.",
    "conn_file_invalid": "연결 설정 파일을 읽지 못했어요. 파일은 고치거나 지우지 않았고 저장된 키는 그대로 있어요. 직전 사본이 있으면 되돌릴 수 있으니 아래 진단 정보를 함께 알려 주세요.",
    "conn_dir_unsafe": "이 폴더는 데이터 폴더로 쓸 수 없어요(프로그램이나 저장소 폴더 안). 다른 폴더를 정해서 다시 열어 주세요.",
    "conn_partial_keystore": "키 보관소를 열지 못해 키가 있는지는 확인하지 못했어요. 나머지 정보는 그대로 보여 드려요.",
    "conn_partial_usage": "사용량 기록을 읽지 못한 곳은 '확인할 수 없어요' 로 보여 드려요.",
    "conn_offline": "오프라인 상태예요. 이 PC 에 저장해 둔 정보만 보여 드려요.",
    # C-Type 공통 부품(UI-C0) — 아직 어떤 화면에도 연결하지 않은 부품의 글. 점수 구간 이름은 엔진의 구간(80/65/50)과 같은 말이다.
    "band_high": "우선 추천", "band_good": "일반 후보", "band_mid": "보류", "band_low": "제외",
    "cd_score_missing": "데이터 부족", "cd_score_a11y": "점수 {score}", "cd_score_none_a11y": "점수 데이터 부족",
    "cd_delta_up": "{n} 상승", "cd_delta_down": "{n} 하락", "cd_delta_flat": "변화 없음", "cd_delta_flat_visible": "― 변화 없음",
    "cd_bar_total": "최종 점수", "cd_bar_a11y": "점수 구성", "cd_bar_empty": "구성 정보 없음",
    "cd_usage_unknown": "확인할 수 없어요", "cd_usage_warn": "주의", "cd_usage_danger": "위험", "cd_usage_over": "한도 넘음",
    "cd_usage_a11y": "{text}, {percent}%", "cd_usage_a11y_state": "{text}, {percent}%, {state}",
    "cd_more_a11y": "더보기 메뉴 열기", "cd_actions_a11y": "행동 줄", "cd_tab_a11y": "{name} 탭, {total}개 중 {index}번째", "cd_tabs_a11y": "탭",
    "cd_gallery_title": "부품 모음", "cd_gallery_sub": "새 화면에서 쓸 공통 부품을 한곳에 늘어놓은 개발용 화면이에요. 모든 이름·숫자는 예시예요.",
    # 진단 정보 영역은 고정폭이라 영문·숫자만 둔다(기본 화면에는 나가지 않는다)
    "diag_purposes": "purposes", "diag_entries": "entries", "diag_keystore": "keystore", "diag_usage": "usage", "diag_ok": "ok", "diag_unavailable": "unavailable",
}

from .blog_text import BLOG_T  # noqa: E402

T.update(BLOG_T)                                                     # 블로그 관리 화면(P4b)의 문구는 새 파일(`blog_text.py`)에 따로 두고 합친다

FORBIDDEN = ("상위노출", "노출 확률", "검색 1위", "수익 보장", "수익보장", "보장")      # 화면 글에 쓰지 않는 표현(시험이 확인)


def fmt_int(value):
    return NO_DATA if value is None else f"{value:,}"


def fmt_demand(value):
    return NO_DATA if value is None else f"{value:,}{T['unit_demand']}"


def fmt_docs(value):
    return NO_DATA if value is None else f"{value:,}{T['unit_docs']}"


WEEKDAYS = "월화수목금토일"


def date_text(day=None):
    day = day or datetime.date.today()
    return f"{day.year}년 {day.month}월 {day.day}일 ({WEEKDAYS[day.weekday()]})"
