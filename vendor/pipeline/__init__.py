"""멀티 블로그 풀오토 파이프라인 공용 코어.

구성
- registry   : 블로그 설정의 단일 원천(pipeline/blogs.json) 로드·검증
- gates      : 생성물 검증(파싱·HTML 정화·정책·중복) — 실패하면 게시하지 않는다(fail closed)
- llm        : Gemini 호출(모델 폴백·재시도·시크릿 마스킹·요청별 호출 기록)
- topics     : 주제 선정(시드 + 쿨다운 + 중복 방지)
- state      : 이력 파일 읽기/쓰기(원자적 쓰기)
- health     : 발행 중단·반복 실패 감시 규칙(순수 함수)
- publishers : 플랫폼 어댑터(blogger 등). 새 플랫폼은 여기에 어댑터를 추가한다
- run        : 블로그 한 곳을 한 번 실행하는 진입점 (python -m pipeline.run --blog KEY)
- plan       : 레지스트리에서 GitHub Actions 매트릭스를 만든다
- drafts     : Chance 승인 흐름(publish_flow: pr)의 이름·판정·PR 본문 소독 규칙과 GitHub REST 클라이언트
- draft_flow : 승인 흐름의 실행부(초안 브랜치 올리기·PR 열기·정리, python -m pipeline.draft_flow)

설명: docs/ARCHITECTURE.md, docs/ENGINEERING_GUIDE.md
"""
