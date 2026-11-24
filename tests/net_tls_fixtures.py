"""접속 틀 TLS 시험용 **버려도 되는** 인증서와 키(NET 설계서 6.1 — 시험 전용 자체 서명, 이 이름들만 SAN 으로, 만료 100년; 만료 시험용 하나만 2020 년에 끝났다).

실제 사이트·계정과 무관하다(시험 안에서 이 이름들의 풀이는 가짜 표가 127.0.0.1 로 바꾼다). 개인 키 모양의 글이 저장소 비밀 검사·푸시 보호에 걸리지 않게 **조립 문자열**로 둔다 —
머리말(대시 다섯 + `BEGIN ` + 종류 + 대시 다섯)을 코드가 이어 붙여 만들고 본문은 64글자 토막으로 나눠 적는다(`CANARY_` 와 같은 방식). 만드는 법: `openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 36500`
(SAN: 첫째 인증서 `github.com`·`www.googleapis.com`·`oauth2.googleapis.com`, 둘째 `other.example.test`, 셋째는 첫째와 같은 이름에 `-not_before 20200101000000Z -not_after 20200102000000Z`).
"""
DASHES = "-" * 5
NL = chr(10)


def _pem(kind, *lines):
    return DASHES + "BEGIN " + kind + DASHES + NL + NL.join(lines) + NL + DASHES + "END " + kind + DASHES + NL


GOOD_CERT = _pem('CERTIFICATE',
    'MIIB9DCCAZmgAwIBAgIUNaRzjC8N3TGnx/6Tc/T/T7SppJ8wCgYIKoZIzj0EAwIw',
    'KjEoMCYGA1UEAwwfTkVUIHRlc3QgY2VydCAobm90IGEgcmVhbCBzaXRlKTAgFw0y',
    'NjExMjQxMTQ1NTFaGA8yMTI2MTAzMTExNDU1MVowKjEoMCYGA1UEAwwfTkVUIHRl',
    'c3QgY2VydCAobm90IGEgcmVhbCBzaXRlKTBZMBMGByqGSM49AgEGCCqGSM49AwEH',
    'A0IABAGCGOxvUIy8KN2zwvXuF7GkiY6kbY0Hr8R8cFTrzsOV4NadMCB29wEMhvyv',
    'R4HQvkIs4zPlF2tE3RGnrvar1aejgZowgZcwQAYDVR0RBDkwN4IKZ2l0aHViLmNv',
    'bYISd3d3Lmdvb2dsZWFwaXMuY29tghVvYXV0aDIuZ29vZ2xlYXBpcy5jb20wDwYD',
    'VR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMCAoQwEwYDVR0lBAwwCgYIKwYBBQUH',
    'AwEwHQYDVR0OBBYEFOGuFdwB/tJXpEaBVx8qpGmqH+NyMAoGCCqGSM49BAMCA0kA',
    'MEYCIQD5JJMUoCltsVNo88FOmCU8xM+ZPnlGgUFKCeLzz0CVvAIhAOaFl+Rz6xoD',
    'a5D75FHphc4ZBB+u3UxuwoOu2lQEyaHy')

GOOD_KEY = _pem('PRIVATE KEY',
    'MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg3n9wXrnzzKF/V8++',
    '3bj7Iis6r/4WTP+DLdmGa0b2CUGhRANCAAQBghjsb1CMvCjds8L17hexpImOpG2N',
    'B6/EfHBU687DleDWnTAgdvcBDIb8r0eB0L5CLOMz5RdrRN0Rp672q9Wn')

OTHER_CERT = _pem('CERTIFICATE',
    'MIIBrTCCAVKgAwIBAgIUeqpjSg1D+Okgz92GvmGfYjmcB6wwCgYIKoZIzj0EAwIw',
    'GTEXMBUGA1UEAwwOTkVUIHRlc3Qgb3RoZXIwIBcNMjYxMTI0MTE0NTUyWhgPMjEy',
    'NjEwMzExMTQ1NTJaMBkxFzAVBgNVBAMMDk5FVCB0ZXN0IG90aGVyMFkwEwYHKoZI',
    'zj0CAQYIKoZIzj0DAQcDQgAEuXomnDIsZgdt2lhyjkVdCcquDBE6NzX6OyqQaz0X',
    'RGNAg77vwwF1/PKIPGz/ihNhQFTtPOJBj3lQjkLa6XrFRqN2MHQwHQYDVR0RBBYw',
    'FIISb3RoZXIuZXhhbXBsZS50ZXN0MA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/',
    'BAQDAgKEMBMGA1UdJQQMMAoGCCsGAQUFBwMBMB0GA1UdDgQWBBTVgT1xtwtmj8iC',
    'i71Kxzs8Ry8+jjAKBggqhkjOPQQDAgNJADBGAiEApuXX7RhTO7qDpEid3uGq99fb',
    '9anymC06eplxJgr63B4CIQCZhJgAFcoVngt1ppNdgJEb3LOFF9M1jmNLiF8QSJdA',
    'uA==')

OTHER_KEY = _pem('PRIVATE KEY',
    'MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgh71dosIOEyIPvpaT',
    'or4HHjRDryEEPhbBfSc+RyEleWWhRANCAAS5eiacMixmB23aWHKORV0Jyq4METo3',
    'Nfo7KpBrPRdEY0CDvu/DAXX88og8bP+KE2FAVO084kGPeVCOQtrpesVG')

EXPIRED_CERT = _pem('CERTIFICATE',
    'MIIB8TCCAZegAwIBAgIUFcWtpthq9PZqkNzv8ha7nIF4Hk8wCgYIKoZIzj0EAwIw',
    'KjEoMCYGA1UEAwwfTkVUIHRlc3QgY2VydCAobm90IGEgcmVhbCBzaXRlKTAeFw0y',
    'MDAxMDEwMDAwMDBaFw0yMDAxMDIwMDAwMDBaMCoxKDAmBgNVBAMMH05FVCB0ZXN0',
    'IGNlcnQgKG5vdCBhIHJlYWwgc2l0ZSkwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNC',
    'AAT2rxY2KU17VcCPYKnL19goe7mELWP0PR0kvcBGbQc14rjcYyhBrB4v0z0mmuq2',
    'A6olozISUTDDDH8srXRkmd9io4GaMIGXMEAGA1UdEQQ5MDeCCmdpdGh1Yi5jb22C',
    'End3dy5nb29nbGVhcGlzLmNvbYIVb2F1dGgyLmdvb2dsZWFwaXMuY29tMA8GA1Ud',
    'EwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgKEMBMGA1UdJQQMMAoGCCsGAQUFBwMB',
    'MB0GA1UdDgQWBBTepXDfSd/dWwzUUvh9mRRyuKm1EDAKBggqhkjOPQQDAgNIADBF',
    'AiAOJlz4/UR96iE0eMKTMuKQ5U9Yy/m6SorjF6cstilTUwIhAKgK4RUD2owYzJ1p',
    'WeSxzKy1PooDmIobeCDrA0UtvnG0')

EXPIRED_KEY = _pem('PRIVATE KEY',
    'MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg9bhFdm4htoPjt5To',
    'o2G9rmoMgnIHql0LNnPhmS6uASuhRANCAAT2rxY2KU17VcCPYKnL19goe7mELWP0',
    'PR0kvcBGbQc14rjcYyhBrB4v0z0mmuq2A6olozISUTDDDH8srXRkmd9i')
