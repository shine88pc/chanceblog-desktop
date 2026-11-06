"""화면 문구(한국어)와 숫자·날짜 서식. 문구는 운영자 요구서·명세·목업의 문장을 옮기지 않고 새로 썼다(메뉴·단추·지표 이름처럼 짧은 이름은 그대로).
결과를 약속하는 표현(상위노출 보장·노출 확률·검색 1위 가능성·수익 보장)은 쓰지 않는다 — `FORBIDDEN` 을 시험이 모든 문구에 대어 본다.
영문 오류 코드·스택 트레이스는 이 표에 없다 — 진단 정보 영역(`diagnostic_text`)에만 나간다."""
from __future__ import annotations

import datetime

NO_DATA = "데이터 없음"
SAMPLE_TAG = "예시 데이터"

T = {
    "app_name": "ChanceBlog", "settings_btn": "설정", "brand_line": "고르고 · 만들고 · 복사하기", "brand_version": "ChanceBlog Desktop",
    "window_title": "ChanceBlog Desktop",
    "nav_home": "홈", "nav_topics": "주제 후보", "nav_draft": "초안 작성", "nav_history": "발행 기록", "nav_blogs": "블로그 관리", "nav_settings": "설정",
    "nav_menu": "주 메뉴", "body_area": "본문", "nav_a11y": "{name} 메뉴로 이동",
    # 예시 데이터 표시와 설명 대화상자
    "sample_tag": SAMPLE_TAG, "sample_tip": "화면에 보이는 주제와 숫자는 예시예요. 실제 수치가 아닙니다.",
    "sample_dialog_title": "예시 데이터예요",
    "sample_dialog_body": "지금 보이는 주제와 숫자는 화면을 확인하려고 넣어 둔 예시예요. 내 블로그의 실제 후보를 불러오면 이 표시가 사라져요.",
    "ok": "확인", "cancel": "취소", "close": "닫기",
    # 홈
    "home_title": "오늘은 어떤 주제로 써 볼까요?", "home_sub": "블로그에 어울리는 주제를 고르면 바로 초안까지 만들어 드려요.",
    "sum_topics": "추천 주제", "sum_done": "작성 완료", "sum_pub": "발행 완료", "sum_ideas": "저장된 아이디어",
    "sum_topics_sub": "새 후보 {n}개 포함", "sum_week_sub": "이번 주 +{n}", "sum_ideas_sub": "보류한 주제 기준", "sum_unavailable": "아직 집계하지 않아요", "sum_none": "–",
    "rec_title": "맞춤 주제 추천", "rec_desc": "내 블로그에 어울릴 만한 주제를 모아 두었어요.", "rec_all": "전체 보기",
    "chip_all": "전체", "chip_a": "블로그 A", "chip_b": "블로그 B", "chip_hot": "트렌드 급상승", "chip_new": "신규 키워드",
    "make_primary": "이 주제로 초안 만들기", "make_small": "초안 만들기", "make_a11y": "{title} 초안 만들기", "detail_a11y": "{title} 자세히 보기",
    "demand": "월 검색량", "docs": "블로그 문서 수", "unit_demand": "회", "unit_docs": "건",
    "tip_demand": "한 달 동안 이 키워드가 검색된 횟수를 어림잡은 값이에요.", "tip_docs": "이 키워드와 관련된 블로그 문서가 얼마나 쌓여 있는지 보여 줘요.",
    "trend_up": "상승", "trend_flat": "보통", "trend_down": "하락",
    "row_a11y": "{title}, {blog}, 작성 우선도 {priority}", "priority": "작성 우선도",
    "rail_blogs": "내 블로그 현황", "rail_blogs_sub": "관리 중인 블로그 {n}개", "rail_total": "총 글", "rail_month": "이번 달", "rail_candidates": "후보", "rail_unit": "개",
    "rail_quick": "빠른 작업",
    "q_new": "새 초안 만들기", "q_new_d": "고른 주제로 바로 시작", "q_saved": "저장된 주제 보기", "q_saved_d": "보류한 주제 다시 보기",
    "q_hist": "발행 기록 보기", "q_hist_d": "발행한 글 확인하기", "q_set": "블로그 설정", "q_set_d": "블로그 기본값 바꾸기",
    "tip_title": "활용 팁", "tip_text": "마음에 드는 주제는 '보류'로 두었다가 나중에 다시 꺼내 볼 수 있어요.", "tip_close": "활용 팁 닫기",
    "list_count": "{n}개 후보", "refresh": "다시 불러오기", "last_fetch": "마지막 조회 {when}",
    # 상세 서랍
    "drawer_title": "주제 상세", "drawer_close": "상세 닫기", "d_demand": "월간 검색량", "d_split": "PC·모바일 검색 비중", "d_docs": "관련 블로그 검색 결과 수", "d_trend": "최근 트렌드",
    "d_season": "계절성", "d_written": "기존 작성 여부", "d_sub": "보조 키워드", "d_date": "데이터 조회일", "d_reason": "추천 이유",
    "written_yes": "이미 쓴 글이 있어요", "written_no": "아직 쓴 글이 없어요", "split_value": "PC {pc}% · 모바일 {mobile}%",
    "draft_a": "블로그 A 초안", "draft_b": "블로그 B 초안", "hold": "보류", "more": "더보기",
    # 상태 화면
    "loading": "후보를 불러오고 있어요…", "loading_a11y": "후보를 불러오는 중",
    "empty_title": "아직 추천 주제가 없어요.", "empty_desc": "블로그 정보를 확인하고 주제 분석을 시작해 보세요.", "empty_btn": "주제 분석 시작",
    "error_title": "주제 후보를 불러오지 못했어요.", "error_desc": "잠시 뒤에 다시 시도해 주세요. 계속되면 아래 진단 정보를 함께 알려 주세요.", "retry": "다시 시도",
    "partial": "검색 추세는 불러오지 못했지만 나머지 정보는 그대로 쓸 수 있어요.", "offline": "오프라인 상태예요. 저장해 둔 초안은 계속 고칠 수 있어요.",
    "diag_show": "진단 정보 보기", "diag_hide": "진단 정보 숨기기", "diag_title": "진단 정보", "diag_note": "도움을 받을 때 함께 알려 주세요. 키와 입력한 글은 담기지 않아요.",
    "diag_code": "code", "diag_when": "time",                                  # 진단 정보는 고정폭 글꼴 영역이라 영문·숫자만 둔다(한글은 글꼴이 바뀌어 모양이 달라진다)
    "soon_title": "이 화면은 아직 만들고 있어요.", "soon_desc": "다음 단계에서 이어서 만들어요. 지금은 홈에서 주제 추천을 볼 수 있어요.", "soon_btn": "홈으로",
    # 안내(토스트)
    "soon_toast": "'{name}' 은(는) 다음 단계에서 열려요.", "load_cancelled": "불러오기를 취소했어요. 보이던 내용은 그대로예요.", "load_busy": "이미 불러오는 중이에요.",
    "load_failed_toast": "불러오지 못했어요. 다시 시도해 주세요.", "job_failed": "작업을 마치지 못했어요. 입력한 내용은 그대로 남아 있어요.", "job_cancelled": "작업을 취소했어요. 입력한 내용은 그대로예요.",
    "data_dir_missing": "지정한 데이터 폴더를 찾지 못했어요. 폴더 이름을 확인한 뒤 다시 열어 주세요.",
    "data_unreadable": "데이터 폴더를 읽지 못했어요. 다른 프로그램이 쓰고 있지 않은지 확인한 뒤 다시 시도해 주세요.",
    "unexpected_line": "화면에서 처리하지 못한 오류가 있었어요",                           # 표준 오류에 한 줄로만 남는다(예외 이름 + 비밀·경로를 가린 짧은 글)
    "cancel_job": "작업 취소", "load_cancel": "불러오기 취소",
    # 이미지 자리 표시·출처(Unsplash)·내 사진
    "thumb_label": "{category} 주제의 이미지 자리 표시", "thumb_label_plain": "이미지 자리 표시", "img_state_none": "대표 이미지가 아직 없어요. 주제 아이콘으로 보여 드려요.",
    "credit_line": "Photo by {name} on Unsplash", "credit_copy": "출처 복사", "credit_copied": "출처 복사됨", "credit_failed": "복사하지 못했어요. 다시 시도해 주세요.", "credit_a11y": "사진 출처",
    "credit_copy_a11y": "사진 출처 두 줄 복사",
    "img_local_unsupported": "지원하지 않는 파일이에요. JPG·PNG·WebP 사진만 쓸 수 있어요.", "img_local_not_image": "사진 파일이 아니에요. 이름만 사진처럼 보이는 파일일 수 있어요.",
    "img_local_too_big": "파일이 너무 커요(20MB 까지). 더 작게 줄여서 다시 골라 주세요.", "img_local_long_side": "사진이 아주 커요(긴 변 12,000px 초과). 쓸 수는 있지만 화면이 느려질 수 있어요.",
    "img_local_unreadable": "사진을 읽지 못했어요. 다른 파일로 다시 시도해 주세요.", "img_local_missing": "파일을 찾지 못했어요.",
    # 설정 — 연결 관리(P4a, 읽기만 한다). 용도 이름은 서비스 표(`connections.PURPOSES`)에서 오고, 여기에는 설명 문장만 둔다
    "settings_title": "설정", "settings_sub": "키를 쓰는 서비스가 지금 어떤 상태인지 한눈에 볼 수 있어요.",
    "conn_title": "연결 관리", "conn_desc": "서비스를 용도별로 묶어 보여 드려요. 이 화면은 읽기만 해요.", "conn_refresh": "연결 상태 다시 읽기",
    "conn_keys_note": "화면에서 키를 넣는 기능은 아직 없어요.",
    "conn_group_data": "데이터", "conn_group_image": "이미지", "conn_group_ai": "AI", "conn_group_publish": "발행·연결",
    "conn_group_open": "펼쳐져 있어요", "conn_group_closed": "접혀 있어요",
    "conn_chip_prep": "준비 중 {n}", "conn_chip_status": "{status} {n}",
    # 용도 카드의 '준비' 배지(호출 코드가 있나)와 '연결' 배지(서비스가 알려 주는 상태 다섯 가지) — 둘은 따로 보인다
    "ready_caption": "준비", "conn_caption": "연결",
    "ready_prep": "준비 중", "ready_ok": "사용할 수 있어요", "ready_nokey": "키 없음", "ready_legacy": "옛 항목",
    "status_not_connected": "연결 안 됨", "status_needs_check": "연결 확인 필요", "status_connected": "연결됨", "status_auth_error": "인증 정보 오류", "status_rate_limited": "요청 한도 도달",
    "state_active": "사용", "state_standby": "예비", "state_off": "꺼짐",
    "prep_note": "아직 실제로 연결하는 기능이 없어요. 키가 없어도 핵심 기능은 그대로예요.",
    "nokey_note": "키를 받지 않아요. 컴퓨터의 Git 로그인을 써요. 로그인 확인은 아직 못 해요.",
    "legacy_note": "지금은 호출하지 않아요. 새 키는 더할 수 없고 저장된 키는 지우지 않았어요.",
    "policy_single": "키는 1개만 써요 · 한도에 닿아도 다른 키로 넘어가지 않아요",
    "limit_naver_apihub": "한도 도달 시 저장된 데이터로 계속", "limit_desc_naver_apihub": "새 API 호출을 중지하고 Seed, 캘린더와 기존 발행 이력으로 후보를 생성합니다.",
    "policy_never": "자동으로 다른 키로 넘어가지 않아요. 한도에 닿으면 저장해 둔 값이나 기본 값으로 계속해요.",
    "policy_failover": "예비: 한도·일시 오류일 때만 다음 키로 넘어가요(용도당 최대 {n}개)",
    "purpose_naver_apihub": "키워드의 최근 관심도 변화를 가져와 주제 후보를 고를 때 참고하는 서비스예요.",
    "purpose_naver_searchad": "키워드의 월간 검색 수 같은 지표를 가져올 때 쓸 수 있는 서비스예요.",
    "purpose_naver_openapi": "예전 버전이 쓰던 네이버 검색·데이터 서비스예요.",
    "purpose_image_provider": "글에 넣을 대표 이미지를 찾을 때 쓰는 서비스예요. 사진은 원본 주소로만 보여 줘요.",
    "purpose_ai_assist": "요약이나 설명을 돕는 선택 기능이에요. 기본은 꺼짐이에요.",
    "purpose_blogger": "Blogger 에 초안을 저장할 때 쓰는 서비스예요.",
    "purpose_github_repo": "글을 GitHub 저장소에 올릴 때 쓰는 연결이에요.",
    "choices_label": "키 사용 설정 종류", "entries_title": "저장된 키", "entry_state": "키 사용 설정: {state}", "entry_missing": "보관소에서 이 키를 찾지 못했어요.",
    "usage_title": "사용량", "usage_count": "{span} {used} / {limit}회", "usage_console": "서비스 콘솔 월 한도 {n}회", "usage_attempts_note": "실패한 호출도 세어요",
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
    "advanced_title": "고급",
    # 진단 정보 영역은 고정폭이라 영문·숫자만 둔다(기본 화면에는 나가지 않는다)
    "diag_purposes": "purposes", "diag_entries": "entries", "diag_keystore": "keystore", "diag_usage": "usage", "diag_ok": "ok", "diag_unavailable": "unavailable",
}

FORBIDDEN = ("상위노출", "노출 확률", "검색 1위", "수익 보장", "수익보장", "보장")      # 화면 글에 쓰지 않는 표현(시험이 확인)


def fmt_int(value):
    return NO_DATA if value is None else f"{value:,}"


def fmt_demand(value):
    return NO_DATA if value is None else f"{value:,}{T['unit_demand']}"


def fmt_docs(value):
    return NO_DATA if value is None else f"{value:,}{T['unit_docs']}"


_WEEK = "월화수목금토일"


def date_text(day=None):
    day = day or datetime.date.today()
    return f"{day.year}년 {day.month}월 {day.day}일 ({_WEEK[day.weekday()]})"
