"""파일·폴더 이름 **자신**이 링크인가 — 앱이 폴더를 훑거나 지우거나 읽기 전에 거는 한 가지 기준(AS-S2 권고-2·권고-6, 결정 D-690·D-692).

전체 백업(`service/backup_flow.py::_is_link`, AS-S1 권고-1·D-608)이 먼저 만든 기준이고 그 함수는 그대로 두었다 — 소스 모양 시험(`tests/test_service_backup_links.py`)이 그 모양을 못박고 있다.
이 모듈은 같은 기준을 서비스를 가져오지 못하는 낮은 층(`topicdb/`·`vendor_pin.py`)에 주려는 것이고, 두 함수가 같은 표에서 같은 답을 내는지는 시험(`tests/test_topicdb_backup_links.py`)이 견준다.

기준: 링크를 따라가지 않고 그 이름을 `os.lstat` 로 본다. 심볼릭 링크이거나 윈도 재해석 지점(junction·마운트 지점 …)이면 참이다.
윈도에서 junction 의 `is_symlink()` 는 거짓이고 `is_dir()` 은 링크를 따라가서 그 둘만으로는 폴더 자리에 놓인 junction 을 못 거른다(목록·정리가 목적지의 앱 이름 파일을 지웠다).
재해석 지점인데 종류(`st_reparse_tag`)가 링크가 아니면(OneDrive 같은 클라우드 파일 자리표시 …) 링크로 보지 않는다 — 그런 파일은 읽으면 내려받아질 뿐 다른 곳으로 돌려지지 않는다.
없는 경로는 거짓, 읽을 수 없으면 참(알 수 없으면 따라가지 않는다). `st_file_attributes` 는 윈도에만 있고 다른 운영체제에서는 0 으로 읽는다(심볼릭 링크는 `S_ISLNK`).
윈도에만 있는 `stat.IO_REPARSE_TAG_*` 이름은 리눅스에서 `AttributeError` 라 종류 값을 숫자로 둔다. 표준 라이브러리만 쓰고 읽기만 한다.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

REPARSE_POINT = 0x400                                            # 윈도 파일 속성 FILE_ATTRIBUTE_REPARSE_POINT — 심볼릭 링크·junction(정션)·마운트 지점이 가진다
LINK_TAGS = frozenset({0xA000000C, 0xA0000003})                  # 이름을 다른 곳으로 돌리는 재해석 종류 — 심볼릭 링크(IO_REPARSE_TAG_SYMLINK)와 junction·마운트 지점(IO_REPARSE_TAG_MOUNT_POINT)


def is_link(path):
    """그 경로 **자신**이 링크인가 — 위 머리말의 기준."""
    path = Path(path)
    try:
        if path.is_symlink():                                    # 심볼릭 링크(윈도 junction 은 여기서 거짓이라 아래 재해석 속성이 따로 본다)
            return True
        info = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return True
    if stat.S_ISLNK(info.st_mode):
        return True
    if not getattr(info, "st_file_attributes", 0) & REPARSE_POINT:
        return False
    tag = getattr(info, "st_reparse_tag", None)
    return tag is None or tag in LINK_TAGS


__all__ = ["LINK_TAGS", "REPARSE_POINT", "is_link"]
