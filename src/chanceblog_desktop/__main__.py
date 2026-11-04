"""`python -m chanceblog_desktop <명령>` — 명령줄 진입점(사용법은 `--help`, 설명은 README.md 의 '명령줄로 써 보기'). `gui` 는 화면을 연다(`ui/launcher.py`, PySide6 가 있을 때만)."""
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "gui":
        from .ui.launcher import main as gui_main
        sys.exit(gui_main(sys.argv[2:]))
    from .service.cli import main
    sys.exit(main())
