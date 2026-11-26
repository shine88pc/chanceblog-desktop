"""설정 화면의 '업데이트' 카드 문구(UPDATE 설계서 3-7) — `text.py` 의 `T` 에 합쳐진다(`T.update(UPDATE_T)`). 쉬운 한국어(해요체)이고 영문 상태 이름·오류 코드·명령·경로는 문장에 없다.

여기 있는 것은 **고정 문구**뿐이다. 새 버전 번호·안내 글·오류 문구는 서명을 확인한 매니페스트와 오류 표에서 오고(가리기·줄이기를 거쳐), 문장에 들어가는 자리표시자는 버전 번호·시각 글뿐이다.
'자동으로 확인해요' 같은 말은 없다 — 확인은 사용자가 단추를 누를 때만 한다.
"""
from __future__ import annotations

UPDATE_T = {
    "upd_title": "업데이트",
    "upd_version_line": "지금 버전: {version}",
    "upd_unknown_version": "지금 버전을 알 수 없어요",
    "upd_never_checked": "아직 확인하지 않았어요.",
    "upd_last_checked": "마지막 확인: {when}",
    # 꺼짐
    "upd_disabled": "이 버전에서는 업데이트 확인이 꺼져 있어요.",
    "upd_disabled_help": "지금 버전은 그대로 쓸 수 있어요. 새 버전이 나오면 릴리스 페이지에서 직접 받아 설치해 주세요.",
    # 확인
    "upd_check": "지금 확인", "upd_checking": "새 버전이 있는지 확인하는 중이에요.", "upd_cancel": "취소",
    "upd_up_to_date": "최신 버전이에요({version}).",
    "upd_available": "새 버전이 있어요: {version}",
    "upd_backup_first": "먼저 백업을 만들고 설치해요. 글과 설정은 그대로 남아요.",
    "upd_install": "내려받고 설치",
    "upd_install_off": "이 버전에서는 업데이트 설치가 꺼져 있어요. 릴리스 페이지에서 새 설치 파일을 받아 설치해 주세요.",
    "upd_open_release": "릴리스 페이지 열기",
    "upd_from_folder": "파일에서 업데이트…",
    # 진행
    "upd_working_download": "새 버전을 내려받는 중이에요.", "upd_working_verify": "받은 파일이 맞는지 확인하는 중이에요.", "upd_working_ready": "설치를 준비하는 중이에요.",
    "upd_working_backup": "먼저 백업을 만드는 중이에요.", "upd_working_apply": "설치를 시작해요. 프로그램이 곧 닫혀요.", "upd_working_rollback": "이전 버전으로 되돌리는 중이에요.",
    "upd_booting": "새 버전이 제대로 켜졌는지 확인하는 중이에요.", "upd_healthy": "업데이트를 마쳤어요({version}).",
    # 실패·안내
    "upd_failed": "업데이트를 마치지 못했어요.", "upd_retry": "다시 확인", "upd_code": "오류 이름: {code}",
    "upd_notice_not_applied": "업데이트가 적용되지 않았어요. 지금 버전 그대로예요.",
    "upd_portable": "휴대용은 새 압축 파일을 받아 풀어서 쓰세요. 데이터는 그대로 이어져요.",
    "upd_portable_new": "새 버전이 있어요: {version}",
    # 복구
    "upd_recover": "복구", "upd_later": "나중에", "upd_ok": "확인",
    # 접근성 이름
    "upd_a11y": "업데이트 카드, {state}",
}

__all__ = ["UPDATE_T"]
