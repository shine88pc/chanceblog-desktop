"""서비스 층 — 이미 만든 모듈(content·render·check·publish·errors·security)을 앱의 흐름으로 잇는다(화면 없음, 시험 가능). 명령줄은 `cli.py`(`python -m chanceblog_desktop`).

흐름: 글 만들기·불러오기(`projects`) → 미리 보기(`previews`) → 검토 요청·승인·승인 취소(`review`) → GitHub Pages 올리기(`pages_flow`: 미리 보기(dry run) → `--yes` 로 commit·push → 공개 확인)
또는 네이버 복사 패키지(`review.issue_naver_package`) → 점검(`doctor`). 경로·저장소·시계·git·배포 확인은 `context.Context` 로 바꿔 끼운다.
docs/ARCHITECTURE.md §5 `service/` 행에 구현 범위와 한계를 적는다.
"""
from .context import Context, Settings, Workspace, make_context

__all__ = ["Context", "Settings", "Workspace", "make_context"]
