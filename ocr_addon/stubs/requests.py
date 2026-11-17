# -*- coding: utf-8 -*-
"""stubs/requests.py - 아무것도 하지 않는 가짜 requests(동결 묶음에서 진짜 requests·urllib3·certifi·idna·charset_normalizer 를 빼기 위한 한 모듈).
rapidocr 3.10.0 은 utils/load_image.py·utils/download_file.py 에서 모듈 위에서 `import requests` 만 하고, 실제로 부르는 곳은 'URL 주소를 사진으로 준 경우'와 '모델 내려받기' 뿐이다.
작업자는 모델을 로컬 파일로만 쓰고 사진은 메모리 배열로만 받으므로 그 길은 열리지 않는다. 혹시 불리면 조용히 나가지 않고 바로 예외를 낸다."""
__version__ = "0+offline-stub"


class RequestException(Exception):
    pass


class Response(object):
    pass


def _disabled(*args, **kwargs):
    raise RuntimeError("이 묶음에서는 네트워크를 쓰지 않는다(requests 는 껍데기)")


get = post = put = delete = head = options = patch = request = _disabled


class Session(object):
    def __init__(self, *args, **kwargs):
        raise RuntimeError("이 묶음에서는 네트워크를 쓰지 않는다(requests 는 껍데기)")
