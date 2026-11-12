"""전체 백업이 담지 않는 것과 그 이유, 그리고 '키·토큰·쿠키·세션은 이 백업에 없어요' 라는 고정 문장 — 백업의 목록 파일(`MANIFEST.json`)과 화면이 같은 글을 쓴다(BACKUPUI, D-382).

운영자 결정(2026-11-11): 백업에는 Credential(키·토큰·쿠키·세션)이 하나도 들어 있지 않고, 목록에 그 사실을 쉬운 문장으로 적는다. 그래서 이 글은 한 곳에 두고 서비스(`service/backup_flow.py`)가 목록에 그대로 적는다.
이 모듈은 글만 있고 파일·네트워크·시계·무작위를 쓰지 않는다. 서비스 층의 시험은 서비스 소스의 글에 영어 비밀 낱말이 없을 것을 요구하므로(서비스는 비밀을 다루지 않는다) 그 낱말이 든 고정 문장은 서비스가 아니라 여기에 둔다.
"""
from types import MappingProxyType

CREDENTIAL_NOTE = "자격 증명(키·토큰·쿠키·세션)은 이 백업에 들어 있지 않아요 — 복원한 뒤 키는 다시 등록하세요"       # 백업 목록(MANIFEST.json)의 `credential_excluded_note` — 주제 백업(PCSEC1 M4, `topicdb/backup.py`)과 **한 상수**다(D-467)
RESTORE_NOTE = "키는 백업에 없어요 — 복원한 뒤 설정에서 다시 등록해 주세요"
SHORT_NOTE = "Credential 제외됨"

# 백업이 담지 않는 것 — (이름, 이유). 이름은 파일·폴더 이름이거나 종류 이름이다. 목록 파일에 이 순서 그대로 적힌다.
EXCLUDED = (
    ("키·토큰·쿠키·세션·자격 증명", "이 앱은 키를 파일에 적지 않고 Windows 자격 증명 관리자에만 둬요. 백업은 그곳을 읽지 않아요"),
    ("connections.json", "키 항목의 이름·사용 상태 같은 연결 설정이에요. 키 원문이 없는 채 옮기면 키가 있는 것처럼 보이는 거짓 상태가 되어 담지 않아요"),
    ("quota_state.json", "호출 한도 사용 기록이에요. 이 PC 의 그날그날 사용량이라 나중에 되돌리면 오히려 틀려져서 담지 않아요"),
    ("publish/", "올리는 중인 글의 진행 기록이에요. 되돌리면 이미 끝난 일을 다시 하려 해서 위험하니 담지 않아요"),
    ("locks/", "실행 중에만 있는 잠금 파일이라 담지 않아요"),
    ("backups/", "백업 자신이에요. 백업 안에 백업을 담지 않아요"),
    ("로그·디버그 기록", "이 앱은 로그 파일을 만들지 않고, 있어도 담지 않아요"),
    ("임시·복구용 사본", "앱이 일하다 만드는 임시 파일과 복구용 사본(.bak·.bad-·.tmp)은 담지 않아요"),
    ("외부에서 가져온 원본 자료", "다른 곳에서 받아 온 글·자료의 원본은 앱 데이터에 두지 않아서 담지 않아요"),
)
EXCLUDED_NAMES = tuple(name for name, _ in EXCLUDED)
EXCLUDED_REASON = MappingProxyType(dict(EXCLUDED))

__all__ = ("CREDENTIAL_NOTE", "EXCLUDED", "EXCLUDED_NAMES", "EXCLUDED_REASON", "RESTORE_NOTE", "SHORT_NOTE")
