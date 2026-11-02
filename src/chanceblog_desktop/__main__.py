"""`python -m chanceblog_desktop <명령>` — 명령줄 진입점(사용법은 `--help`, 설명은 README.md 의 '명령줄로 써 보기')."""
import sys

from .service.cli import main

if __name__ == "__main__":
    sys.exit(main())
