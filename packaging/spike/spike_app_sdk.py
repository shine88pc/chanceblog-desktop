# -*- coding: utf-8 -*-
"""spike_app_sdk.py - 설치 도구 시험(spike) 갈래 A 의 작은 앱(결정 D-704): spike_app.py 와 같은 앱인데 Velopack 파이썬 SDK 가 훅을 받는다.

맨 앞에서 velopack.App().set_auto_apply_on_startup(False).run() 를 부른다(콜백 등록 0) — 훅 인자(--veloapp-install 버전 등)를 받으면 SDK 가 알아서 종료 코드 0 으로 끝내고,
'시작 때 내려받아 둔 높은 판을 스스로 적용하고 재시작' 하는 기본값(켜짐)은 끈다(설계서 F6 — 업데이트는 수동 확인이 기본이다). 나머지 동작은 spike_app.main 이다.
이 앱은 휠이 설치된 별도 가상환경에서만 묶는다(실제 묶음을 만드는 환경에는 SDK 가 섞여 들어가지 않는다).
"""
import sys

import velopack

import spike_app


def main():
    velopack.App().set_auto_apply_on_startup(False).run()
    return spike_app.main(sdk=velopack)


if __name__ == "__main__":
    sys.exit(main())
