"""건강 판정 미탐 보강 시험(WP-B5, D-290–D-296) — 5채널 독립 검증이 찾은 '건강 C 의도 문장 52개 중 초안으로 나오던 10개'를 모두 중지로 만들고, 일상 문장은 한 글자도 바꾸지 않았는지 못박는다.
낱말 표·표현 목록은 모두 **초기값 — 운영자 확인 전**이다(이 시험이 값을 못박아 고칠 때 의식적으로 함께 고치게 한다). 시험 글은 모두 지어낸 일반 문장이다.

지키는 것:
  Y1) 미탐 10개가 각각 중지(C)이고 후보의 제목·핵심 키워드·보조 키워드 어느 자리에서도 같다 — 원인이 있는 곳(의문 꼬리 걸침·증상 낱말·즉각 표현·복용 중단)에서 고쳐졌다
  Y2) 범위 밖 C 의도 52개 + 운영자 C 예시 9개 전부 중지 Y3) A·B·일반 대조 40개는 옛 단계 그대로(감기 낱말을 더해 `감기 기운이 …` 하나만 일반 → 표시만) 이고 중지가 없다, 일상 문장 61개는 새 낱말이 든 것 말고는 그대로다
  Y4) 증상 × 즉각 낱말 × 효과 동사 격자와 새 증상 낱말 전부가 중지로 읽힌다(활용형·즉각 표현 포함) Y5) 새 증상 13·질환 5 낱말 하나하나 — 단독은 표시만·근거 확인 필요, 주장은 중지, 일상어 속 우연한 일치는 마스크 8개가 막는다
  Y6) 의문 꼬리가 띄어쓴 두 낱말에 걸쳐 우연히 맞는 것은 의문이 아니다(`없애는 지압법`·`가이드`·`지름길` …) — 한 낱말 안의 진짜 의문(`줄이는지`·`줄일까`)은 그대로 단정을 끈다
  Y7) 즉각 표현 `단번에`·`한 번에`·`한꺼번에`·`하루 만에` 는 범위 낱말처럼 읽되 옛 중지 바닥에는 없다 — 평범한 글(`당뇨 예방 식단 한 번에 정리하기`)은 중지가 아니다
  Y8) 처방약 복용 중단 단정 — `당뇨약 안 먹고 낫는 방법`·`고혈압약 끊어도 되는 방법` 은 중지, 질문 꼴·`없이`·`끊는 방법`·`끊어도 되는 시기` 는 지금대로다
  Y9) 알림·문서·머리말 Y10) 효과 낱말 표는 그대로다(`해결` 을 넣으면 `영양제 오류 해결` 같은 엔진 후보가 근거 확인 필요로 올라간다)
수정 라운드(독립 검증 `ver_wpb5` 의 지적 — D-298–D-306):
  Z1) 늘 단정 낱말 곁 결과 서술어(`요통 100% 해결`) Z2) 두 글자 증상은 낱말 처음에서만·허용 합성어·마스크·새 증상 일곱 Z3) 서술어 읽기 보강(효과 동사 어간·글 끝 결과 명사·`멈추` 대상 구분·건강 낱말 조각 건너뛰기)과 모르는 서술어 규칙 삭제(쇼핑 문장)
  Z4) 즉각·기간 표현 보강 Z5) 붙여 쓴 끝말 의문 꼬리 Z6) 처방약 복용 중단 좁히기·허용 말투 Z7) 병적 입력 속도 Z8) 알려진 한계 못박기 Z9) 변이 시험 틈(V13)
3차 수정 라운드(델타 재검증 `ver_wpb5b` 의 지적 — D-307–D-311):
  Z10) 한 낱말 마스크 `한눈에`·`첫눈에` 를 지우고 `눈 건강` 은 낱말 처음에서만 읽는다 — 마스크가 글을 갈라 기준이 중지로 읽던 글을 낮췄다(마스크 표 전체를 돌리는 속성 시험)
  Z11) 낱말 처음 읽기가 낱말 경계를 가로지르지 않는다(`설 사진`·`감 기르는 법`)·낱말 경계 시험이 운영 표를 본다 Z12) 증상 앞 수식어 표(허용 합성어 25개 목록을 갈음)·`손목감기` Z13) 약 이름 + 복용 중단 + 결과어는 중지
  Z14) `풀어보는` 의 대상이 증상이면 효과(퀴즈·제품·질환은 행동 그대로)
네트워크·파일·실제 시계·난수 없이 돈다(속도 시험만 `time.perf_counter` 로 잰다).
"""
import itertools
import random
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_topics_health_context as hc  # noqa: E402
import topics_support as ts  # noqa: E402

from chanceblog_desktop.topics import concepts as cn  # noqa: E402
from chanceblog_desktop.topics import notice as nt  # noqa: E402
from chanceblog_desktop.topics import safety as sf  # noqa: E402

GENERAL, MARK, EVIDENCE, STOP = "general", "mark", "evidence", "stop"
SHORT = {"G": GENERAL, "A": MARK, "B": EVIDENCE, "C": STOP}

# 독립 검증(`ver_p4e`)이 건강 판정기를 '초안 엔진' 입구에서 돌려 본 문장 — 운영자 C 예시 9개·범위 밖 C 의도 52개(운영자 원칙 — 증상·질환·영양제·처방약 + 즉각·단정 + 효과 — 에 비춘 것)
OPERATOR_C = ("영양제로 불면이 바로 치료됩니다", "당뇨 100% 보장", "암 완치 보장", "이 영양제는 피로를 즉시 없애줍니다", "수면제 바로 끊어도 될까", "피로를 즉시 줄이는 방법", "자세를 바로 교정하는 책상 설정", "통증을 완전히 없애는 의자 선택법", "당뇨를 무조건 개선하는 식품")
EXTRA_C = (
    "두통이 즉시 사라지는 방법", "두통을 바로 없애는 지압법", "불면증 완전히 치료하는 영양제", "우울증 확실히 낫는 방법", "혈압을 100% 낮추는 음식", "탈모 완치 보장 샴푸", "체중을 무조건 줄이는 식단", "관절염 통증을 즉시 없애는 크림",
    "혈당을 확실히 낮춰주는 영양제", "암을 100% 예방하는 식품", "치매 예방 보장 영양제", "감기를 바로 낫게 하는 차", "고혈압약 끊어도 되는 방법", "당뇨약 안 먹고 낫는 방법", "불면증 약 없이 하룻밤에 완치", "피로를 한 번에 해결하는 영양제",
    "통증 즉각 완화되는 방법", "피로가 즉시 풀리는 비타민", "영양제 먹고 하루 만에 살 빠지는 법", "만성피로 완전 해소", "알레르기 확실히 치료하는 방법", "요통 100% 해결 보장", "아토피 완치 비법", "이 약 하나로 모든 통증이 사라진다",
    "몸살 즉시 해결하는 방법", "콜레스테롤을 무조건 낮추는 영양제", "갑상선 질환 완치 가능", "항암 효과 100% 영양제", "면역력을 즉시 높이는 영양제", "수면의 질을 바로 개선하는 영양제", "눈 건강 즉시 회복하는 방법", "피로를즉시줄이는방법",
    "피로를 즉시 줄여줍니다", "피로를 즉시 줄일 수 있어요", "통증이 완전히 사라지는 의자", "당뇨를 반드시 개선하는 식품", "당뇨 100%보장", "당뇨 백퍼센트 보장", "암 완치를 보장합니다", "암 100% 완치", "수면제 바로 끊는 법", "수면제 즉시 끊어도 됩니다",
    "자세를 즉시 교정하는 의자", "자세 확실히 교정하는 방법", "피로가 완전히 풀리는 영양제", "영양제 먹으면 즉시 낫는다", "비타민으로 불면 완전히 해결", "관절 통증 완치 보장", "복용만 하면 통증이 바로 사라집니다", "하루 만에 당뇨 극복",
    "Cure diabetes 100% guaranteed", "Supplement instantly eliminates fatigue",
)
# 그 가운데 이번 보강 전에 초안으로 나오던 열 문장과 원인(코드 안의 이름은 화면에 나오지 않는다)
MISSED_TEN = (
    ("두통을 바로 없애는 지압법", "straddle"), ("감기를 바로 낫게 하는 차", "symptom"), ("요통 100% 해결 보장", "symptom"), ("몸살 즉시 해결하는 방법", "symptom"), ("눈 건강 즉시 회복하는 방법", "symptom"),
    ("피로를 한 번에 해결하는 영양제", "instant"), ("영양제 먹고 하루 만에 살 빠지는 법", "instant"), ("하루 만에 당뇨 극복", "instant"), ("고혈압약 끊어도 되는 방법", "quit"), ("당뇨약 안 먹고 낫는 방법", "quit"),
)
# A·B·일반 대조 40문장 — (검증자가 기대한 값, 글, **이번 보강 전(기준 커밋) 판정기가 실제로 낸 단계** G·A·B·C). 옛 단계는 미리 계산해 박았다(새 코드로 다시 계산하지 않는다)
CONTRAST_40 = (
    ("A", "영양제 바로 알기", "A"), ("A", "피로할 때 작업환경을 점검하는 방법", "A"), ("A", "자세가 불편할 때 책상 높이를 확인하는 기준", "A"), ("B", "영양제를 식후 바로 먹어도 될까", "B"), ("B", "피로 회복 영양제를 비교하는 기준", "B"),
    ("B", "당뇨 관련 공식 표시사항 확인하기", "B"), ("B", "당뇨 환자의 식품 라벨 확인 기준", "B"), ("B", "당뇨 환자가 무조건 피해야 할 음식", "B"), ("B", "암 관련 공식 정보 찾는 방법", "B"), ("G", "암호 관리자 사용법 비교", "G"),
    ("G", "암호화 방식 쉽게 이해하기", "G"), ("A", "눈이 피로할 때 모니터 위치 확인하기", "A"), ("A", "어깨가 아플 때 의자 높이 확인하기", "G"), ("A", "건강기능식품 표시사항 읽는 법", "A"), ("A", "비타민 섭취 시간 기록하는 방법", "A"),
    ("A", "수면 환경 점검 체크리스트", "A"), ("A", "체중 관리 앱 비교하는 기준", "A"), ("A", "홍삼 제품 성분표 확인하는 순서", "A"), ("B", "피로를 줄이는 업무 일정 짜는 방법", "A"), ("B", "당뇨 환자 식단 기록 방법", "B"),
    ("B", "고혈압 약 복용 시간 기록하기", "B"), ("G", "무선 청소기 고르는 기준", "G"), ("G", "노트북 거치대 비교하는 방법", "G"), ("G", "강아지 산책 준비물 정리", "G"), ("G", "겨울 이불 세탁하는 순서", "G"),
    ("G", "냉장고 정리 순서", "G"), ("G", "이사 체크리스트 만드는 방법", "G"), ("G", "자세히 알아보는 보험 용어", "G"), ("G", "즉시 사용 가능한 문서 템플릿 모음", "G"), ("G", "바로가기 아이콘 만드는 방법", "G"),
    ("G", "완전히 새로운 공간 정리법", "G"), ("G", "확실히 알아두면 좋은 절약 팁", "G"), ("G", "반드시 챙길 여행 준비물", "G"), ("G", "무조건 저장해 두는 스마트폰 단축키", "G"), ("G", "100% 환불 규정 확인하는 방법", "G"),
    ("G", "보장 범위 비교하는 자동차 보험 용어", "G"), ("G", "통증 없는 신발 고르기 전에 발 크기 재는 방법", "A"), ("A", "두통이 있을 때 확인할 생활 습관 목록", "A"), ("A", "감기 기운이 있을 때 집에서 확인할 것", "G"),
    ("A", "허리가 불편할 때 책상 높이 맞추는 방법", "G"),
)
# 일상 문장 61개 — (글, 보강 전 단계, 보강 후 단계). 단계가 달라진 것은 **새 건강 낱말이 든 평범한 문장이 일반 → 표시만·근거 확인 필요로 올라간 것뿐**이고 어느 것도 중지가 아니다
ORDINARY_61 = (
    ("이사 후 주소 변경을 한 번에 끝내는 방법", "G", "G"), ("서랍 정리를 하루 만에 끝내는 방법", "G", "G"), ("가계부 쓰기를 단번에 익히는 요령", "G", "G"), ("엑셀 파일을 곧바로 열어 보는 단축키", "G", "G"),
    ("냉장고 청소를 한꺼번에 마치는 순서", "G", "G"), ("집 정리를 단숨에 끝내는 법", "G", "G"), ("이메일 정리를 당장 시작하는 습관", "G", "G"), ("비밀번호를 즉시 바꾸는 방법", "G", "G"), ("택배 반품을 바로 신청하는 방법", "G", "G"),
    ("노트북 배터리 사용 시간을 확실히 늘리는 설정", "G", "G"), ("와이파이 속도를 즉시 높이는 방법", "G", "G"), ("서버 응답 시간을 하루 만에 줄이는 방법", "G", "G"), ("생활비를 한 번에 줄이는 방법", "G", "G"),
    ("메일함 용량을 완전히 비우는 방법", "G", "G"), ("오류 메시지를 단번에 해결하는 방법", "G", "G"), ("여행 짐을 하루 만에 싸는 체크리스트", "G", "G"), ("사진 정리를 한꺼번에 끝내는 앱", "G", "G"),
    ("100% 무료 체험 조건 확인하는 방법", "G", "G"), ("환불 규정 보장 범위 비교", "G", "G"), ("이력서 작성을 곧바로 시작하는 순서", "G", "G"), ("블로그 글쓰기 습관을 단번에 바꾸는 방법", "G", "G"),
    ("가습기 필터를 한 번에 교체하는 요령", "G", "G"), ("게임 캐릭터 체력 회복 아이템 정리", "G", "G"), ("머리 감기 순서와 두피 관리 루틴", "G", "G"), ("빨리감기 단축키 모음", "G", "G"), ("경기침체 대비 가계부 쓰는 법", "G", "G"),
    ("건설사 순위 비교하는 방법", "G", "G"), ("이명박 정부 정책 정리", "G", "G"), ("한눈에 건강 상태 확인하는 앱 화면 구성", "G", "G"), ("손에 착 감기는 마우스 후기", "G", "G"), ("영상 되감기 기능 설명", "G", "G"),
    ("당뇨 예방 식단 한 번에 정리하기", "B", "B"), ("고혈압 식단 일지를 하루 만에 정리하는 법", "B", "B"), ("영양제 한 번에 몇 알 먹나요", "A", "A"), ("영양제 하루 만에 도착하는 배송 업체 비교", "A", "A"),
    ("피로 기록을 한꺼번에 정리하는 앱", "A", "A"), ("통증 일지를 단번에 확인하는 방법", "A", "A"), ("수술 후 하루 만에 퇴원하는 방법", "A", "A"), ("스트레스 해소 여행 코스 하루 만에 다녀오기", "A", "A"),
    ("감기 예방 식단", "G", "A"), ("요통 완화 운동 루틴 정리", "G", "A"), ("시력 검사표 인쇄하기", "G", "A"), ("코골이 앱 비교", "G", "A"), ("손목터널증후군 예방 스트레칭", "G", "B"), ("저림 증상 기록 노트", "G", "A"),
    ("수면제 없이 잠드는 방법", "A", "A"), ("수면제 끊는 방법", "A", "A"), ("항생제 끊어도 되나요", "B", "B"), ("혈압약 끊어도 되는 시기", "B", "B"), ("혈압약 끊어도 되는지 알아보기", "B", "B"), ("처방약 영수증 정리하는 방법", "A", "A"),
    ("피로를 즉시 줄이는지 알아보기", "A", "A"), ("피로 일지를 바로 확인하는 가이드", "A", "A"), ("통증 기록을 즉시 저장하는 지침", "A", "A"), ("이사 체크리스트 하루 만에 끝내는 방법", "G", "G"), ("감기약 보관 방법", "G", "A"),
    ("눈 건강 관리 가이드", "G", "A"), ("건조한 눈 후기", "G", "A"), ("생리통 일기 쓰는 법", "G", "A"), ("기침 소리 녹음 앱", "G", "A"), ("설사 증상 기록 노트", "G", "A"),
)
NEW_SYMPTOMS = ("요통", "몸살", "감기", "눈 건강", "건조한 눈", "시력", "설사", "기침", "가려움", "저림", "생리통", "코골이", "이명")                                    # 13
NEW_DISEASES = ("손목터널증후군", "오십견", "두드러기", "구내염", "치주염")                                                                                   # 5
NEW_MASKS = {                                                                                                                                                # D-291 마스크 가운데 남은 둘 — 마스크가 지켜 주는 일상 문장(마스크가 없으면 새 증상 낱말이 걸린다)
    "머리 감기": "머리 감기 순서와 두피 관리 루틴", "착 감기": "손에 착 감기는 마우스 후기",
}
REMOVED_MASKS = {                                                                                                                                            # 지운 마스크 일곱 — 다섯(D-303)은 낱말 처음에서만 읽는 증상이 스스로 거르게 되어, 둘(D-307 `한눈에`·`첫눈에`)은 한 낱말 마스크가 글을 갈라 기준이 중지로 읽던 글을 낮춰서 지웠다(문장은 마스크 없이도 일반이다)
    "빨리감기": "영상 빨리감기 단축키 모음", "되감기": "영상 되감기 기능 설명", "경기침체": "경기침체 대비 가계부 쓰는 법", "이명박": "이명박 정부 정책 정리", "건설사": "건설사 순위 비교하는 방법",
    "한눈에": "한눈에 건강 상태 확인하는 앱 화면 구성", "첫눈에": "첫눈에 건강해 보이는 사람의 특징",
}
NEW_MASKS_2 = {                                                                                                                                              # D-303 마스크 열넷(처음 열다섯에서 `첫눈에` 를 D-307 이 지웠다) — 띄어 쓴 일상 구절·이름
    "줄 감기": "이어폰 줄 감기 쉬운 정리함 고르기", "태엽 감기": "시계 태엽 감기 방법", "붕대 감기": "붕대 감기 연습하는 방법", "전선 감기": "전선 감기 정리하는 방법", "케이블 감기": "케이블 감기 전에 정리하는 순서",
    "목도리 감기": "목도리 감기 연습 영상 모음", "목에 감기는": "목에 감기는 목도리 추천", "손에 감기는": "컨트롤러 그립 손에 감기는 느낌 비교", "배추 저림": "배추 저림 시간 맞추는 방법",
    "건조한 눈빛": "건조한 눈빛으로 바라보다 라는 표현 정리", "건조한 눈길": "건조한 눈길 걷기 좋은 겨울 산책로", "건조한 눈매": "건조한 눈매 묘사하는 글쓰기 표현", "건조한 눈동자": "건조한 눈동자 묘사하는 문장",
    "건조한 눈썹": "건조한 눈썹 정리하는 뷰티 팁",
}
NEW_SYMPTOMS_2 = ("복통", "인후통", "치통", "관절통", "콧물", "무좀", "습진")                                                                                      # 7 (D-303)
NEW_GUARANTEES = ("해결 보장", "치유 보장", "호전 보장")
INSTANT = ("단번에", "한 번에", "한꺼번에", "하루 만에")
UNKNOWN_COUNTS = ("단번에", "하루 만에")                                                                                                                       # D-293 의 모르는 서술어 규칙 낱말 — D-299 가 규칙을 없앴다(시험은 없어진 것을 못박는다)
QUIT_SENTENCES = (                                                                                                                                           # (표 항목, 그 항목만이 중지로 읽히게 하는 글) — 한 줄씩 지우면 잡힌다
    ("끊고", "당뇨약 끊고 낫는 방법"), ("끊어도", "당뇨약 끊어도 낫는 방법"), ("끊으면", "당뇨약 끊으면 낫는 방법"), ("안 먹고", "당뇨약 안 먹고 낫는 방법"), ("안 먹어도", "당뇨약 안 먹어도 낫는 방법"), ("먹지 않고", "당뇨약 먹지 않고 낫는 방법"),
    ("먹지 않아도", "당뇨약 먹지 않아도 낫는 방법"), ("중단하고", "당뇨약 중단하고 낫는 방법"), ("중단해도", "당뇨약 중단해도 낫는 방법"), ("복용하지 않고", "당뇨약 복용하지 않고 낫는 방법"), ("복용하지 않아도", "당뇨약 복용하지 않아도 낫는 방법"),
    ("그만 먹고", "당뇨약 그만 먹고 낫는 방법"), ("멈추고", "당뇨약 멈추고 낫는 방법"),
)


def stage(text):
    return sf.check_text([text]).stage


def report_of(text):
    return sf.check_text([text])


def codes(text):
    return [finding.code for finding in sf.check_text([text]).findings if finding.flag == "health_check"]


def blanked_without(sentence, mask):
    """마스크 하나를 뺀 표로 `health_signals` 와 같은 가림을 한 글 — (가린 글, 낱말 시작 자리). 마스크가 하는 일을 보려는 도구다."""
    ordered = sorted((word for word in dict.fromkeys(cn.HEALTH_MASKS_KO) if word != mask), key=lambda word: (-len(word), word))
    regular = tuple(cn.phrase_regex(word) for word in ordered if not word.startswith("암") and word not in cn.HEALTH_MASKS_WORD_KO)
    at_start = tuple(cn.phrase_regex(word) for word in ordered if word.startswith("암"))
    within = tuple(cn.phrase_regex(word) for word in ordered if word in cn.HEALTH_MASKS_WORD_KO)
    joined, starts = cn.compact_marked([cn.fold(sentence)])
    return cn.blank_within_words(cn.blank_at_starts(cn.blank(joined, regular), starts, at_start), starts, within), starts


def candidate_stages(text):
    """글을 후보의 제목·핵심 키워드·보조 키워드 자리에 하나씩 넣었을 때의 단계 — 나머지 칸은 중립 낱말(검증자의 방식)."""
    neutral = {"topic": "예시 안내 주제", "primary_keyword": "예시 낱말", "secondary_keywords": ("예시 보조 가", "예시 보조 나")}
    found = {}
    for place in neutral:
        values = dict(neutral)
        values[place] = (text, "예시 보조 나") if place == "secondary_keywords" else text
        found[place] = sf.assess(ts.make(content_type="explainer", **values)).stage
    return found


class MissedTenTest(unittest.TestCase):                                                                                  # Y1
    def test_each_of_the_ten_missed_sentences_now_stops_the_draft(self):
        self.assertEqual(len(MISSED_TEN), 10)
        self.assertEqual(len({text for text, _cause in MISSED_TEN}), 10)
        for text, _cause in MISSED_TEN:
            with self.subTest(text=text):
                report = report_of(text)
                self.assertEqual((report.stage, report.stop, codes(text)), (STOP, True, ["HEALTH_STOP"]))
                self.assertTrue(sf.needs_evidence(report.stage))

    def test_they_stop_in_the_title_the_main_keyword_and_the_sub_keyword_alike(self):
        for text, _cause in MISSED_TEN:
            with self.subTest(text=text):
                self.assertEqual(candidate_stages(text), {"topic": STOP, "primary_keyword": STOP, "secondary_keywords": STOP})

    def test_the_straddling_question_ending_was_the_cause_of_the_pressure_point_sentence_not_the_word_after_it(self):
        text = "두통을 바로 없애는 지압법"
        signals = cn.health_signals([text])
        self.assertEqual(signals.scoped, (("바로", "soft", "effect"),), "‘없애는 지압법’ 의 ‘는지’ 를 의문으로 읽어 단정 낱말을 끄던 것이 사라졌다")
        self.assertEqual(signals.concept_key(), (1, 0, 0, 0, 1, 1))
        self.assertEqual(stage("두통을 바로 없애는 방법"), STOP, "대조: 같은 문장에서 끝말만 다르면 옛 판정도 중지였다")

    def test_each_cause_is_fixed_where_the_cause_lives(self):
        for word in ("감기", "요통", "몸살", "눈 건강"):
            self.assertIn(word, cn.HEALTH_SYMPTOM_KO)
        self.assertIn("해결 보장", cn.HEALTH_ASSERT_EFFECT_KO)
        self.assertEqual(cn.health_signals(["요통 100% 해결 보장"]).assert_effect, ("해결 보장",))
        for text, phrase in (("피로를 한 번에 해결하는 영양제", "한 번에"), ("영양제 먹고 하루 만에 살 빠지는 법", "하루 만에"), ("하루 만에 당뇨 극복", "하루 만에")):
            with self.subTest(text=text):
                self.assertIn(phrase, cn.health_signals([text]).counted_assert())
        self.assertEqual(cn.health_signals(["고혈압약 끊어도 되는 방법"]).quit, ("끊어도",))
        self.assertEqual(cn.health_signals(["당뇨약 안 먹고 낫는 방법"]).quit, ("안 먹고",))

    def test_the_causes_are_the_four_the_report_names(self):
        self.assertEqual({cause for _text, cause in MISSED_TEN}, {"straddle", "symptom", "instant", "quit"})
        self.assertEqual([cause for _text, cause in MISSED_TEN].count("symptom"), 4)


class SentenceListsTest(unittest.TestCase):                                                                              # Y2
    def test_the_lists_have_the_documented_sizes(self):
        self.assertEqual((len(OPERATOR_C), len(set(OPERATOR_C)), len(EXTRA_C), len(set(EXTRA_C))), (9, 9, 52, 52))
        self.assertEqual(len(CONTRAST_40), 40)
        self.assertEqual(len({text for _kind, text, _old in CONTRAST_40}), 40)
        self.assertEqual(len(ORDINARY_61), 61)
        self.assertEqual(len({text for text, _old, _new in ORDINARY_61}), 61)
        self.assertEqual({text for text, _cause in MISSED_TEN} - set(EXTRA_C), set(), "미탐 10개는 52개 안에 있다")

    def test_all_fifty_two_intended_c_sentences_and_the_operator_nine_stop(self):
        for text in OPERATOR_C + EXTRA_C:
            with self.subTest(text=text):
                report = report_of(text)
                self.assertEqual((report.stage, report.stop), (STOP, True))
                self.assertEqual(codes(text), ["HEALTH_STOP"])

    def test_the_operator_nine_stop_in_every_candidate_place(self):
        for text in OPERATOR_C:
            with self.subTest(text=text):
                self.assertEqual(candidate_stages(text), {"topic": STOP, "primary_keyword": STOP, "secondary_keywords": STOP})

    def test_the_intended_stops_are_not_just_the_old_floor_they_are_read_by_the_new_key_or_the_floor_as_before(self):
        # 이번 보강이 새로 읽는 문장(미탐 10개)은 옛 바닥이 아니라 새 열쇠(`concept_key`)가 단정으로 읽는다 — 옛 중지 바닥에 새 낱말을 넣지 않았다(Y7)
        for text, _cause in MISSED_TEN:
            with self.subTest(text=text):
                signals = cn.health_signals([text])
                self.assertEqual(sf.HEALTH_MATRIX[signals.concept_key()], STOP)


class ContrastAndOrdinaryTest(unittest.TestCase):                                                                        # Y3
    def test_the_forty_contrast_sentences_keep_their_stage_and_none_stops(self):
        changed = []
        for kind, text, old in CONTRAST_40:
            with self.subTest(text=text):
                report = report_of(text)
                self.assertFalse(report.stop, "A·B·일반 대조는 초안이 나와야 한다")
                self.assertNotEqual(report.stage, STOP)
                if report.stage != SHORT[old]:
                    changed.append((text, old, report.stage))
        self.assertEqual(changed, [("감기 기운이 있을 때 집에서 확인할 것", "G", MARK)], "단 하나 — `감기` 를 증상 낱말에 더해 일반 → 표시만(검증자가 기대한 값 A 와 같다). 초안은 그대로 나온다")

    def test_the_contrast_sentences_with_the_operator_a_and_b_labels_are_where_the_operator_put_them(self):
        for kind, text, _old in CONTRAST_40:
            if kind in ("A", "B") and text in ("영양제 바로 알기", "영양제를 식후 바로 먹어도 될까", "피로 회복 영양제를 비교하는 기준", "당뇨 관련 공식 표시사항 확인하기", "당뇨 환자의 식품 라벨 확인 기준", "피로할 때 작업환경을 점검하는 방법"):
                with self.subTest(text=text):
                    self.assertEqual(stage(text), {"A": MARK, "B": EVIDENCE}[kind])

    def test_the_sixty_one_ordinary_sentences_changed_only_by_the_new_health_words_and_never_to_a_stop(self):
        newest = NEW_SYMPTOMS + NEW_DISEASES + ("감기", "한눈에")
        moved = []
        for text, old, new in ORDINARY_61:
            with self.subTest(text=text):
                self.assertEqual(stage(text), SHORT[new])
                self.assertNotEqual(SHORT[new], STOP)
                if old != new:
                    moved.append(text)
                    self.assertTrue(any(word.replace(" ", "") in text.replace(" ", "") for word in newest), f"새 건강 낱말이 없는데 단계가 달라졌다(과탐): {text}")
                    self.assertIn(SHORT[new], (MARK, EVIDENCE))
                    self.assertEqual(SHORT[old], GENERAL, "일반 → 표시만·근거 확인 필요만 있다")
        self.assertEqual(len(moved), 12, "새 낱말이 든 평범한 문장 열둘 — 일반 → 표시만 열하나·근거 확인 필요(질환 낱말) 하나")

    def test_the_older_pinned_sets_are_unchanged_by_this_work(self):
        # 앞선 묶음(WP-B2·B3·B4)이 못박은 운영자 예시 16개·옛 표본 16개·평범한 생활 문장 66개 — 이 묶음도 그대로다
        for text, expected, _points, _code in hc.OPERATOR_EXAMPLES:
            with self.subTest(operator=text):
                self.assertEqual(stage(text), expected)
        for text, expected, _points in hc.OLD_SAMPLES:
            with self.subTest(old=text):
                self.assertEqual(stage(text), expected)
        for text, _old, new in hc.ORDINARY_66:
            with self.subTest(ordinary=text):
                self.assertEqual(stage(text), hc.SHORT[new])
        self.assertEqual((len(hc.OPERATOR_EXAMPLES), len(hc.OLD_SAMPLES), len(hc.ORDINARY_66)), (16, 16, 66))


class GridTest(unittest.TestCase):                                                                                       # Y4
    SYMPTOMS_10 = ("피로", "불면", "통증", "자세", "체중", "두통", "스트레스", "요통", "몸살", "감기")
    WORDS_5 = ("즉시", "바로", "완전히", "확실히", "무조건")
    VERBS_8 = ("줄이는", "없애는", "해소하는", "교정하는", "치료하는", "회복하는", "완화하는", "개선하는")
    VERBS_MORE = ("해결하는", "낮추는", "풀어주는", "낫게 하는", "극복하는", "사라지게 하는", "예방하는", "감량하는")

    def test_the_four_hundred_combinations_leave_no_draft(self):
        count = 0
        for symptom, word, verb in itertools.product(self.SYMPTOMS_10, self.WORDS_5, self.VERBS_8):
            count += 1
            text = f"{symptom}을 {word} {verb} 방법"
            self.assertEqual(stage(text), STOP, text)
        self.assertEqual(count, 400)

    def test_every_new_symptom_word_stops_with_every_instant_word_and_every_effect_verb(self):
        for symptom, word, verb in itertools.product(NEW_SYMPTOMS, self.WORDS_5 + ("즉각", "당장", "단숨에", "순식간에") + INSTANT + ("곧바로",), self.VERBS_8 + self.VERBS_MORE):
            text = f"{symptom}을 {word} {verb} 방법"
            self.assertEqual(stage(text), STOP, text)

    def test_the_old_symptom_words_stop_with_the_new_instant_phrases_too(self):
        for symptom, word, verb in itertools.product(self.SYMPTOMS_10[:7], INSTANT + ("곧바로",), self.VERBS_8):
            text = f"{symptom}을 {word} {verb} 방법"
            self.assertEqual(stage(text), STOP, text)

    def test_the_conjugated_forms_beside_a_new_symptom_word_stop_without_any_instant_word(self):
        for symptom in NEW_SYMPTOMS:
            for form in ("줄여 줍니다", "줄일 수 있습니다", "없애 줍니다", "없앨 수 있어요", "해소해 줍니다", "치료할 수 있다"):
                with self.subTest(symptom=symptom, form=form):
                    self.assertEqual(stage(f"{symptom}을 {form}"), STOP)

    def test_an_action_order_beside_a_new_symptom_word_is_not_a_stop(self):
        for symptom, word, action in itertools.product(NEW_SYMPTOMS, ("즉시", "바로", "단번에", "한 번에", "하루 만에", "한꺼번에"), ("확인하는 체크리스트", "기록하는 앱", "정리하는 방법", "저장하는 습관")):
            text = f"{symptom} 증상을 {word} {action}"
            self.assertNotEqual(stage(text), STOP, text)
            self.assertEqual(stage(text), MARK, text)


class NewWordsTest(unittest.TestCase):                                                                                   # Y5
    def test_the_new_words_are_the_documented_last_entries_of_the_tables(self):
        self.assertEqual(cn.HEALTH_SYMPTOM_KO[-20:-7], NEW_SYMPTOMS)
        self.assertEqual(cn.HEALTH_SYMPTOM_KO[-7:], NEW_SYMPTOMS_2)
        self.assertEqual(cn.HEALTH_DISEASE_KO[-5:], NEW_DISEASES)
        self.assertEqual(cn.HEALTH_ASSERT_EFFECT_KO[-3:], NEW_GUARANTEES)
        self.assertEqual(cn.HEALTH_MASKS_KO[-16:-14], tuple(NEW_MASKS))
        self.assertEqual(cn.HEALTH_MASKS_KO[-14:], tuple(NEW_MASKS_2))
        for mask in REMOVED_MASKS:
            self.assertNotIn(mask, cn.HEALTH_MASKS_KO)
        self.assertEqual((len(cn.HEALTH_SYMPTOM_KO), len(cn.HEALTH_DISEASE_KO), len(cn.HEALTH_ASSERT_EFFECT_KO), len(cn.HEALTH_MASKS_KO)), (59, 76, 19, 64))

    def test_each_new_symptom_word_alone_is_a_mark_with_no_cost_and_a_claim_with_it_is_a_stop(self):
        for word in NEW_SYMPTOMS:
            with self.subTest(word=word):
                self.assertEqual(stage(f"예시 {word} 글"), MARK)
                self.assertEqual(codes(f"예시 {word} 글"), ["HEALTH_TOPIC"])
                self.assertEqual(stage(f"{word} 기록 앱 만들기"), MARK)
                self.assertEqual(stage(f"{word} 때 확인할 생활 습관"), MARK)
                self.assertEqual(stage(f"{word} 바로 확인하는 체크리스트"), MARK)
                self.assertEqual(stage(f"{word}을 즉시 없애는 방법"), STOP)
                self.assertEqual(stage(f"{word} 완치 보장"), STOP)
                self.assertEqual(stage(f"{word} 100% 해결 보장"), STOP)
                self.assertEqual(stage(f"{word}을 한 번에 해결하는 법"), STOP)
                self.assertIn(word, cn.health_signals([f"예시 {word} 글"]).symptom)

    def test_each_new_disease_word_alone_needs_evidence_and_a_strong_claim_with_it_stops(self):
        for word in NEW_DISEASES:
            with self.subTest(word=word):
                self.assertEqual(stage(f"예시 {word} 글"), EVIDENCE)
                self.assertEqual(stage(f"{word} 관련 뉴스 정리"), EVIDENCE)
                self.assertEqual(stage(f"{word} 바로 확인하는 체크리스트"), EVIDENCE)
                self.assertEqual(stage(f"{word} 100% 보장"), STOP)
                self.assertEqual(stage(f"{word}을 즉시 없애는 방법"), STOP)
                self.assertIn(word, cn.health_signals([f"예시 {word} 글"]).disease)

    def test_each_mask_keeps_one_everyday_sentence_out_of_the_health_words(self):
        for mask, sentence in {**NEW_MASKS, **NEW_MASKS_2}.items():
            with self.subTest(mask=mask):
                self.assertIn(mask, cn.HEALTH_MASKS_KO)
                self.assertEqual((stage(sentence), codes(sentence)), (GENERAL, []))
                self.assertEqual(cn.health_signals([sentence]).key(), (0, 0, 0, 0))
                blanked, starts = blanked_without(sentence, mask)
                found = cn.find_ko(blanked, starts, cn.Tables.s_weak) + cn.find_ko(blanked, starts, cn.Tables.s_strong)
                self.assertTrue(found, f"마스크 ‘{mask}’ 를 빼면 이 문장에서 건강 낱말이 걸려야 한다(마스크가 하는 일)")

    def test_the_seven_masks_that_later_work_made_unnecessary_or_harmful_are_gone_and_their_sentences_stay_general(self):
        # D-303: 낱말 처음에서만 읽는 증상(`감기`·`기침`·`설사`)과 `이명` 의 낱말 끝 규칙이 `빨리감기`·`되감기`·`경기침체`·`건설사`·`이명박` 속 낱말을 스스로 거른다 — 마스크를 지워도 문장은 일반이다(마스크가 같은 일을 둘이 하지 않게)
        # D-307: `눈 건강` 을 낱말 처음에서만 읽게 해 `한눈에 건강`·`첫눈에 건강` 을 스스로 거른다 — 한 낱말 마스크 둘은 글을 갈라 기준이 중지로 읽던 글을 낮추어서 지웠다
        for mask, sentence in REMOVED_MASKS.items():
            with self.subTest(mask=mask):
                self.assertNotIn(mask, cn.HEALTH_MASKS_KO)
                self.assertEqual((stage(sentence), codes(sentence)), (GENERAL, []))
                joined, starts = cn.compact_marked([cn.fold(sentence)])
                self.assertEqual(cn.find_ko(joined, starts, cn.Tables.s_weak) + cn.find_ko(joined, starts, cn.Tables.s_strong), [], "마스크 없이도 걸리지 않는다")

    def test_the_real_health_meanings_of_the_new_words_are_still_read(self):
        for text, expected in (("감기 예방 식단", MARK), ("감기를 예방하는 식단", MARK), ("기침 완화 방법", MARK), ("이명 증상 기록", MARK), ("설사 증상 기록 노트", MARK), ("경기 침체 속 기침 완화 방법", MARK),
                               ("머리 감기 전 감기 예방 방법", MARK), ("눈 건강을 지키는 습관", MARK), ("눈에 건강한 음식", MARK), ("시력 보호 필름 비교", MARK)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)

    def test_two_everyday_words_were_left_out_on_purpose_and_stay_so_until_the_operator_decides(self):
        # 독립 검증이 읽히지 않는다고 찾은 19 낱말 가운데 17개를 더했다. `체력`(게임 체력 바·일상어)·`노안`(동안의 반대말)은 일상어와 겹쳐 뺐다 — 넣으려면 운영자 확인 뒤 이 시험을 의식적으로 함께 고친다
        for word in ("체력", "노안"):
            self.assertNotIn(word, cn.HEALTH_SYMPTOM_KO)
            self.assertNotIn(word, cn.HEALTH_DISEASE_KO)
            self.assertEqual(stage(f"{word}을 즉시 없애는 방법"), GENERAL)

    def test_the_three_result_guarantees_stop_a_symptom_and_the_word_itself_was_not_added_to_the_effect_table(self):
        for symptom, noun in (("요통", "해결"), ("피로", "치유"), ("스트레스", "호전")):
            for text in (f"{symptom} {noun} 보장", f"{symptom} 100% {noun} 보장", f"{symptom} {noun}을 보장합니다"):
                with self.subTest(text=text):
                    self.assertEqual(stage(text), STOP)
            self.assertEqual(stage(f"{symptom} 보장"), MARK, "대조: 보장만으로는 표시만(옛 규칙)")
        self.assertEqual(len(cn.HEALTH_EFFECT_KO), 34)
        self.assertEqual(cn.HEALTH_EFFECT_KO[-1], "도와")
        for word in ("해결", "치유", "호전"):
            self.assertNotIn(word, cn.HEALTH_EFFECT_KO, "효과 낱말 표에 넣으면 `영양제 오류 해결` 같은 평범한 글(엔진이 만드는 후보 포함)이 근거 확인 필요로 올라간다")
        for text in ("영양제 오류 해결", "영양제 오류 해결 방법", "비타민 보관 문제 해결", "앱 오류 해결 보장", "서비스 문제 해결 보장 안내"):
            with self.subTest(text=text):
                self.assertIn(stage(text), (GENERAL, MARK), "결과 낱말이 건강 대상 곁에 있다고 올라가지 않는다(`보장` 과 함께일 때만 센다)")


class QuestionTailTest(unittest.TestCase):                                                                               # Y6
    # 보강 전에는 모두 표시만(A) 이었다 — 끝말 `가이드`·`지침` 의 첫 글자와 앞 낱말의 끝이 이어 붙어 ‘는가’·‘는지’ 같은 의문 꼬리로 읽혔기 때문이다(기준 커밋에서 직접 확인)
    STRADDLE = ("두통을 바로 없애는 지압법", "두통을 바로 없애는 지압 방법", "두통을 바로 없애는 가이드", "피로를 즉시 없애는 가이드", "통증을 바로 없애는 지름길", "통증을 바로 없애는 지침", "두통을 바로 없애는 지식", "피로를 즉시 줄이는 지도",
                "두통을 단숨에 줄이는 지압", "체중을 무조건 줄이는 가이드", "붓기를 즉시 빼는 가이드", "소화를 즉시 돕는 가이드", "통증을 당장 줄이는 지침", "스트레스를 즉각 낮추는 가이드", "소화불량을 바로 낮추는 가이드")

    def test_an_ending_that_only_forms_across_two_spaced_words_is_not_a_question(self):
        self.assertEqual(len(self.STRADDLE), len(set(self.STRADDLE)))
        for text in self.STRADDLE:
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)
                self.assertNotEqual(cn.health_signals([text]).scoped, ())

    def test_a_real_question_ending_inside_one_word_still_switches_the_assertion_off(self):
        for text in ("피로를 즉시 줄이는지 알아보기", "두통을 바로 없애는지 궁금해요", "피로를 즉시 줄일까", "피로를 즉시 줄일까 고민하는 가이드", "체중을 무조건 줄이는지 확인하는 지침"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), MARK)
                self.assertEqual(cn.health_signals([text]).counted_assert(), ())
        for text in ("당뇨 보장하는지 확인하기", "당뇨를 보장하는지 알아보기"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), EVIDENCE, "질환만 있다 — 한 낱말 안의 ‘는지’ 는 예전처럼 ‘보장’ 을 끈다")

    def test_the_always_assertion_words_follow_the_same_rule(self):
        self.assertEqual(stage("당뇨 보장하는 가이드"), STOP, "‘보장하는 가이드’ 의 ‘는가’ 는 걸친 것이다 — 질환 + 보장 = 단정 위험(운영자 ③)")
        self.assertEqual(cn.health_signals(["당뇨 보장하는 가이드"]).counted_assert(), ("보장",))

    def test_a_question_ending_does_not_reach_across_text_pieces_or_after_a_stem_that_is_not_hangul(self):
        # 의문 꼬리의 어미 앞 조각(0–2글자)은 한글 음절만이다(옛 정규식 그대로) — 다른 글 조각이나 숫자·영문이 끼면 의문이 아니다
        self.assertEqual(sf.check_text(["당뇨 보장", "하는지"]).stage, STOP, "‘보장’ 과 ‘하는지’ 가 서로 다른 글 조각이면 의문이 아니다")
        self.assertEqual(sf.check_text(["당뇨 보장하는지"]).stage, EVIDENCE, "같은 글 조각 안의 ‘하는지’ 는 의문이다")
        self.assertEqual(stage("당뇨 보장 2일까"), STOP, "숫자가 낀 ‘2일까’ 는 한글 어미 앞 조각이 아니다")
        self.assertEqual(stage("당뇨 보장 a일까"), STOP)
        self.assertEqual(stage("당뇨 보장 줄일까"), EVIDENCE, "한글 한 글자 + ‘일까’ 는 의문이다")

    def test_the_helper_reads_where_a_word_starts_inside_the_ending(self):
        def asks(text, word):
            joined, starts = cn.compact_marked([cn.fold(text)])
            return cn._asks_after(joined, starts, joined.index(cn.compact(cn.fold(word))) + len(cn.compact(cn.fold(word))))
        for text, word, expected in (("바로 없애는 지압법", "바로", False), ("바로 없애는지 알아보기", "바로", True), ("바로 줄일까", "바로", True), ("바로 줄일 까", "바로", False), ("바로 하는 가이드", "바로", False),
                                     ("바로 해소한 가이드", "바로", False), ("바로 해소한가 궁금", "바로", True), ("바로 알아볼지 정하기", "바로", False), ("바로 효과 있을까", "바로", True), ("바로 효과 있나요", "바로", True), ("바로", "바로", False),
                                     ("바로 일까", "바로", True), ("바로 있나요", "바로", True), ("바로 일 까", "바로", False)):          # 앞 조각이 0글자인 어미(`즉시 일까`)도 읽는다
            with self.subTest(text=text):
                self.assertEqual(asks(text, word), expected)
        self.assertEqual(len(cn._QUESTION_ENDINGS), 15)
        self.assertTrue(all(len(ending) == 2 for ending in cn._QUESTION_ENDINGS))

    def test_negation_is_read_as_before_across_a_space(self):
        self.assertEqual(stage("피로를 즉시 줄이지 않는 법"), MARK)
        self.assertEqual(cn.health_signals(["피로를 즉시 줄이지 않는 법"]).counted_assert(), ())


class InstantPhraseTest(unittest.TestCase):                                                                              # Y7
    EFFECT_AND_ACTION = (("피로를 {w} 줄이는 방법", "피로 기록을 {w} 정리하는 앱"), ("통증을 {w} 없애는 방법", "통증 일지를 {w} 확인하는 방법"), ("불면을 {w} 해소하는 루틴", "불면 일기를 {w} 저장하는 습관"),
                         ("두통을 {w} 해결하는 법", "두통 기록을 {w} 메모하는 법"), ("스트레스를 {w} 풀어주는 방법", "스트레스 점검표를 {w} 작성하는 법"), ("요통을 {w} 개선하는 운동", "요통 운동 영상을 {w} 검색하는 방법"))
    ORDINARY = ("당뇨 예방 식단 한 번에 정리하기", "당뇨 예방 식단 하루 만에 정리하기", "당뇨 예방 식단 단번에 정리하기", "당뇨 예방 식단 한꺼번에 정리하기", "고혈압 식단 일지를 하루 만에 정리하는 법", "영양제 한 번에 몇 알 먹나요",
                "영양제 한꺼번에 먹어도 될까", "영양제 하루 만에 도착하는 배송 업체 비교", "영양제 한 번에 주문하는 방법", "영양제 단번에 비교하기", "수술 후 하루 만에 퇴원하는 방법")

    def test_the_tables_are_the_documented_initial_values(self):
        self.assertEqual(cn.HEALTH_INSTANT_PHRASE_KO, INSTANT)
        self.assertFalse(hasattr(cn, "HEALTH_INSTANT_UNKNOWN_KO"), "D-299: 꾸밈을 모를 때 제품 곁에서 세던 규칙은 없어졌다 — 쇼핑 문장이 중지가 됐다")
        self.assertNotIn("HEALTH_INSTANT_UNKNOWN_KO", cn.__all__)
        self.assertEqual(len(set(cn.HEALTH_INSTANT_PHRASE_KO)), 4)
        self.assertNotIn("곧바로", cn.HEALTH_INSTANT_PHRASE_KO, "`곧바로` 는 `바로` 가 낱말 속에서 이미 읽는다")
        self.assertEqual(stage("피로를 곧바로 줄이는 방법"), STOP)
        self.assertEqual(cn.health_signals(["피로를 곧바로 줄이는 방법"]).scoped, (("바로", "soft", "effect"),))

    def test_they_are_not_in_the_old_stop_floor_tables(self):
        for word in INSTANT:
            self.assertNotIn(word, cn.HEALTH_ASSERT_SOFT_KO, "옛 중지 바닥의 바탕 표에는 옛 코드의 낱말만 있다")
            self.assertNotIn(word, cn.ASSERT_SCOPED_KO["soft"], "옛 코드의 범위 낱말 표도 그대로다")
        self.assertEqual(cn.ASSERT_SCOPED_KO["soft"], ("즉시", "즉각", "바로", "단숨에", "순식간", "당장"))
        self.assertEqual(cn.HEALTH_ASSERT_SOFT_KO, ("즉시", "즉각", "바로", "단숨에", "순식간", "당장", "즉효"))
        for text in ("영양제 한 번에 몇 알 먹나요", "당뇨 예방 식단 한 번에 정리하기", "피로를 하루 만에 해결하는 영양제", "영양제 먹고 하루 만에 살 빠지는 법", "하루 만에 당뇨 극복"):
            with self.subTest(text=text):
                signals = cn.health_signals([text])
                self.assertEqual(signals.assert_soft, ())
                self.assertEqual(signals.floor_key(), signals.legacy_concept_key())
                self.assertNotIn(signals.floor_key(), sf.LEGACY_STOP_KEYS, "옛 코드는 이 글을 중지로 읽지 않았다 — 새 열쇠가 읽는다")

    def test_an_instant_phrase_that_modifies_an_effect_result_stops_and_one_that_modifies_an_action_does_not(self):
        for word in INSTANT:
            for result, action in self.EFFECT_AND_ACTION:
                with self.subTest(word=word, result=result):
                    self.assertEqual(stage(result.format(w=word)), STOP)
                    self.assertEqual(stage(action.format(w=word)), MARK)
        self.assertEqual(stage("피로를 한 번에 해결하는 영양제"), STOP)

    def test_an_ordinary_sentence_with_an_instant_phrase_is_not_stopped_even_beside_a_disease_or_a_product(self):
        for text in self.ORDINARY:
            with self.subTest(text=text):
                self.assertNotEqual(stage(text), STOP)

    def test_an_effect_word_right_after_an_instant_phrase_is_read_as_its_result_beside_a_disease_or_a_product(self):
        # 서술어를 못 읽어도(`당뇨 극복` 은 서술어 꼴이 아니다) 효과 낱말이 즉각 표현 바로 뒤 세 낱말 안에 있고 질환·제품이 대상이면 효과 결과를 꾸미는 것이다(D-293)
        for text, phrase in (("하루 만에 당뇨 극복", "하루 만에"), ("단번에 당뇨 극복", "단번에"), ("한 번에 당뇨 극복", "한 번에"), ("한꺼번에 당뇨 극복", "한꺼번에"), ("하루 만에 비염 극복", "하루 만에"), ("비염 하루 만에 극복", "하루 만에"),
                             ("비타민 하루 만에 극복", "하루 만에"), ("하루 만에 혈압 낮추기", "하루 만에"),
                             ("하루 만에 불면 극복", "하루 만에"), ("단번에 피로 해소", "단번에")):          # 의도적 갱신(D-299): 대상이 증상뿐이어도 효과 결과 명사가 글 끝에 오면 읽는다(독립 검증 P-4)
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)
                self.assertEqual(cn.health_signals([text]).scoped, ((phrase, "soft", "effect"),))
        # 효과 낱말이 앞에 있거나(`예방 식단`) 세 낱말 밖이거나 효과 결과 명사 뒤에 다른 낱말이 더 이어지면(`해소 여행 코스`) 읽지 않는다 — 일상 문장이 중지가 되지 않게
        for text, expected in (("당뇨 예방 식단 하루 만에 완성", EVIDENCE), ("당뇨 예방 식단 하루 만에 완성하기", EVIDENCE), ("고혈압 예방 운동 단번에 이해하기", EVIDENCE), ("하루 만에 당뇨 환자 식단 짜기 극복", EVIDENCE),
                               ("스트레스 해소 여행 코스 하루 만에 다녀오기", MARK), ("하루 만에 스트레스 해소 여행 코스", MARK)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)
                self.assertEqual(cn.health_signals([text]).counted_assert(), ())

    def test_the_helper_finds_the_first_effect_word_inside_three_words_after_the_phrase(self):
        def later(text, phrase):
            joined, starts = cn.compact_marked([cn.fold(text)])
            end = joined.index(cn.compact(cn.fold(phrase))) + len(cn.compact(cn.fold(phrase)))
            return cn._effect_within(joined, starts, end), end
        found, end = later("하루 만에 당뇨 극복", "하루 만에")
        self.assertEqual(found, end + len("당뇨극복"))
        self.assertIsNone(later("당뇨 예방 식단 하루 만에 완성", "하루 만에")[0], "효과 낱말이 앞에 있다")
        self.assertIsNone(later("하루 만에 당뇨 환자 식단 짜기 극복", "하루 만에")[0], "효과 낱말이 다섯째 낱말이다 — 세 낱말을 넘는다")
        self.assertIsNotNone(later("하루 만에 당뇨 환자 극복", "하루 만에")[0], "셋째 낱말까지는 읽는다")
        self.assertIsNone(later("하루 만에", "하루 만에")[0])
        spans = cn._object_spans(*cn.compact_marked([cn.fold("하루 만에 불면 극복")]))
        self.assertEqual(spans, [], "증상만 있으면 대상으로 읽지 않는다")
        self.assertNotEqual(cn._object_spans(*cn.compact_marked([cn.fold("하루 만에 당뇨 극복")])), [])
        self.assertNotEqual(cn._object_spans(*cn.compact_marked([cn.fold("하루 만에 비타민 극복")])), [])

    def test_the_supplementary_reading_takes_the_nearest_effect_word_and_never_one_that_straddles_two_words(self):
        # 가장 가까운 효과 낱말이 끝나는 자리까지만 대상 창을 본다 — 대상(`당뇨`)이 그 뒤에 있으면 더 먼 효과 낱말(`개선`)이 있어도 읽지 않는다(검증자의 변이 V09)
        self.assertEqual(stage("하루 만에 극복 당뇨 개선"), EVIDENCE)
        self.assertEqual(cn.health_signals(["하루 만에 극복 당뇨 개선"]).scoped, (("하루 만에", "soft", "none"),))
        self.assertEqual(stage("하루 만에 당뇨 극복 개선"), STOP)
        # 낱말 두 개에 걸쳐 우연히 이어 붙은 효과 낱말(`지도 움직임` 의 ‘도움’)은 읽지 않는다(검증자의 변이 V10)
        self.assertEqual(stage("하루 만에 당뇨 지도 움직임 기록"), EVIDENCE)
        self.assertEqual(cn.health_signals(["하루 만에 당뇨 지도 움직임 기록"]).scoped, (("하루 만에", "soft", "none"),))
        self.assertEqual(stage("하루 만에 당뇨 식단 도움 되는 방법"), STOP, "낱말 안에서 찾으면 읽는다")

    def test_a_negation_a_question_and_a_warning_word_switch_the_phrases_off_like_the_old_ones(self):
        for text in ("피로를 한 번에 해결하지 않는 법", "피로를 하루 만에 해결할까", "피로를 단번에 줄이는지 알아보기", "피로를 하루 만에 해결한다는 광고에 속지 않는 법", "통증을 단번에 없애는 방법은 사기일까"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), MARK)
                self.assertEqual(cn.health_signals([text]).counted_assert(), ())

    def test_the_phrase_after_another_instant_word_is_read_through_the_connector_skip(self):
        for text in ("피로를 바로 한 번에 줄이는 방법", "피로를 즉시 한꺼번에 해소하는 방법", "통증을 즉시 한 번에 없애는 방법"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)
        # 알려진 한계(D-296): 띄어쓴 `한 번에`·`하루 만에` 는 두 낱말이라 그 뒤에 또 다른 즉각 낱말이 오면(`통증을 한 번에 즉시 없애는 방법`) 앞 두 낱말 대상 창에서 건강 낱말이 밀려난다 — 거꾸로(`즉시 한 번에`)는 읽는다
        self.assertEqual(stage("통증을 한 번에 즉시 없애는 방법"), MARK)


class QuitMedicineTest(unittest.TestCase):                                                                               # Y8
    # 옛(기준 커밋) 단계를 미리 계산해 박았다 — 이 묶음이 바꾸지 않은 판정
    AS_BEFORE = (("항생제 끊어도 되나요", EVIDENCE), ("혈압약 끊어도 되는 시기", EVIDENCE), ("혈압약 끊어도 되는지 알아보기", EVIDENCE), ("혈압약 끊어도 되는 기준", EVIDENCE), ("당뇨약 끊어도 되는 이유", EVIDENCE),
                 ("수면제 없이 잠드는 방법", MARK), ("수면제 끊는 방법", MARK), ("수면제 안 먹고 잠드는 방법", MARK), ("수면제 중단 후 수면 습관 정리", EVIDENCE), ("혈압약 끊어도 되는 법적 근거", EVIDENCE), ("수면제 먹어도 될까", EVIDENCE),
                 ("처방약 복용 중 비타민 먹어도 될까", STOP), ("해열제 먹어도 괜찮을까", EVIDENCE), ("영양제 안 먹고 낫는 방법", EVIDENCE), ("비타민 끊고 낫는 방법", EVIDENCE), ("한약 끊어도 되는 방법", EVIDENCE),
                 ("당뇨약 안 먹고 낫는다는 광고에 속지 않는 법", EVIDENCE), ("수면제 바로 알기", MARK), ("인슐린 보관 방법 정리", MARK), ("스테로이드 연고 구매 영수증", MARK))

    def test_the_tables_are_the_documented_initial_values(self):
        self.assertEqual(cn.HEALTH_QUIT_KO, tuple(entry for entry, _text in QUIT_SENTENCES))
        self.assertEqual(cn.HEALTH_QUIT_ALLOW_KO, ("끊어도", "안 먹어도", "먹지 않아도", "중단해도", "복용하지 않아도"))
        self.assertEqual(cn.HEALTH_QUIT_HOWTO_KO, ("방법", "비법", "비결", "노하우", "요령", "법"))
        self.assertTrue(set(cn.HEALTH_QUIT_ALLOW_KO) <= set(cn.HEALTH_QUIT_KO))
        self.assertEqual((len(cn.HEALTH_QUIT_KO), len(cn.HEALTH_QUIT_ALLOW_KO), len(cn.HEALTH_QUIT_HOWTO_KO)), (13, 5, 6))

    def test_each_stop_phrase_beside_a_medicine_and_a_cure_word_stops(self):
        for entry, text in QUIT_SENTENCES:
            with self.subTest(entry=entry):
                signals = cn.health_signals([text])
                self.assertEqual(signals.quit, (entry,))
                self.assertEqual((stage(text), codes(text)), (STOP, ["HEALTH_STOP"]))
                self.assertEqual(cn.health_signals([text.replace(entry, "복용 중")]).quit, (), "같은 글에서 그 표현만 빼면 해당 없다")

    def test_the_permission_form_with_a_how_to_word_stops_for_every_allowed_stop_phrase_and_every_how_to_word(self):
        for allowed, howto in itertools.product(cn.HEALTH_QUIT_ALLOW_KO, cn.HEALTH_QUIT_HOWTO_KO):
            text = f"고혈압약 {allowed} 되는 {howto}"
            with self.subTest(text=text):
                self.assertEqual(cn.health_signals([text]).quit, (allowed,))
                self.assertEqual(stage(text), STOP)
        for text in ("혈압약 끊어도 되는 방법은", "혈압약 끊어도 되는 방법을 알려드려요", "혈압약 끊어도 되는 방법 총정리", "혈압약 끊어도 되는법", "혈압약 끊어도 되는 법", "수면제 중단해도 되는 노하우"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)

    def test_a_question_a_timing_an_absence_and_a_plain_how_to_stop_are_as_before(self):
        for text, expected in self.AS_BEFORE:
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)

    def test_only_a_prescription_word_triggers_it_and_a_warning_word_switches_it_off(self):
        for text in ("영양제 안 먹고 낫는 방법", "비타민 끊고 낫는 방법", "한약 끊어도 되는 방법"):
            with self.subTest(text=text):
                self.assertEqual(cn.health_signals([text]).quit, ())
        signals = cn.health_signals(["당뇨약 안 먹고 낫는다는 광고에 속지 않는 법"])
        self.assertEqual(signals.quit, ("안 먹고",))
        self.assertEqual(signals.counted_assert(), (), "경고 낱말이 있으면 아무것도 세지 않는다(옛 규칙 그대로)")

    def test_the_card_names_the_stop_phrase_and_nothing_hidden(self):
        finding = report_of("당뇨약 안 먹고 낫는 방법").findings[0]
        self.assertEqual(finding.code, "HEALTH_STOP")
        self.assertEqual((finding.matched[-1], finding.groups[-1]), ("안 먹고", "단정·보장"))
        finding = report_of("고혈압약 끊어도 되는 방법").findings[0]
        self.assertEqual((finding.matched[-1], finding.groups[-1]), ("끊어도", "단정·보장"))


class NoticeAndShapeTest(unittest.TestCase):                                                                             # Y9
    def test_the_card_of_every_new_stop_has_no_leak_and_the_same_four_health_codes(self):
        for text, _cause in MISSED_TEN:
            with self.subTest(text=text):
                report = report_of(text)
                notices = nt.from_report(report)
                self.assertEqual(nt.leaks(nt.cards(notices)), ())
                self.assertEqual(nt.leaks(chr(10).join(sf.notes(report))), ())
                self.assertEqual([finding.code for finding in report.findings if finding.flag == "health_check"], ["HEALTH_STOP"])
        self.assertEqual(len(nt.CODES), 30)

    def test_the_signal_record_keeps_its_old_fields_and_only_gained_quit_stopping_and_resolve(self):
        self.assertEqual(cn.HealthSignals._fields[:10], ("symptom", "disease", "effect", "medical", "product", "assert_strong", "assert_effect", "assert_soft", "warned", "inside"))
        self.assertEqual(cn.HealthSignals._fields[-3:], ("quit", "stopping", "resolve"))
        plain = cn.health_signals(["일반 업무 정리"])
        self.assertEqual((plain.quit, plain.stopping, plain.resolve, plain.scoped, plain.counted_assert()), ((), (), (), (), ()))

    def test_the_new_names_are_exported_and_the_matrix_is_untouched(self):
        for name in ("HEALTH_INSTANT_PHRASE_KO", "HEALTH_QUIT_KO", "HEALTH_QUIT_ALLOW_KO", "HEALTH_QUIT_HOWTO_KO", "BARE_SYMPTOM_REST_KO", "HEALTH_BARE_TAIL_KO", "HEALTH_HALT_SCOPE_KO", "HEALTH_INSTANT_ACTION_KO", "HEALTH_INSTANT_MORE_KO",
                     "HEALTH_INSTANT_NUMBERED_KO", "HEALTH_MASKS_WORD_KO", "HEALTH_QUIT_CURE_KO", "HEALTH_QUIT_OK_KO", "HEALTH_RESOLVE_KO", "HEALTH_SYMPTOM_BARE_KO", "HEALTH_SYMPTOM_PREFIX_KO", "HEALTH_SYMPTOM_START_KO", "HEALTH_QUIT_OUTCOME_KO", "HEALTH_MEDICINE_GENERIC_KO"):
            self.assertIn(name, cn.__all__)
        self.assertNotIn("HEALTH_SYMPTOM_COMPOUND_KO", cn.__all__, "D-309: 허용 합성어 목록은 수식어 표가 갈음했다")
        self.assertTrue(all(hasattr(cn, name) for name in cn.__all__))
        self.assertEqual(len(sf.HEALTH_MATRIX), 64)
        self.assertEqual(sf.LEGACY_STOP_KEYS, frozenset(key for key, value in hc.OLD_MATRIX.items() if value == STOP))

    def test_the_same_input_gives_the_same_answer_whatever_the_order_of_the_other_texts(self):
        texts = [text for text, _cause in MISSED_TEN] + ["감기 예방 식단", "머리 감기 순서"]
        first = [stage(text) for text in texts]
        self.assertEqual([stage(text) for text in reversed(texts)][::-1], first)
        self.assertEqual([stage(text) for text in texts], first)

    def test_english_and_other_flags_are_untouched(self):
        for text, expected in (("diabetes diet notes", EVIDENCE), ("diabetes guaranteed", STOP), ("supplements immediately", STOP), ("sleep tips for beginners", MARK), ("Cure diabetes 100% guaranteed", STOP), ("password manager guide", GENERAL)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)
        self.assertEqual(sf.check_text(["협찬받아 작성한 영양제 후기"]).flags, ("health_check", "sponsor_disclosure"), "기준 커밋과 같다 — 다른 표시는 이 묶음이 만지지 않았다")


# ==== 수정 라운드(독립 검증 ver_wpb5 의 지적 — D-298–D-306) ==========================================================================================================
SYMPTOMS_40 = ("가려움", "감기", "거북목", "건조한 눈", "근육통", "기억력", "기침", "눈 건강", "더부룩", "두통", "몸살", "무기력", "변비", "부종", "불면", "불안", "붓기", "생리통", "설사", "소화불량", "속쓰림", "수면", "숙면", "스트레스", "시력",
               "안구건조", "어깨 결림", "어지럼", "여드름", "요통", "이명", "입냄새", "저림", "집중력", "체중", "컨디션", "코골이", "통증", "피로", "활력")        # 40 — 검증자의 P-1 재현 격자
ALWAYS_WORDS = ("100%", "백퍼센트", "틀림없이", "장담하는", "보증하는")                                                                                        # 늘 단정 낱말 다섯(검증자의 격자)
RISK_TABLE = ("체감기온", "체감기후", "체감기온표", "실감기", "줄감기", "태엽감기", "호스감기", "테이프감기", "붕대감기", "케이블감기", "이어폰줄감기", "냉감기능", "냉감기능성 원단", "온감기능", "경감기준", "절감기술", "시설사용료", "시설사업",
           "신설사업", "증설사업", "제설사업", "가설사무소", "건설사업", "건설사고", "수요통계", "수요통제", "수요통신", "수요통합", "필요통신비", "중요통지서", "중요통계", "중요통화", "주요통신사", "주요통계", "주요통화", "이명희", "이명수",
           "이명훈", "몸살림", "첫눈에 건강", "눈에 건강", "건조한 눈빛", "건조한 눈길", "건조한 눈매", "경기침체기", "경기침체 대비", "설사 비가 와도", "설사 그렇다 해도", "설사 실패해도", "장기침체", "장기침수")        # 51 — 검증자의 P-7 위험표 49개(합성어·구절)와 요청서가 따로 든 `장기침체`·`장기침수`
RISK_FRAMES = ("{w}", "{w} 정리하는 방법", "{w} 바로 줄이는 방법", "{w} 즉시 낮추는 방법", "{w} 하루 만에 해결하는 방법")
RISK_KEPT = {"몸살림": MARK, "눈에 건강": MARK, "설사 비가 와도": MARK, "설사 그렇다 해도": MARK, "설사 실패해도": MARK}                                                   # 건강 뜻이 될 수 있거나(몸살림 운동·눈에 건강한) 알려진 한계(`설사` 부사 — D-306)라 일반이 아닌 것 5개
START_WORDS = ("감기", "설사", "요통", "기침", "복통", "치통", "습진", "무좀")
COMPOUNDS = ("목감기", "코감기", "여름감기", "겨울감기", "환절기감기", "아기감기", "아이감기", "배탈설사", "급성설사", "만성설사", "여행자설사", "아기설사", "유아설사", "급성요통", "만성요통", "산후요통", "임신요통",
             "마른기침", "잔기침", "밤기침", "만성기침", "급성기침", "가래기침", "급성복통", "만성복통")        # 25 — 2차 수정 머리의 허용 합성어 목록(D-303) — D-309 가 수식어 표로 갈음했고 이 낱말들은 모두 그대로 읽힌다
START_ENTRIES = START_WORDS + ("눈 건강",)                                                                                                                  # 9 (D-307: 두 낱말 항목 `눈 건강` 은 낱말 처음에서만 읽는다)
GENUINE_COMPOUNDS = (
    "열감기", "봄감기", "가을감기", "늦감기", "잔감기", "속감기", "위장감기", "초기감기", "만성감기", "급성감기", "심한감기", "독한감기", "잦은감기", "유아감기", "성인감기", "노인감기", "바이러스감기", "장염감기", "임산부감기", "어린이감기",
    "물설사", "묽은설사", "심한설사", "잦은설사", "아이설사", "어린이설사", "노인설사", "장염설사", "식중독설사", "항생제설사", "과민성설사", "스트레스설사", "우유설사", "새벽설사", "아침설사", "식후설사", "소아설사", "감염성설사", "바이러스설사",
    "심한요통", "디스크요통", "허리요통", "근막요통", "기능성요통", "운동후요통", "아침요통", "새벽요통", "척추요통", "노인요통", "임산부요통", "만성적요통",
    "심한기침", "잦은기침", "독한기침", "새벽기침", "아침기침", "야간기침", "알레르기기침", "천식기침", "아이기침", "아기기침", "소아기침", "노인기침", "지속기침", "바이러스기침", "목기침", "역류성기침",
    "심한복통", "식후복통", "아랫배복통", "윗배복통", "위장복통", "생리복통", "소아복통", "아이복통", "아기복통", "장염복통", "변비복통", "경련성복통",
    "심한치통", "급성치통", "만성치통", "어금니치통", "사랑니치통", "충치치통", "잇몸치통", "야간치통", "신경치통", "아이치통",
    "주부습진", "손습진", "발습진", "접촉성습진", "한포진습진", "지루성습진", "아토피습진", "건성습진", "화폐상습진", "땀띠습진", "기저귀습진", "아기습진", "소아습진", "만성습진", "급성습진", "발바닥습진", "손바닥습진",
    "발무좀", "손무좀", "발톱무좀", "사타구니무좀", "머리무좀", "심한무좀", "만성무좀", "물집무좀", "각질무좀", "아이무좀",
    "이명증", "이명증상", "만성이명", "급성이명", "이석이명", "소아이명", "이명현상", "이명소리", "이명치료", "이명소음", "이명치료법", "이명개선", "이명완화", "이명극복", "이명원인", "이명해결")        # 132 — 독립 재검증이 허용 목록 밖의 진짜 합성어로 만든 낱말(D3 — 3차 수정 전에는 396문장 가운데 중지가 45개뿐이었다)
LOOKALIKE_WORDS = (
    "체감기온", "체감기후", "체감기온차", "냉감기능", "경감기준", "절감기술", "절감기법", "실감기", "줄감기", "태엽감기", "붕대감기", "케이블감기", "이어폰줄감기", "낚싯줄감기", "휘감기", "되감기", "빨리감기", "리본감기", "테이프감기", "호스감기",
    "시설사용료", "시설사업", "신설사업", "증설사업", "제설사업", "가설사무소", "건설사업", "증설사", "개설사", "창설사", "수요통계", "수요통제", "중요통지서", "중요통화", "주요통신사", "필요통신비", "중요통지", "장기침체", "장기침수", "경기침체",
    "정치통계", "가치통계", "행정치통계", "실습진행", "학습진도", "복습진도", "연습진행", "업무좀", "이명희", "이명수", "이명박", "이명훈", "이명진", "경기침수", "가감기", "체감기", "손목감기", "발목감기", "팔목감기", "코코감기")        # 60 — 읽으면 안 되는 일상 낱말(위험표의 합성어·검증자 F2n·F2h 와 이번 라운드에 더한 것)
CROSS_WORD = ("설 사진", "설 사과", "설 사골", "설 사업", "설 사전 예약", "설 사랑", "설 사용 후기", "설 사무실", "설 사실", "설 사이트", "설 사회", "설 사람", "설 사고", "설 사정", "설 사탕", "설 사기", "설 사다리", "설 사자", "설 사슴", "설 사진관",
              "감 기르는 법", "감 기능", "감 기사", "감 기록", "감 기분", "감 기술", "요 통계", "요 통신", "요 통지서", "요 통화", "기 침체", "기 침수", "기 침대", "무 좀 더 알아보기", "무 좀비 영화", "이 명", "이 명단", "이 명언", "복 통계", "치 통계")        # 40 — 낱말 경계를 가로질러 우연히 증상 낱말이 되는 글(D2)
VERIFIER_CROSS_154 = (
    "설 사과 선물세트 추천", "설 사과 바로 올리는 방법", "설 사과 정리", "설 사과 즉시 줄이는 방법", "설 사과 하루 만에 끝내는 법", "설 사진 선물세트 추천",
    "설 사진 바로 올리는 방법", "설 사진 정리", "설 사진 즉시 줄이는 방법", "설 사진 하루 만에 끝내는 법", "설 사전 예약 선물세트 추천", "설 사전 예약 바로 올리는 방법",
    "설 사전 예약 정리", "설 사전 예약 즉시 줄이는 방법", "설 사전 예약 하루 만에 끝내는 법", "설 사골 선물세트 추천", "설 사골 바로 올리는 방법", "설 사골 정리",
    "설 사골 즉시 줄이는 방법", "설 사골 하루 만에 끝내는 법", "설 사탕 선물세트 추천", "설 사탕 바로 올리는 방법", "설 사탕 정리", "설 사탕 즉시 줄이는 방법",
    "설 사탕 하루 만에 끝내는 법", "설 사업 선물세트 추천", "설 사업 바로 올리는 방법", "설 사업 정리", "설 사업 즉시 줄이는 방법", "설 사업 하루 만에 끝내는 법",
    "설 사용 후기 선물세트 추천", "설 사용 후기 바로 올리는 방법", "설 사용 후기 정리", "설 사용 후기 즉시 줄이는 방법", "설 사용 후기 하루 만에 끝내는 법", "설 사이트 선물세트 추천",
    "설 사이트 바로 올리는 방법", "설 사이트 정리", "설 사이트 즉시 줄이는 방법", "설 사이트 하루 만에 끝내는 법", "설 사연 선물세트 추천", "설 사연 바로 올리는 방법",
    "설 사연 정리", "설 사연 즉시 줄이는 방법", "설 사연 하루 만에 끝내는 법", "설 사람 선물세트 추천", "설 사람 바로 올리는 방법", "설 사람 정리",
    "설 사람 즉시 줄이는 방법", "설 사람 하루 만에 끝내는 법", "설 사고 예방 선물세트 추천", "설 사고 예방 바로 올리는 방법", "설 사고 예방 정리", "설 사고 예방 즉시 줄이는 방법",
    "설 사고 예방 하루 만에 끝내는 법", "설 사실 선물세트 추천", "설 사실 바로 올리는 방법", "설 사실 정리", "설 사실 즉시 줄이는 방법", "설 사실 하루 만에 끝내는 법",
    "설 사회 선물세트 추천", "설 사회 바로 올리는 방법", "설 사회 정리", "설 사회 즉시 줄이는 방법", "설 사회 하루 만에 끝내는 법", "설 사이즈 선물세트 추천",
    "설 사이즈 바로 올리는 방법", "설 사이즈 정리", "설 사이즈 즉시 줄이는 방법", "설 사이즈 하루 만에 끝내는 법", "설 사다리 선물세트 추천", "설 사다리 바로 올리는 방법",
    "설 사다리 정리", "설 사다리 즉시 줄이는 방법", "설 사다리 하루 만에 끝내는 법", "설 사랑 문구 선물세트 추천", "설 사랑 문구 바로 올리는 방법", "설 사랑 문구 정리",
    "설 사랑 문구 즉시 줄이는 방법", "설 사랑 문구 하루 만에 끝내는 법", "설 사찰 선물세트 추천", "설 사찰 바로 올리는 방법", "설 사찰 정리", "설 사찰 즉시 줄이는 방법",
    "설 사찰 하루 만에 끝내는 법", "설 사슴 선물세트 추천", "설 사슴 바로 올리는 방법", "설 사슴 정리", "설 사슴 즉시 줄이는 방법", "설 사슴 하루 만에 끝내는 법",
    "설 사무실 선물세트 추천", "설 사무실 바로 올리는 방법", "설 사무실 정리", "설 사무실 즉시 줄이는 방법", "설 사무실 하루 만에 끝내는 법", "설 사직서 선물세트 추천",
    "설 사직서 바로 올리는 방법", "설 사직서 정리", "설 사직서 즉시 줄이는 방법", "설 사직서 하루 만에 끝내는 법", "감 기르는 법", "감 기르는 법 바로 익히는 방법",
    "감 기르는 법 하루 만에 끝내기", "감 기능성 소재", "감 기능성 소재 바로 익히는 방법", "감 기능성 소재 하루 만에 끝내기", "감 기본 상식", "감 기본 상식 바로 익히는 방법",
    "감 기본 상식 하루 만에 끝내기", "감 기분 좋은 하루", "감 기분 좋은 하루 바로 익히는 방법", "감 기분 좋은 하루 하루 만에 끝내기", "감 기준 정리", "감 기준 정리 바로 익히는 방법",
    "감 기준 정리 하루 만에 끝내기", "감 기초 원예", "감 기초 원예 바로 익히는 방법", "감 기초 원예 하루 만에 끝내기", "감 기부 방법", "감 기부 방법 바로 익히는 방법",
    "감 기부 방법 하루 만에 끝내기", "감 기억 남는 여행", "감 기억 남는 여행 바로 익히는 방법", "감 기억 남는 여행 하루 만에 끝내기", "감 기술 소개", "감 기술 소개 바로 익히는 방법",
    "감 기술 소개 하루 만에 끝내기", "감 기간 확인", "감 기간 확인 바로 익히는 방법", "감 기간 확인 하루 만에 끝내기", "요 통계 보는 법", "요 통계 보는 법 바로 줄이는 방법",
    "요 통신 요금", "요 통신 요금 바로 줄이는 방법", "요 통장 만들기", "요 통장 만들기 바로 줄이는 방법", "요 통화 기록", "요 통화 기록 바로 줄이는 방법",
    "요 통제 방법", "요 통제 방법 바로 줄이는 방법", "무 좀 더 활용하는 요리", "무 좀 더 활용하는 요리 바로 만드는 법", "무 좀 더 넣은 국", "무 좀 더 넣은 국 바로 만드는 법",
    "무 좀 사다 주세요", "무 좀 사다 주세요 바로 만드는 법", "기 침체 극복", "기 침체 극복 바로 줄이는 방법", "기 침대 고르기", "기 침대 고르기 바로 줄이는 방법",
    "기 침구 세탁", "기 침구 세탁 바로 줄이는 방법", "기 침체기 대비", "기 침체기 대비 바로 줄이는 방법",
)        # 154 — 독립 재검증의 낱말 가로지름 문장(설 + 사… 20낱말 × 틀 5, 감·요·기·무 포함): 기준은 모두 일반, 2차 수정 머리는 표시만 106·중지 48
MASK_SYMPTOMS = ("두통", "피로", "통증")
MASK_ASSERTS = ("즉시", "바로", "하루 만에", "단번에")
MASK_VERBS = ("없애는 방법", "줄여줍니다", "회복하는 식단")
INHERITED_CUT_MASKS = ("소화기", "소화전", "혈압계", "체중계", "처방전", "자세히", "자세한", "자세하게", "불확실", "완전판", "보장성", "보장금", "보증금", "보증서", "보증보험", "피로도", "불안정", "바로잡", "바로가기", "바로미터", "불완전",
                       "모니터암", "로봇암", "암거치대")        # 24 — 기준(main)에 이미 있던 한 낱말 마스크 — 같은 장치로 글을 갈라 `증상 + 마스크 + 즉시` 를 낮춘다. 기준과 같고 이 묶음이 바꾸지 않았다(D-306 의 알려진 한계)
RANK = {GENERAL: 0, MARK: 1, EVIDENCE: 2, STOP: 3}
EVIDENCE_COMPOUNDS = ("장염감기", "장염설사", "항생제설사", "과민성설사", "알레르기기침", "천식기침", "역류성기침", "장염복통", "아토피습진", "이명치료", "이명치료법")        # 11 — 수식어·뒷말 자체가 질환·제품·의료 낱말이라 단독으로도 근거 확인 필요(B)


def obj(word):
    """받침이 있으면 `을`, 없으면 `를` 을 붙인다."""
    return word + ("을" if (ord(word[-1]) - 0xAC00) % 28 else "를")


class ResolveFamilyTest(unittest.TestCase):                                                                              # Z1 (D-298, 독립 검증 P-1)
    NOUNS = ("해결", "치유", "호전", "제거", "퇴치", "차단", "정복")
    STEMS = ("잡아주는", "잡아준다", "잡아줍니다", "잡아줘요", "막아주는", "막아준다", "막아줍니다", "막아줘요")

    def test_the_table_is_the_documented_initial_value_and_the_effect_table_is_untouched(self):
        self.assertEqual(cn.HEALTH_RESOLVE_KO, ("해결", "치유", "호전", "제거", "퇴치", "차단", "정복", "잡아주", "잡아준", "잡아줍", "잡아줘", "막아주", "막아준", "막아줍", "막아줘"))
        self.assertEqual(len(cn.HEALTH_RESOLVE_KO), 15)
        for word in cn.HEALTH_RESOLVE_KO:
            self.assertNotIn(word, cn.HEALTH_EFFECT_KO, "효과 낱말 표에 넣으면 `영양제 오류 해결`·`체중 앱 오류 해결` 같은 평범한 글이 올라간다")
        self.assertEqual(len(cn.HEALTH_EFFECT_KO), 34)

    def test_the_verifier_grid_of_eight_hundred_sentences_all_stop(self):
        # {증상 40}을 {늘 단정 낱말 5} {해결하는·잡아주는·치유하는·정복하는} 방법 — 고치기 전에는 800개 모두 표시만이었다(같은 틀의 `없애는`·`줄이는` 은 400개 모두 중지)
        texts = [f"{obj(symptom)} {always} {verb} 방법" for symptom in SYMPTOMS_40 for always in ALWAYS_WORDS for verb in ("해결하는", "잡아주는", "치유하는", "정복하는")]
        self.assertEqual(len(texts), 800)
        self.assertEqual([text for text in texts if stage(text) != STOP], [])
        controls = [f"{obj(symptom)} {always} {verb} 방법" for symptom in SYMPTOMS_40 for always in ALWAYS_WORDS for verb in ("없애는", "줄이는")]
        self.assertEqual([text for text in controls if stage(text) != STOP], [], "같은 틀의 옛 효과 동사 400개는 그대로 중지다")

    def test_the_brief_sentences_stop(self):
        for text in ("요통 100% 해결", "통증 100% 해결하는 방법", "통증 100% 치유", "요통 100% 제거", "기침을 틀림없이 잡아주는 가이드", "불면 100% 퇴치", "염증 100% 차단", "감기 틀림없이 호전", "당뇨 100% 해결", "다이어트 100% 정복 가이드",
                     "요통 해결 100% 보장", "비타민 100% 해결", "두통을 보증하는 해결하는 방법", "통증을 장담하는 정복하는 방법"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)
                signals = cn.health_signals([text])
                self.assertTrue(signals.resolve or signals.counted("effect") or signals.assert_effect, "효과로 읽은 말이 있다")

    def test_every_noun_and_stem_stops_beside_a_symptom_and_every_always_word(self):
        for always in ALWAYS_WORDS:
            for word in self.NOUNS + self.STEMS:
                text = f"통증 {always} {word}"
                with self.subTest(text=text):
                    self.assertEqual(stage(text), STOP)
                    self.assertTrue(cn.health_signals([text]).resolve, "읽은 결과 서술어가 신호에 실린다")

    def test_the_contrast_sentences_the_brief_names_behave_as_expected(self):
        for text, expected in (("체중 앱 오류 100% 해결", MARK), ("서버 오류 100% 해결", GENERAL), ("요통 100% 해결 보장", STOP), ("영양제 오류 해결", MARK), ("통증 해결 방법", MARK), ("앱 오류 해결 보장", GENERAL), ("토익 100% 정복", GENERAL),
                               ("광고 100% 차단 앱", GENERAL), ("다이어트 앱 오류 100% 해결", MARK), ("수면 소음 100% 차단", MARK)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)
        for text in ("체중 앱 오류 100% 해결", "서버 오류 100% 해결", "통증 해결 방법", "영양제 오류 해결"):
            self.assertEqual(cn.health_signals([text]).resolve, (), text)

    def test_it_needs_an_always_assertion_word_in_the_same_text_not_a_scoped_one(self):
        # `확실히`·`즉시` 같은 범위 낱말은 효과 서술어를 꾸밀 때만 센다 — 그쪽은 결과 서술어 표(`해결하` …)와 글 끝 결과 명사가 읽는다. 이 규칙은 늘 단정 낱말 곁에서만 켜진다
        for text in ("요통 해결하는 방법", "요통 치유 후기", "통증 제거 방법", "불면 퇴치 앱"):
            with self.subTest(text=text):
                self.assertEqual(cn.health_signals([text]).resolve, ())
                self.assertEqual(stage(text), MARK)
        self.assertEqual(cn.health_signals(["요통 확실히 해결하는 방법"]).resolve, ())
        self.assertEqual(stage("요통 확실히 해결하는 방법"), STOP, "범위 낱말은 서술어 읽기가 센다")

    def test_the_health_word_must_be_inside_the_two_words_before_the_result_word(self):
        # 대상 창은 결과 서술어 앞 두 낱말부터다(`_has_health_object`) — 건강 낱말이 세 낱말 앞이면 읽지 않는다
        self.assertEqual(cn.health_signals(["통증 100% 해결"]).resolve, ("해결",))
        self.assertEqual(cn.health_signals(["통증 걱정 100% 해결"]).resolve, (), "통증이 세 낱말 앞이다(걱정·100퍼센트·해결)")
        self.assertEqual(cn.health_signals(["통증 앱 서비스 100% 해결"]).resolve, (), "통증이 세 낱말 앞이다")
        self.assertEqual(cn.health_signals(["통증앱서비스100%해결"]).resolve, ("해결",), "한 낱말로 붙여 쓰면 창이 글 처음부터다")

    def test_a_negation_a_question_and_a_warning_word_keep_the_old_guards(self):
        for text in ("요통 해결 보장하는지 확인하기", "요통 해결 보장하지 않는 광고", "통증 100% 해결 광고에 속지 않는 법"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), MARK)
                self.assertEqual(cn.health_signals([text]).counted_assert(), ())
        self.assertEqual(cn.health_signals(["통증 100% 해결 광고에 속지 않는 법"]).resolve, (), "경고 낱말이 있으면 아무것도 세지 않는다")

    def test_the_card_shows_the_result_word_in_the_effect_group(self):
        finding = report_of("통증 100% 해결").findings[0]
        self.assertEqual(finding.code, "HEALTH_STOP")
        self.assertEqual((finding.matched, finding.groups), (("통증", "해결", "100퍼센트"), ("증상·상태", "효과·결과", "단정·보장")))
        self.assertEqual(nt.leaks(nt.cards(nt.from_report(report_of("통증 100% 해결")))), ())

    def test_the_old_floor_does_not_know_the_new_reading(self):
        for text in ("요통 100% 해결", "통증 100% 치유", "기침을 틀림없이 잡아주는 가이드"):
            signals = cn.health_signals([text])
            self.assertEqual(signals.floor_key(), signals.legacy_concept_key(), text)
            self.assertNotIn(signals.floor_key(), sf.LEGACY_STOP_KEYS, "옛 코드는 이 글을 중지로 읽지 않았다 — 새 열쇠가 읽는다")
            self.assertNotEqual(signals.concept_key(), signals.legacy_concept_key())


class WordStartTest(unittest.TestCase):                                                                                  # Z2 (D-303, 독립 검증 P-7·P-5)
    def mode(self, entry):
        return next(mode for name, _pattern, mode in cn.Tables.s_weak if name == entry)

    def test_the_tables_are_the_documented_initial_values(self):
        self.assertEqual(cn.HEALTH_SYMPTOM_START_KO, START_ENTRIES)
        self.assertEqual(cn.HEALTH_SYMPTOM_BARE_KO, ("이명",))
        self.assertEqual(cn.HEALTH_MASKS_WORD_KO, ("바로잡",))
        self.assertEqual((len(cn.HEALTH_SYMPTOM_START_KO), len(cn.HEALTH_SYMPTOM_BARE_KO)), (9, 1))
        self.assertTrue(set(cn.HEALTH_SYMPTOM_START_KO + cn.HEALTH_SYMPTOM_BARE_KO) <= set(cn.HEALTH_SYMPTOM_KO))
        self.assertEqual(len(set(COMPOUNDS)), 25)
        self.assertFalse(set(COMPOUNDS) & set(cn.HEALTH_SYMPTOM_KO), "옛 허용 합성어는 증상 표 밖의 낱말이다")
        self.assertEqual(cn.BARE_SYMPTOM_REST_KO, cn.BARE_DISEASE_PARTICLES_KO + ("증", "으", "처", "현상", "소리", "소음", "치료", "개선", "완화", "극복", "원인", "해결", "검사", "클리닉", "환자"))
        self.assertEqual(len(cn.BARE_SYMPTOM_REST_KO), 27)

    def test_the_compiled_table_marks_each_entry_with_its_reading_mode(self):
        self.assertEqual(len(cn.Tables.s_weak), 59)
        for entry, _pattern, mode in cn.Tables.s_weak:
            with self.subTest(entry=entry):
                if entry in START_WORDS:
                    self.assertEqual(mode, "start")
                elif entry == "눈 건강":
                    self.assertEqual(mode, "wordstart")
                elif entry == "이명":
                    self.assertEqual(mode, "bare")
                elif " " in entry:
                    self.assertFalse(mode)
                else:
                    self.assertTrue(mode is True)
        self.assertEqual([(entry, mode) for entry, _pattern, mode in cn.compile_table(("치매", "감기", "이명", "눈 건강", "수면 장애"), start=("감기", "눈 건강"), bare=("이명",))],
                         [("치매", True), ("감기", "start"), ("이명", "bare"), ("눈 건강", "wordstart"), ("수면 장애", False)])

    def test_a_start_word_is_read_at_a_word_start_with_a_particle_or_an_ending_but_not_inside_a_glued_compound(self):
        for word in START_WORDS:
            with self.subTest(word=word):
                for text in (f"예시 {word} 글", f"{word}이 심할 때", f"{word}약 보관", f"{word} 때 확인할 것"):
                    self.assertEqual(stage(text), MARK, text)
                    self.assertIn(word, cn.health_signals([text]).symptom, text)
                for text in (f"예시 가{word}나 글", f"체{word}기 정리", f"예시 가{word}"):
                    self.assertEqual(stage(text), GENERAL, text)
                    self.assertEqual(cn.health_signals([text]).symptom, (), text)

    def test_the_old_allow_list_words_are_still_read_as_whole_words_by_the_modifier_table(self):
        for compound in COMPOUNDS:
            with self.subTest(compound=compound):
                for text in (f"예시 {compound} 글", f"{obj(compound)} 즉시 없애는 방법", f"{compound}에 즉시 효과 있는 방법"):
                    self.assertEqual(cn.health_signals([text]).symptom, (compound[-2:],), text)
                self.assertEqual(stage(f"{obj(compound)} 즉시 없애는 방법"), STOP)
                self.assertEqual(stage(f"예시 {compound} 글"), MARK)

    def test_the_fifty_one_risk_phrases_the_verifier_found_are_general_in_every_frame_except_the_five_kept_ones(self):
        self.assertEqual(len(RISK_TABLE), 51)
        wrong = []
        for word in RISK_TABLE:
            for frame in RISK_FRAMES:
                text = frame.format(w=word)
                if word in RISK_KEPT:
                    continue
                if stage(text) != GENERAL:
                    wrong.append((stage(text), text))
        self.assertEqual(wrong, [])
        for word, expected in RISK_KEPT.items():
            with self.subTest(word=word):
                self.assertEqual(stage(word), expected, "건강 뜻이 될 수 있거나 알려진 한계 — 표시만(A)")

    def test_the_real_symptom_sentences_still_stop_in_the_normal_places(self):
        for word in START_WORDS + ("이명",):
            for text in (f"{obj(word)} 즉시 없애는 방법", f"{word}에 즉시 효과 있는 방법", f"{word}이 하루 만에 사라지는 방법", f"{word} 100% 해결 보장", f"{word}을 한 번에 해결하는 법"):
                with self.subTest(text=text):
                    self.assertEqual(stage(text), STOP)
        for text in ("요통을 즉시 없애는 방법", "감기에 즉시 효과 있는 방법", "감기를 바로 낫게 하는 차", "기침을 바로 멈추는 방법", "설사 즉시 멈추는 방법", "기침 단번에 멈추는 법"):
            self.assertEqual(stage(text), STOP, text)

    def test_the_bare_word_is_read_only_when_the_word_ends_or_a_particle_follows(self):
        for text in ("예시 가이명증 글", "체이명 기록 앱", "환자이명증 기록"):
            with self.subTest(text=text):
                self.assertEqual(cn.health_signals([text]).symptom, (), "앞에 한글이 붙은 낱말 속 `이명` 은 읽지 않는다")
        for text, expected in (("이명 있을 때 병원 가는 기준", MARK), ("이명이 들릴 때 확인할 것", MARK), ("이명을 즉시 줄이는 방법", STOP), ("이명증 기록 노트", MARK), ("이명으로 병원 가는 기준", MARK), ("이명처럼 들리는 소리", MARK),
                               ("이명을즉시줄이는방법", STOP), ("이명희 작가 에세이 소개", GENERAL), ("이명수 감독 작품 정리", GENERAL), ("이명훈 선수 인터뷰", GENERAL), ("이명박 정부 정책 정리", GENERAL)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)

    def test_the_new_seven_symptoms_alone_are_a_mark_and_with_a_claim_a_stop(self):
        for word in NEW_SYMPTOMS_2:
            with self.subTest(word=word):
                self.assertEqual(stage(f"예시 {word} 글"), MARK)
                self.assertEqual(codes(f"예시 {word} 글"), ["HEALTH_TOPIC"])
                self.assertEqual(stage(f"{word} 기록 앱 만들기"), MARK)
                self.assertEqual(stage(f"{obj(word)} 즉시 없애는 방법"), STOP)
                self.assertEqual(stage(f"{word} 100% 해결"), STOP)
                self.assertIn(word, cn.health_signals([f"예시 {word} 글"]).symptom)
        for text in ("정치통계 바로 줄이는 방법", "실습진행 즉시 줄이는 방법", "학습진도 바로 줄이는 방법"):
            self.assertEqual(stage(text), GENERAL, text)

    def test_a_word_inside_a_product_name_is_still_not_counted_as_its_own_symptom(self):
        # 새 증상 낱말이 제품 이름 속에 있어도 따로 세지 않는 규칙(D-105)은 그대로다 — `감기약` 은 제품 표에 없어 증상 `감기` 로 읽는다
        self.assertIn("감기", cn.health_signals(["감기약 보관 방법"]).symptom)
        self.assertEqual(stage("감기약 보관 방법"), MARK)

    def test_the_blank_within_a_word_helper_only_blanks_a_match_that_does_not_straddle_a_word_start(self):
        pattern = (cn.phrase_regex("바로잡"),)
        for text, blanked in (("자세 바로잡는 방법", True), ("두통 바로 잡아주는 비법", False), ("바로 잡아", False), ("바로잡기", True)):
            joined, starts = cn.compact_marked([cn.fold(text)])
            result = cn.blank_within_words(joined, starts, pattern)
            with self.subTest(text=text):
                self.assertEqual(result != joined, blanked)
                self.assertEqual(len(result), len(joined), "가린 길이는 그대로라 낱말 시작 자리가 맞는다")
        self.assertEqual(stage("두통 바로 잡아주는 비법"), STOP)
        self.assertEqual(stage("통증 바로잡는 방법"), MARK, "붙여 쓴 `바로잡` 은 ‘바로’ 가 아니라 바로잡다")
        self.assertEqual(stage("영양제 자세 바로잡는 방법"), EVIDENCE, "마스크가 없으면 ‘바로’ 가 영양제 곁의 모르는 꾸밈이 되어 옛 중지 바닥에 걸린다 — 영양제 + 자세 는 근거 확인 필요다")
        self.assertEqual(stage("영양제 자세 바로 잡는 방법"), STOP, "띄어 쓰면 ‘바로’ 다 — 영양제 + 모르는 꾸밈은 옛 규칙 그대로")


class ResultReadingTest(unittest.TestCase):                                                                              # Z3 (D-299, 독립 검증 P-4·P-8·P-12)
    NEW_STEM_SENTENCES = (("날려", "피로를 즉시 날려버리는 방법"), ("날리", "피로를 즉시 날리는 방법"), ("날린", "피로를 즉시 날린 비법"), ("날립", "피로를 즉시 날립니다"), ("날렸", "피로를 즉시 날렸습니다"),
                          ("가라앉", "속쓰림 즉시 가라앉히는 음식"), ("고치", "코골이 한 번에 고치는 방법"), ("고쳐", "코골이 바로 고쳐 주는 베개"), ("고친", "코골이를 바로 고친 방법"), ("고칩", "코골이를 즉시 고칩니다"),
                          ("고쳤", "코골이를 즉시 고쳤습니다"), ("빠지", "체중 무조건 빠지는 식단"), ("빠져", "체중이 즉시 빠져요"), ("빠진", "체중이 즉시 빠진 비법"), ("빠집", "체중이 즉시 빠집니다"), ("빠졌", "체중이 즉시 빠졌습니다"),
                          ("멎", "기침이 즉시 멎는 방법"))
    NOUN_ENDINGS = ("하는", "해요", "합니다", "했습니다", "시키는", "되는", "됩니다")

    def test_the_tables_are_the_documented_initial_values(self):
        self.assertEqual(cn._RESULT_NOUNS_KO[-1], "탈출")
        self.assertEqual(len(cn._RESULT_NOUNS_KO), 17)
        self.assertEqual(cn.HEALTH_RESULT_SCOPE_KO[221:238], tuple(stem for stem, _text in self.NEW_STEM_SENTENCES))
        self.assertEqual(len(cn.HEALTH_RESULT_SCOPE_KO), 368)
        self.assertEqual(cn.HEALTH_BARE_TAIL_KO, ("방법", "법", "비법", "비결", "노하우", "요령", "팁", "가이드", "루틴", "비밀"))
        self.assertEqual(cn.HEALTH_HALT_SCOPE_KO, ("멈추", "멈춰", "멈춘", "멈춥", "멈췄", "멈출"))
        self.assertEqual(cn.HEALTH_INSTANT_ACTION_KO, ("풀어보",))
        self.assertEqual([stem for stem in cn.HEALTH_HALT_SCOPE_KO if stem in cn.HEALTH_RESULT_SCOPE_KO], [], "`멈추` 는 결과 서술어 표에 없다 — 복용 중단 낱말과 겹쳐 대상으로 가른다")
        self.assertEqual([(x, y) for x in cn.HEALTH_RESULT_SCOPE_KO for y in cn.HEALTH_ACTION_SCOPE_KO if x.startswith(y) or y.startswith(x)], [], "결과 조각과 행동 조각이 서로의 앞부분이 되지 않는다")

    def test_each_new_verb_stem_is_read_as_an_effect_result_beside_a_health_word(self):
        for stem, text in self.NEW_STEM_SENTENCES:
            with self.subTest(stem=stem):
                self.assertEqual(stage(text), STOP)
                self.assertEqual([scope for _entry, _kind, scope in cn.health_signals([text]).scoped], ["effect"])
                without = text.replace(next(word for word in text.split() if stem in word), "정리하는")
                self.assertEqual(stage(without), MARK, "같은 글에서 그 서술어만 행동으로 바꾸면 표시만이다")

    def test_the_noun_added_to_the_result_nouns_is_read_with_every_ending(self):
        for ending in self.NOUN_ENDINGS:
            for text in (f"변비 하루 만에 탈출{ending} 방법", f"변비를 즉시 탈출{ending} 방법"):
                with self.subTest(text=text):
                    self.assertEqual(stage(text), STOP)

    def test_a_bare_result_noun_ends_the_text_and_reads_as_the_result_beside_a_health_word(self):
        for noun in cn._RESULT_NOUNS_KO:
            for text in (f"통증 즉시 {noun}", f"통증 바로 {noun} 방법", f"통증 하루 만에 {noun} 비법"):
                with self.subTest(text=text):
                    self.assertEqual(stage(text), STOP)
                    self.assertEqual([scope for _entry, _kind, scope in cn.health_signals([text]).scoped], ["effect"])
        for text in ("통증 즉시 완화", "피로를 즉시 해소", "하루 만에 불면 극복", "한 번에 유방암 치료", "하루 만에 비만 해결", "단번에 당뇨 완치", "단번에 피로 해소", "변비 하루 만에 탈출", "집중력 단숨에 향상"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)

    def test_a_bare_noun_that_is_not_the_last_word_is_not_read_and_an_object_is_needed(self):
        for text, expected in (("통증 즉시 완화 후기", MARK), ("스트레스 해소 여행 코스 하루 만에 다녀오기", MARK), ("하루 만에 스트레스 해소 여행 코스", MARK), ("치료 바로 시작하기", MARK), ("통증 즉시 완화 방법 총정리", MARK),
                               ("바로 개선", GENERAL), ("즉시 완화", GENERAL), ("하루 만에 극복", GENERAL), ("서버 오류 즉시 해결", GENERAL), ("규제 즉시 완화", GENERAL), ("스트레스 해소 즉시", MARK)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)

    def test_the_noun_itself_is_not_its_own_object_so_the_object_has_to_come_before_it(self):
        # 의료 효능어(`치료`·`완치`)는 건강 낱말이라 서술어 자리의 명사 자신이 대상으로 세어지면 안 된다 — 명사가 시작하는 자리를 끝으로 대상 창을 본다
        joined, starts = cn.compact_marked([cn.fold("바로 치료")])
        self.assertEqual(cn._scope_and_end(joined, starts, 2)[:2], ("effect", 2))
        self.assertEqual(cn.health_signals(["바로 치료"]).scoped, (("바로", "soft", "none"),), "대상이 없으니 모르는 꾸밈과 같다")
        self.assertEqual(cn.health_signals(["통증 바로 치료"]).scoped, (("바로", "soft", "effect"),))
        self.assertEqual(cn.health_signals(["바로 치료 시작하는 방법"]).scoped, (("바로", "soft", "none"),))

    def test_a_halt_verb_is_an_effect_for_a_symptom_and_a_stop_of_taking_for_a_product(self):
        for text, expected in (("설사 즉시 멈추는 방법", STOP), ("어지럼증 바로 멈추는 방법", STOP), ("기침 단번에 멈추는 법", STOP), ("영양제 먹고 설사 즉시 멈추는 방법", STOP), ("영양제 바로 멈추는 법", MARK),
                               ("영양제 바로 멈춰도 될까", MARK), ("비타민 즉시 멈추는 방법", MARK), ("수면제 바로 멈춰도 될까", STOP), ("수면제 즉시 멈추는 방법", STOP)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)
        self.assertEqual([scope for _entry, _kind, scope in cn.health_signals(["설사 즉시 멈추는 방법"]).scoped], ["effect"])
        self.assertEqual([scope for _entry, _kind, scope in cn.health_signals(["영양제 바로 멈추는 법"]).scoped], ["dose"])
        # 제품 이름 속 증상 낱말(`수면제` 의 ‘수면’)이 대상이 되어 효과로 읽히면 안 된다 — 제품이 창 안에 있으면 복용 중단이다
        self.assertEqual([scope for _entry, _kind, scope in cn.health_signals(["수면제 바로 멈추는 방법"]).scoped], ["dose"])
        self.assertEqual([scope for _entry, _kind, scope in cn.health_signals(["진통제 즉시 멈추는 방법"]).scoped], ["dose"])

    def test_every_halt_stem_is_an_effect_beside_a_symptom_and_a_dose_beside_a_prescription_drug(self):
        for stem, ending in (("멈추", "는 방법"), ("멈춰", "요"), ("멈춘", " 방법"), ("멈춥", "니다"), ("멈췄", "습니다"), ("멈출", " 수 있는 방법")):
            with self.subTest(stem=stem):
                self.assertIn(stem, cn.HEALTH_HALT_SCOPE_KO)
                self.assertEqual(stage(f"설사 즉시 {stem}{ending}"), STOP)
                self.assertEqual([scope for _entry, _kind, scope in cn.health_signals([f"설사 즉시 {stem}{ending}"]).scoped], ["effect"])
                dose_form = stem in ("멈추", "멈춰")                                                  # 복용 중단 낱말 표에 있는 활용형만 복용으로 읽는다 — 나머지는 옛 코드처럼 모르는 꾸밈이다
                self.assertEqual([scope for _entry, _kind, scope in cn.health_signals([f"영양제 바로 {stem}{ending}"]).scoped], ["dose" if dose_form else "none"])
                self.assertEqual(stage(f"영양제 바로 {stem}{ending}"), MARK if dose_form else STOP, "모르는 꾸밈 + 영양제 는 옛 중지 바닥 그대로")

    def test_every_how_to_word_after_a_bare_noun_keeps_it_the_last_word_and_any_other_word_does_not(self):
        for tail in cn.HEALTH_BARE_TAIL_KO:
            with self.subTest(tail=tail):
                self.assertEqual(stage(f"통증 즉시 완화 {tail}"), STOP)
        for other in ("후기", "여행", "음식", "운동", "식단", "앱"):
            with self.subTest(other=other):
                self.assertEqual(stage(f"통증 즉시 완화 {other}"), MARK)
        self.assertEqual(stage("통증 즉시 완화 방법 후기"), MARK, "안내 낱말 뒤에 또 낱말이 오면 끝 말이 아니다")

    def test_a_health_word_between_the_assertion_word_and_the_verb_is_skipped_when_it_reads_the_result(self):
        # 두 낱말 증상(`눈 건강`·`건조한 눈`)이 단정 낱말과 서술어 사이에 있어도 서술어를 읽는다(P-12)
        for text in ("즉시 눈 건강을 회복하는 방법", "바로 건조한 눈을 해소하는 방법", "즉시 어깨 결림을 풀어주는 방법", "바로 소화불량을 낫게 하는 차", "즉각 눈 건강 회복"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)
        # 건너뛰어 읽어 행동·복용으로 보이면 바꾸지 않는다 — 옛 중지가 풀리지 않게(둘째 읽기는 효과 결과일 때만 받아들인다)
        for text in ("고혈압약 즉시 혈압 측정하는 방법", "고혈압약 즉시 혈압 떨어지는 방법", "수면제 바로 수면 시간 기록하는 방법"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)
        for text, expected in (("영양제 바로 영양제 복용하는 방법", STOP), ("즉시 두통 기록 앱", MARK), ("바로 두통 검색하는 방법", MARK)):          # 영양제 + 모르는 꾸밈은 옛 규칙 그대로(옛 중지 바닥)
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)
        joined, starts = cn.compact_marked([cn.fold("즉시 눈 건강을 회복하는 방법")])
        self.assertEqual(cn.scope_of(joined, starts, 2), "none", "공개 함수 `scope_of` 는 건강 낱말 자리를 모르므로 건너뛰지 않는다")
        spans = cn._SpanIndex(cn._health_spans(joined, starts))
        self.assertEqual(cn._scope_and_end(joined, starts, 2, lambda: spans)[0], "effect")

    def test_an_instant_phrase_beside_a_disease_and_a_cure_or_a_solve_noun_stops(self):
        # 운영자 규칙 '질환 + 단정 = 중지' 와 맞춘다(P-4) — 질환 곁 즉각 표현 + 치료·해결·완치 가 글 끝에 오면 근거 확인 필요가 아니라 중지다
        for text in ("한 번에 유방암 치료", "하루 만에 비만 해결", "단번에 당뇨 완치", "하루 만에 당뇨 극복", "일주일 만에 고혈압 해결"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)
        for text in ("유방암 치료 한 번에 정리하기", "비만 해결 방법 정리", "당뇨 한 번에 정리하기"):
            with self.subTest(text=text):
                self.assertNotEqual(stage(text), STOP)

    def test_the_quiz_reading_of_a_solve_verb_is_an_action_beside_the_new_instant_phrases_only(self):
        # D-310: 대상이 증상 낱말이면(`두통을 하루 만에 풀어보는 앱`) 효과로 읽는다 — 그 글들은 Z14 가 지킨다. 제품·질환 곁이나 퀴즈 낱말 곁은 행동 그대로다
        for text in ("크레아틴 단번에 문제 풀어보는 템플릿", "홍삼 한 번에 퀴즈 풀어보는 앱", "당뇨 하루 만에 문제 풀어보는 노트",
                     "크레아틴 단번에 풀어보는 템플릿", "당뇨 한 번에 풀어보는 가이드", "홍삼 먹자마자 풀어보는 퀴즈"):
            with self.subTest(text=text):
                self.assertNotEqual(stage(text), STOP)
                self.assertNotIn("effect", [scope for _entry, _kind, scope in cn.health_signals([text]).scoped])
        for text in ("스트레스를 즉시 풀어보는 방법", "피로를 바로 풀어주는 방법", "스트레스를 한 번에 풀어주는 방법", "크레아틴 즉시 풀어보는 템플릿", "당뇨 바로 풀어보는 가이드", "영양제 즉시 풀어보는 방법", "홍삼 즉시 문제 풀어보는 앱"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP, "옛 범위 낱말(즉시·바로)과 `풀어주는` 은 그대로다 — 제품·질환 곁 `즉시 풀어보는` 도 기준처럼 중지다(D-306 ⑧, 3차 수정 변이 N18 이 알려 준 시험 틈)")


class ShoppingContextTest(unittest.TestCase):                                                                            # Z3 (D-299, 독립 검증 P-8)
    SHOPPING = ("영양제 하루 만에 품절되는 이유", "비타민 단번에 품절되는 이유", "홍삼 하루 만에 팔리는 이유", "영양제 단번에 이해하는 성분표 읽기", "건강기능식품 하루 만에 소진되는 재고 관리 방법", "하루 만에 품절된 영양제 후기 분석",
                "단번에 매진된 비타민 이벤트 정리", "영양제 하루 만에 마스터하는 구매 가이드", "비타민 하루 만에 배달받는 순서", "건강기능식품 하루 만에 소진되는 이유 분석", "프로바이오틱스 단번에 이해하는 용어 정리", "영양제 단번에 흡수되는 시간")
    VERBS = ("마스터하는", "이해하는", "습득하는", "완성하는", "마무리하는", "익히는", "터득하는", "소화하는", "훑어보는", "요약하는", "번역하는", "배달받는", "소진되는", "뽑는", "모으는", "외우는", "구매하는", "채우는", "포장하는", "환불받는",
             "교환하는", "반품하는", "품절되는", "매진되는", "팔리는", "도착하는", "배송되는", "마감되는", "끝나는", "바뀌는", "오르는", "내려가는", "할인받는", "주문하는", "정리하는", "비교하는", "후기 쓰는", "리뷰 쓰는")

    def test_the_verifier_shopping_sentences_are_marked_only_like_before_the_instant_phrases_existed(self):
        for text in self.SHOPPING:
            with self.subTest(text=text):
                self.assertEqual(stage(text), MARK)
                self.assertEqual(cn.health_signals([text]).counted_assert(), ())

    def test_no_shopping_or_study_verb_after_an_instant_phrase_stops_beside_a_supplement_a_medicine_or_a_health_word(self):
        stops = [f"{word} {phrase} {verb} 방법" for word in cn.HEALTH_SUPPLEMENT_KO + cn.HEALTH_MEDICINE_KO + ("두통", "당뇨", "불면", "탈모") for phrase in INSTANT for verb in self.VERBS if stage(f"{word} {phrase} {verb} 방법") == STOP]
        self.assertEqual(stops, [])

    def test_the_rule_that_counted_an_unknown_predicate_beside_a_product_is_gone_but_health_result_shapes_still_stop(self):
        for text in ("영양제 먹고 하루 만에 살 빠지는 법", "영양제 먹고 단번에 피로가 풀리는 법", "영양제 먹고 하루 만에 체중이 낮아지는 법", "영양제 먹고 하루 만에 통증이 사라지는 법", "영양제 먹고 단번에 혈당이 낮아지는 법", "비타민 먹고 하루 만에 좋아지는 법",
                     "영양제 먹고 하루 만에 살이 쏙 빠지는 법", "영양제 먹고 하루 만에 5kg 빠지는 법"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)
        for text in ("영양제 하루 만에 소진되는 이유", "영양제 단번에 흡수되는 시간"):
            self.assertEqual(stage(text), MARK, "D-293 은 이 글을 중지로 읽었다 — 모르는 서술어는 이제 세지 않는다")

    def test_a_dose_verb_after_an_instant_phrase_beside_a_supplement_is_an_action_order(self):
        # 변이 V13 이 드러낸 시험 틈 — `영양제 단번에 먹는 방법`·`영양제 하루 만에 복용하는 방법` 은 표시만인데 변이는 중지로 읽었다
        for text in ("영양제 단번에 먹는 방법", "영양제 하루 만에 복용하는 방법", "영양제 한 번에 먹는 방법", "영양제 한꺼번에 섭취하는 방법", "비타민 단번에 마시는 방법"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), MARK)
                self.assertEqual([scope for _entry, _kind, scope in cn.health_signals([text]).scoped], ["dose"])
                self.assertEqual(cn.health_signals([text]).counted_assert(), ())
        for text in ("수면제 한 번에 끊는 방법", "수면제 단번에 끊어도 될까", "혈압약 하루 만에 끊는 법"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP, "처방약 곁의 복용·중단 동사는 지금도 단정이다")

    def test_an_unknown_predicate_beside_a_prescription_drug_is_not_counted_for_an_instant_phrase_but_still_for_an_old_word(self):
        self.assertEqual(stage("수면제 하루 만에 품절되는 이유"), MARK)
        self.assertEqual(stage("혈압약 한 번에 두 알 먹는 방법"), EVIDENCE)
        self.assertEqual(stage("수면제 즉시 품절되는 이유"), STOP, "옛 범위 낱말은 처방약 곁에서 모르는 꾸밈도 센다(D-133)")


class InstantMoreTest(unittest.TestCase):                                                                                # Z4 (D-300, 독립 검증 P-3)
    def test_the_tables_are_the_documented_initial_values(self):
        self.assertEqual(cn.HEALTH_INSTANT_MORE_KO, ("먹자마자", "마시자마자", "하룻밤", "한방에", "금세", "이틀 만에", "사흘 만에", "일주일 만에", "열흘 만에", "며칠 만에", "한 달 만에"))
        self.assertEqual(cn.HEALTH_INSTANT_NUMBERED_KO, ("분 만에", "시간 만에", "일 만에", "주 만에", "개월 만에"))
        self.assertEqual((len(cn.HEALTH_INSTANT_MORE_KO), len(cn.HEALTH_INSTANT_NUMBERED_KO)), (11, 5))
        self.assertEqual(cn.Tables.instant_all, frozenset(cn.HEALTH_INSTANT_PHRASE_KO + cn.HEALTH_INSTANT_MORE_KO + cn.HEALTH_INSTANT_NUMBERED_KO))
        for word in cn.HEALTH_INSTANT_MORE_KO + cn.HEALTH_INSTANT_NUMBERED_KO:
            self.assertNotIn(word, cn.HEALTH_ASSERT_SOFT_KO, "옛 중지 바닥의 바탕 표에는 옛 코드의 낱말만 있다")
            self.assertNotIn(word, cn.ASSERT_SCOPED_KO["soft"])

    def test_each_new_phrase_beside_a_health_word_and_an_effect_predicate_stops(self):
        for text in ("통증을 5분 만에 없애는 방법", "두통 10분 만에 사라지는 방법", "통증 2시간 만에 줄이는 법", "불면 하룻밤에 해결하는 방법", "코골이 한방에 고치는 방법", "두통 금세 가라앉히는 방법", "당뇨 일주일 만에 극복",
                     "비만 며칠 만에 해결", "감기 이틀 만에 낫는 방법", "감기 사흘 만에 낫는 방법", "두통 3일 만에 사라지는 방법", "불면 2주 만에 해결하는 법", "요통 3개월 만에 낫는 방법", "통증 몇 분 만에 없애는 방법",
                     "영양제 먹자마자 살 빠지는 법", "통증 마시자마자 사라지는 차", "열흘 만에 두통 해결", "두통 한 주 만에 사라지는 방법"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)
                self.assertIn("effect", [scope for _entry, _kind, scope in cn.health_signals([text]).scoped])

    def test_every_new_phrase_stops_with_every_symptom_verb_pair(self):
        phrases = ("5분 만에", "2시간 만에", "3일 만에", "2주 만에", "3개월 만에", "하룻밤에", "한방에", "금세", "이틀 만에", "사흘 만에", "일주일 만에", "열흘 만에", "며칠 만에", "한 달 만에", "먹자마자", "마시자마자")
        texts = [f"{obj(symptom)} {phrase} {verb} 방법" for symptom in ("두통", "요통", "불면", "피로", "변비") for phrase in phrases for verb in ("없애는", "줄이는", "해결하는", "개선하는")]
        self.assertEqual([text for text in texts if stage(text) != STOP], [])

    def test_a_shopping_or_ordinary_sentence_with_a_new_phrase_is_not_stopped(self):
        for text, expected in (("배송 일주일 만에 도착하는 영양제", MARK), ("영양제 이틀 만에 도착하는 배송 업체 비교", MARK), ("비타민 며칠 만에 품절되는 이유", MARK), ("수면제 일주일 만에 받는 방법", MARK),
                               ("혈압약 며칠 만에 배송되는 이유", EVIDENCE), ("영양제 열흘 만에 도착하는 주문 방법", MARK), ("체중 한 달 만에 5kg 감량", MARK), ("당뇨 식단 일주일 만에 정리하는 방법", EVIDENCE),
                               ("이사 짐 일주일 만에 싸는 방법", GENERAL), ("블로그 글 금세 쓰는 방법", GENERAL), ("엑셀 정리 5분 만에 끝내는 방법", GENERAL), ("서버 오류 하룻밤에 해결하는 방법", GENERAL)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)

    def test_a_prescription_drug_beside_a_new_phrase_counts_only_when_the_verb_is_a_dose_or_an_effect(self):
        self.assertEqual(stage("수면제 며칠 만에 끊는 방법"), STOP)
        self.assertEqual(stage("수면제 며칠 만에 끊어도 될까"), STOP)
        self.assertEqual(stage("혈압약 일주일 만에 사라지는 방법"), STOP, "처방약 + 효과 서술은 효과 결과다")
        self.assertEqual(stage("혈압약 일주일 만에 받는 방법"), EVIDENCE)
        self.assertEqual(stage("수면제 먹자마자 잠드는 방법"), MARK, "`잠드는` 은 결과 서술어 표에 없다 — 모르는 서술어는 세지 않는다")

    def test_a_number_is_needed_for_the_period_phrases_and_the_one_blow_phrase_is_not_the_korean_medicine_word(self):
        for text in ("통증을 분만에 없애는 방법", "분만에 필요한 준비물 즉시 확인", "시간 만에", "한방에서 보는 감기 치료", "한방에서 통증을 즉시 다스리는 방법"):
            with self.subTest(text=text):
                self.assertNotIn("분 만에", [entry for entry, _kind, _scope in cn.health_signals([text]).scoped])
                self.assertNotIn("한방에", [entry for entry, _kind, _scope in cn.health_signals([text]).scoped])
        self.assertEqual(stage("통증을 분만에 없애는 방법"), MARK)
        self.assertEqual(stage("분만에 필요한 준비물 즉시 확인"), GENERAL)
        self.assertEqual(stage("한방에서 보는 감기 치료"), EVIDENCE)

    def test_a_negation_a_question_and_a_warning_word_switch_the_new_phrases_off_too(self):
        for text in ("통증을 5분 만에 없애지 않는 법", "통증을 5분 만에 줄일까", "통증을 일주일 만에 없애는지 알아보기", "통증을 5분 만에 없앤다는 광고에 속지 않는 법"):
            with self.subTest(text=text):
                self.assertEqual(cn.health_signals([text]).counted_assert(), ())


class GluedEndingTest(unittest.TestCase):                                                                                # Z5 (D-301, 독립 검증 P-2)
    ENDINGS = ("지압법", "가이드", "지침", "지식", "지름길", "인지법")

    def test_the_helper_table_and_the_rule_are_pinned(self):
        self.assertEqual(cn._QUESTION_AFTER, ("요", "도", "는", "를", "을", "가", "이", "만", "에", "죠", "다", "고", "라"))
        self.assertEqual(len(cn._QUESTION_ENDINGS), 15)

    def test_an_ending_glued_to_a_longer_word_is_not_a_question_and_the_assertion_stays_on(self):
        texts = [f"{obj(symptom)} {phrase} {verb}{end}" for symptom in ("두통", "요통", "불면", "피로", "체중", "통증", "붓기", "집중력") for phrase in ("바로", "즉시", "하루 만에", "단번에") for verb in ("없애는", "줄이는") for end in self.ENDINGS]
        self.assertEqual([text for text in texts if stage(text) != STOP], [])

    def test_a_real_question_ending_that_closes_the_word_still_switches_the_assertion_off(self):
        for text in ("피로를 즉시 줄이는지 알아보기", "피로를 즉시 줄일까요", "피로를 즉시 줄이는지를 알아보기", "피로를 즉시 줄이는지에 대한 글", "피로를 즉시 줄이는지도", "피로를 즉시 줄이는가 궁금", "피로를 즉시 줄일까 고민", "피로를 즉시 줄이나요"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), MARK)
                self.assertEqual(cn.health_signals([text]).counted_assert(), ())

    def test_the_helper_closes_the_ending_at_a_word_end_a_particle_or_the_text_end(self):
        def closed(text, place):
            joined, starts = cn.compact_marked([cn.fold(text)])
            return cn._question_closed(joined, starts, place)
        for text, place, expected in (("줄이는지", 4, True), ("줄이는지 알아보기", 4, True), ("줄이는지를 알아보기", 4, True), ("줄이는지도", 4, True), ("줄이는지압법", 4, False), ("줄이는가이드", 4, False), ("줄이는지침", 4, False),
                                      ("줄이는지를알아보기", 4, False), ("줄일까요", 3, True), ("줄일까봐", 3, False), ("줄이는지", 5, True)):
            with self.subTest(text=text, place=place):
                self.assertEqual(closed(text, place), expected)
        joined, starts = cn.compact_marked(["줄이는지", "압법"])
        self.assertTrue(cn._question_closed(joined, starts, 4), "다른 글 조각(`SEP`) 앞은 낱말 끝이다")

    def test_the_prefix_ending_that_needs_a_third_letter_is_not_asked_to_close(self):
        for text in ("바로 효과 있을까", "바로 효과 있을지", "바로 효과 있을 수 있다"):
            joined, starts = cn.compact_marked([cn.fold(text)])
            with self.subTest(text=text):
                self.assertTrue(cn._asks_after(joined, starts, 2), "`있을` 은 `있을까`·`있을지` 의 앞부분이라 옛 규칙대로 읽는다")

    def test_the_known_limit_a_glued_particle_looking_end_word_stays_a_question(self):
        self.assertEqual(stage("두통을 바로 없애는지도"), MARK, "`지도`(안내 지도)는 `는지`+`도`(조사)와 구별되지 않는다 — 안전하지 않은 쪽의 한계(D-306)")
        self.assertEqual(stage("피로를 즉시 줄이는지알아보기"), STOP, "띄어쓰기 없이 이어 쓴 진짜 의문은 단정으로 읽는다 — 안전한 쪽의 한계(D-306)")
        self.assertEqual(stage("피로를 즉시 줄이는 지 알아보기"), STOP, "`는 지` 로 잘못 띄어 쓴 의문도 단정으로 읽는다 — 안전한 쪽의 한계(D-306, 독립 검증 P-9)")


class QuitRefineTest(unittest.TestCase):                                                                                 # Z6 (D-302, 독립 검증 P-6)
    def test_the_tables_are_the_documented_initial_values(self):
        self.assertEqual(cn.HEALTH_QUIT_CURE_KO, ("낫는", "나아지", "극복", "회복"))
        self.assertEqual(cn.HEALTH_QUIT_OK_KO, ("되는", "안전한", "괜찮은", "가능한", "문제없는", "좋은"))
        self.assertEqual((len(cn.HEALTH_QUIT_CURE_KO), len(cn.HEALTH_QUIT_OK_KO)), (4, 6))
        self.assertEqual(cn.HEALTH_QUIT_OK_KO[0], "되는", "옛 말투가 첫째다")

    def test_a_generic_effect_word_alone_does_not_make_a_prescription_quit_a_claim(self):
        # D-308: 약 이름(수면제·인슐린 …) + 복용 중단 + 결과어(`개선`·`해결` …)는 비용 이야기여도 중지로 읽는다(`인슐린 구독 중단하고 비용 개선하는 방법` — 알려진 과탐, KnownLimitTest). 일반 낱말(의약품·처방약·치료제)이나 결과어가 없는 글은 그대로다
        for text in ("의약품 구독 끊고 비용 줄이는 방법", "의약품 구독 안 먹고 비용 낮추는 방법", "처방약 구독 끊고 지출 줄이는 법", "스테로이드 구독 끊고 요금 낮추는 법", "의약품 끊고 비용 개선하는 방법"):
            with self.subTest(text=text):
                self.assertEqual(cn.health_signals([text]).quit, ())
                self.assertNotEqual(stage(text), STOP)
        self.assertEqual(stage("의약품 구독 끊고 비용 줄이는 방법"), EVIDENCE, "기준 커밋과 같다")

    def test_a_symptom_or_a_disease_or_a_health_only_cure_word_still_makes_it_a_claim(self):
        for text in ("수면제 끊고 불면 줄이는 방법", "진통제 끊고 통증 줄이는 방법", "당뇨약 안 먹고 낫는 방법", "스테로이드 안 먹고 낫는 방법", "수면제 끊고 극복하는 법", "수면제 끊고 회복하는 방법", "항생제 먹지 않고 나아지는 방법",
                     "의약품 구독 끊고 스트레스 줄이는 앱", "혈압약 끊고 혈압 낮추는 방법", "당뇨약 끊고 혈당 낮추는 방법", "항암제 안 먹고 암세포 줄이는 방법", "스타틴 끊고 콜레스테롤 낮추는 방법"):        # 마지막 넷: 질환 낱말만 있는 복용 중단(기준은 근거 확인 필요 — 3차 수정 변이 N21 이 알려 준 시험 틈)
            with self.subTest(text=text):
                self.assertTrue(cn.health_signals([text]).quit)
                self.assertEqual(stage(text), STOP)

    def test_the_permission_phrasings_stop_like_the_old_one_for_every_medicine_and_stop_phrase_and_how_to_word(self):
        texts = [f"{medicine} {allowed} {ok} {howto}" for medicine in cn.HEALTH_MEDICINE_KO for allowed in cn.HEALTH_QUIT_ALLOW_KO for ok in cn.HEALTH_QUIT_OK_KO for howto in cn.HEALTH_QUIT_HOWTO_KO]
        self.assertEqual(len(texts), 16 * 5 * 6 * 6)
        self.assertEqual([text for text in texts if stage(text) != STOP], [])
        for ok in cn.HEALTH_QUIT_OK_KO[1:]:
            self.assertEqual(cn.health_signals([f"수면제 끊어도 {ok} 방법"]).quit, ("끊어도",), ok)

    def test_a_question_a_timing_and_a_plain_how_to_are_as_before_for_the_new_phrasings(self):
        for text, expected in (("수면제 끊어도 안전한 시기", MARK), ("수면제 끊어도 괜찮은지 알아보기", EVIDENCE), ("수면제 끊어도 되나요", EVIDENCE), ("수면제 끊어도 안전한가요", EVIDENCE), ("수면제 끊어도 괜찮을까", EVIDENCE),
                               ("혈압약 끊어도 되는 시기", EVIDENCE), ("혈압약 끊어도 되는 법적 근거", EVIDENCE), ("수면제 끊어도 되는 방법이나 시기", EVIDENCE), ("수면제 끊어도 되는 방법이나 시기 알아보기", EVIDENCE), ("수면제 끊어도 가능한 시기 정리", MARK), ("영양제 끊어도 안전한 방법", MARK), ("한약 끊어도 괜찮은 방법", EVIDENCE)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)
        self.assertEqual(cn.health_signals(["수면제 끊어도 안전한 시기"]).quit, ())

    def test_an_effect_word_that_only_lives_inside_a_product_name_is_not_a_cure_word(self):
        # `자세교정기` 속 ‘교정’ 은 제품 이름의 일부일 뿐이다 — 처방약 + 복용 중단 곁이어도 낫는 말로 세지 않는다(검증자의 변이 V17)
        for text in ("당뇨약 끊고 자세교정기 구독 정리", "당뇨약 끊고 자세교정기 비교하는 방법", "혈압약 안 먹고 자세교정기 고르는 법"):
            with self.subTest(text=text):
                self.assertEqual(cn.health_signals([text]).quit, ())
                self.assertNotEqual(stage(text), STOP)
        self.assertTrue(cn.health_signals(["당뇨약 끊고 자세 교정하는 방법"]).quit, "띄어 쓴 `교정` 은 낱말이라 세어진다")

    def test_a_stop_phrase_that_only_forms_across_two_words_is_not_read(self):
        # 단어 하나짜리 표현 `끊고` 가 `끊 고기` 처럼 두 낱말에 걸쳐 우연히 맞는 것은 읽지 않는다(검증자의 변이 V20)
        for text in ("당뇨약 낫는 방법 끊 고기", "당뇨약 낫는 끊 고기", "수면제 불면 극복 끊 고기"):
            with self.subTest(text=text):
                self.assertEqual(cn.health_signals([text]).quit, ())
        self.assertEqual(cn.health_signals(["당뇨약 끊고 낫는 방법"]).quit, ("끊고",))

    def test_a_prescription_word_is_still_needed(self):
        for text in ("영양제 끊어도 안전한 방법", "비타민 끊어도 괜찮은 방법", "한약 끊어도 문제없는 방법"):
            self.assertEqual(cn.health_signals([text]).quit, (), text)


class SpeedTest(unittest.TestCase):                                                                                      # Z7 (D-304, 독립 검증 P-11)
    CASES = {"하루 만에 당뇨 극복 x1000": "하루 만에 당뇨 극복 " * 1000, "하루 만에 당뇨 극복 x2000": "하루 만에 당뇨 극복 " * 2000, "단번에 영양제 극복 x1000": "단번에 영양제 극복 " * 1000, "한 번에 요통 줄이는 x1000": "한 번에 요통 줄이는 " * 1000,
             "한 번에 요통 줄이는 x2000": "한 번에 요통 줄이는 " * 2000, "없애는 지압법 x1000": "바로 없애는 지압법 " * 1000, "체감기온 x1000": "체감기온 바로 줄이는 " * 1000, "하루 만에 x2000 + 당뇨": "하루 만에 " * 2000 + "당뇨 극복",
             "즉시 x2000": "즉시 " * 2000, "바로 줄이는 x1000": "바로 줄이는 " * 1000, "이명 x2000": "이명 " * 2000, "5분 만에 통증 없애는 x1000": "5분 만에 통증 없애는 " * 1000, "100% 해결 x1000": "통증 100% 해결 " * 1000,
             "통증 즉시 완화 x2000": "통증 즉시 완화 " * 2000, "1 x4000": "1" * 4000, "감기 x2000": "감기 " * 2000, "영양제 하루 만에 소진 x1000": "영양제 하루 만에 소진되는 이유 " * 1000, "암 x16000": "암 " * 16000, "암세포 x8000": "암세포 " * 8000, "설 사 x4000": "설 사 " * 4000, "이 명 x4000": "이 명 " * 4000}

    def test_pathological_repeated_inputs_judge_in_under_a_second(self):
        slow = []
        for name, text in self.CASES.items():
            best = min(self.took(text) for _ in range(2))
            if best >= 1.0:
                slow.append((name, round(best, 2)))
        self.assertEqual(slow, [])

    @staticmethod
    def took(text):
        started = time.perf_counter()
        sf.check_text([text])
        return time.perf_counter() - started

    def test_the_helpers_agree_with_the_plain_scans_they_replaced(self):
        def naive_pieces(text, starts, end):                              # 옛 구현 — 글 끝(`SEP`)까지 전부 쪼갠다
            stop = text.find(cn.SEP, end)
            stop = len(text) if stop < 0 else stop
            cuts = [end, *sorted(place for place in starts if end < place < stop), stop]
            pieces = [(cuts[number], cuts[number + 1], text[cuts[number]:cuts[number + 1]]) for number in range(len(cuts) - 1)]
            if pieces and end not in starts:
                pieces[0] = (pieces[0][0], pieces[0][1], cn.Tables.adverb_suffix.sub("", pieces[0][2], count=1))
            return [piece for piece in pieces if piece[2]]

        def naive_object(text, starts, spans, begin, stop):               # 옛 구현 — 낱말 시작 자리를 전부 훑는다
            word = max((place for place in starts if place <= begin), default=0)
            lower = text.rfind(cn.SEP, 0, word) + 1
            before = sorted(place for place in starts if lower <= place < word)
            window = max(lower, before[-2]) if len(before) >= 2 else lower
            return any(low < stop and high > window for low, high in spans)

        def naive_rest(text, starts, end):
            stop = text.find(cn.SEP, end)
            stop = len(text) if stop < 0 else stop
            ends = [place for place in starts if end <= place < stop]
            return text[end:min(ends) if ends else stop]

        rng = random.Random(20261109)
        syllables = ("통", "증", "즉", "시", "바", "로", " ", " ", "줄", "이", "는", "방", "법", "영", "양", "제", "-", "x")
        for _ in range(300):
            raw = "".join(rng.choice(syllables) for _ in range(rng.randint(1, 40)))
            joined, starts = cn.compact_marked([cn.fold(raw), cn.fold(raw[::-1])])
            plain = frozenset(starts)
            for end in range(0, len(joined) + 1, 2):
                self.assertEqual(cn._pieces_after(joined, starts, end, limit=1000), naive_pieces(joined, starts, end))
                self.assertEqual(cn._pieces_after(joined, starts, end), cn._pieces_after(joined, plain, end), "집합만 받아도 같다")
                self.assertEqual(cn._pieces_after(joined, starts, end), naive_pieces(joined, starts, end)[:6][:len(cn._pieces_after(joined, starts, end))])
                self.assertEqual(cn._word_rest(joined, starts, end), naive_rest(joined, starts, end))
                stop = min(len(joined), end + rng.randint(0, 6))
                spans = [(low, min(len(joined), low + rng.randint(1, 4))) for low in rng.sample(range(len(joined)), min(3, len(joined)))]
                expected = naive_object(joined, starts, spans, end, stop)
                self.assertEqual(cn._has_health_object(joined, starts, spans, end, stop), expected)
                self.assertEqual(cn._has_health_object(joined, plain, spans, end, stop), expected)
                self.assertEqual(cn._has_health_object(joined, starts, cn._SpanIndex(spans), end, stop), expected)

    def test_the_span_index_answers_overlap_and_cover_like_the_naive_any(self):
        rng = random.Random(7)
        for _ in range(300):
            spans = [(low, low + rng.randint(1, 6)) for low in (rng.randint(0, 50) for _ in range(rng.randint(0, 12)))]
            index = cn._SpanIndex(spans)
            self.assertEqual(list(index), sorted(spans))
            self.assertEqual(len(index), len(spans))
            for _ in range(20):
                a, b = rng.randint(0, 60), rng.randint(0, 60)
                self.assertEqual(index.overlaps(a, b), any(low < b and high > a for low, high in spans))
                self.assertEqual(index.covers(a, b), any(low <= a and b <= high for low, high in spans))

    def test_the_percent_scan_does_not_slow_down_on_a_long_run_of_digits(self):
        for text in ("1" * 8000, "12" * 4000 + "%", "9" * 6000 + "분 만에"):
            best = min(self.took_fold(text) for _ in range(2))
            self.assertLess(best, 0.3, len(text))

    @staticmethod
    def took_fold(text):
        started = time.perf_counter()
        cn.fold(text)
        cn.health_signals([text])
        return time.perf_counter() - started

    def test_the_start_set_is_a_frozenset_that_remembers_its_order_and_the_percent_scan_means_the_same(self):
        joined, starts = cn.compact_marked(["가나 다라 마", "바 사"])
        self.assertIsInstance(starts, frozenset)
        self.assertEqual(starts.order, tuple(sorted(starts)))
        self.assertEqual(starts, frozenset(starts.order))
        self.assertEqual(cn._order(frozenset({5, 1, 3})), (1, 3, 5))
        self.assertEqual(cn.compact_marked([]), ("", frozenset()))
        for text, expected in (("효과 100% 보장", "효과 100퍼센트 보장"), ("a1234%", "a1234퍼센트"), ("12345", "12345"), ("3 퍼센트 12프로 7 %", "3퍼센트 12퍼센트 7퍼센트"), ("１００％", "100퍼센트")):
            self.assertEqual(cn.fold(text), expected)


class MaskStructureTest(unittest.TestCase):                                                                              # Z10 (D-307, 델타 재검증 D1)
    BRIEF = ("두통 한눈에 즉시 없애는 방법", "피로를 한눈에 즉각 회복하는 식단", "스트레스 한눈에 바로 풀어주는 음악", "통증을 한눈에 바로 줄여줍니다", "당뇨를 한눈에 즉시 해결하는 습관", "피로를 첫눈에 즉시 회복하는 식단",
             "요통 한눈에 하루 만에 줄이는 법", "두통 첫눈에 단번에 없애는 방법", "불면 첫눈에 당장 해결하는 식단")

    def test_the_two_one_word_masks_are_gone_and_the_sentences_they_cut_stop_again(self):
        for mask in ("한눈에", "첫눈에"):
            self.assertNotIn(mask, cn.HEALTH_MASKS_KO)
        self.assertEqual(len(cn.HEALTH_MASKS_KO), 64)
        for text in self.BRIEF:
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)

    def test_the_eye_health_word_is_read_only_from_a_word_start_so_the_idiom_does_not_need_a_mask(self):
        self.assertIn("눈 건강", cn.HEALTH_SYMPTOM_START_KO)
        self.assertEqual(next(mode for entry, _pattern, mode in cn.Tables.s_weak if entry == "눈 건강"), "wordstart")
        for text in ("한눈에 건강 상태 확인하는 앱 화면 구성", "첫눈에 건강해 보이는 사람의 특징", "한눈에 건강 점수 보는 방법", "첫눈에 건강미가 느껴지는 코디"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), GENERAL)
                self.assertEqual(cn.health_signals([text]).symptom, ())
        for text in ("눈 건강 검진 항목 정리", "눈에 건강한 음식", "눈건강 영양제 비교", "시력과 눈 건강 지키는 습관"):
            with self.subTest(text=text):
                self.assertNotEqual(stage(text), GENERAL)
        self.assertEqual(stage("해결 보장 한눈에 건강기능식품"), STOP, "마스크를 좁히던 안(`한눈에 건강`)은 `건강기능식품` 속 ‘건강’ 을 먹어 이 글을 낮췄다")

    FILLER_STAGES = {}

    @classmethod
    def lowered_cells(cls, mask):
        """`증상 + 마스크 + 즉각 낱말 + 효과 동사` 가 같은 낱말 수의 평범한 낱말(`오늘`·`하루`)로 바꾼 글보다 낮아지는 칸 — 마스크가 글을 `SEP` 로 갈라 앞 두 낱말 창과 서술어 읽기를 끊어 앞의 중지를 낮추는지 본다."""
        filler = " ".join(("오늘", "하루", "오늘", "하루")[:len(mask.split())])
        found = []
        for symptom, assertion, verb in itertools.product(MASK_SYMPTOMS, MASK_ASSERTS, MASK_VERBS):
            with_mask, with_filler = f"{symptom} {mask} {assertion} {verb}", f"{symptom} {filler} {assertion} {verb}"
            if with_filler not in cls.FILLER_STAGES:
                cls.FILLER_STAGES[with_filler] = stage(with_filler)                          # 낱말 수가 같은 마스크끼리 같은 글을 쓴다 — 한 번만 판정한다
            if RANK[stage(with_mask)] < RANK[cls.FILLER_STAGES[with_filler]]:
                found.append((with_mask, stage(with_mask), cls.FILLER_STAGES[with_filler]))
        return found

    def test_only_the_inherited_one_word_masks_lower_a_sentence_below_the_same_sentence_with_neutral_words_in_its_place(self):
        # 속성 시험: 마스크 표 전체를 돌린다. 글을 낮추는 마스크는 기준(main)에 이미 있던 한 낱말 마스크 24개뿐이다 — 이 묶음이 더한 마스크는 모두 두 낱말이라 같은 낱말 수의 평범한 낱말과 똑같이 읽힌다.
        # 새 마스크를 더했는데 이 목록이 늘면(특히 한 낱말 마스크) 이 시험이 알린다
        lowering = tuple(mask for mask in cn.HEALTH_MASKS_KO if self.lowered_cells(mask))
        self.assertEqual(lowering, INHERITED_CUT_MASKS)
        self.assertEqual(set(INHERITED_CUT_MASKS) - set(cn.HEALTH_MASKS_KO[:48]), set(), "낮추는 마스크는 모두 기준(main)의 마스크 48개 안에 있다")
        self.assertTrue(all(" " not in mask for mask in INHERITED_CUT_MASKS))
        self.assertEqual([mask for mask in cn.HEALTH_MASKS_KO[48:] if " " not in mask], [], "이 묶음이 더한 마스크에는 한 낱말 마스크가 없다")

    def test_the_inherited_masks_read_as_the_base_did(self):
        # 기준(main)과 같다(미리 계산해 박은 기준 단계 A·A·A) — 이 묶음이 바꾸지 않은 한계로 D-306 에 적었다
        for text, expected in (("두통 소화기 즉시 없애는 방법", MARK), ("두통 자세히 즉시 없애는 방법", MARK), ("피로 불안정 바로 줄이는 방법", MARK), ("통증 소화기 즉시 없애는 방법", MARK)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)

    def test_a_mask_still_keeps_an_everyday_idiom_out_of_the_health_words_in_front_of_and_behind_an_instant_word(self):
        for text in ("줄 감기 쉬운 정리함 바로 고르는 방법", "이어폰 줄 감기 즉시 끝내는 방법", "건조한 눈빛 바로 만드는 방법", "머리 감기 순서 즉시 바꾸는 방법"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), GENERAL)


class WordCrossingTest(unittest.TestCase):                                                                               # Z11 (D-307, 델타 재검증 D2·D9)
    def test_the_verifier_154_cross_word_sentences_are_general_like_the_base(self):
        self.assertEqual(len(VERIFIER_CROSS_154), 154)
        self.assertEqual(len(set(VERIFIER_CROSS_154)), 154)
        wrong = [(stage(text), text) for text in VERIFIER_CROSS_154 if stage(text) != GENERAL or cn.health_signals([text]).symptom]
        self.assertEqual(wrong, [])
        for text in VERIFIER_CROSS_154:
            self.assertEqual(candidate_stages(text), {"topic": GENERAL, "primary_keyword": GENERAL, "secondary_keywords": GENERAL}, text)

    def test_a_short_word_and_the_next_word_that_form_a_symptom_across_a_space_are_not_read(self):
        self.assertEqual(len(CROSS_WORD), 40)
        for text in CROSS_WORD:
            for frame in ("{w}", "{w} 바로 올리는 방법", "{w} 즉시 줄이는 방법", "{w} 하루 만에 해결하는 방법"):
                sentence = frame.format(w=text)
                with self.subTest(text=sentence):
                    self.assertEqual(stage(sentence), GENERAL)
                    self.assertEqual(cn.health_signals([sentence]).symptom, ())

    def test_letters_spread_with_spaces_or_marks_are_not_read_as_the_symptom_either(self):
        for word in START_WORDS + ("이명",):
            first, second = word
            for text in (f"{first} {second}", f"{first}-{second}", f"{first}·{second}", f"예시 {first} {second} 글", f"{first} {second}을 즉시 줄이는 방법", f"{first}  {second}"):
                with self.subTest(text=text):
                    self.assertEqual(cn.health_signals([text]).symptom, (), text)
        self.assertEqual(stage("이 명 을 즉 시 줄 이 는 방 법"), GENERAL)

    def test_the_table_reader_refuses_a_match_that_starts_a_new_word_inside_it_and_accepts_the_same_letters_in_one_word(self):
        def read(text, word):
            joined, starts = cn.compact_marked([cn.fold(text)])
            return word in cn.find_ko(joined, starts, cn.Tables.s_weak)
        for text, word, expected in (("설 사진", "설사", False), ("설사진", "설사", True), ("감 기르는", "감기", False), ("감기르는", "감기", True), ("이 명", "이명", False), ("이명", "이명", True),
                                     ("요 통계", "요통", False), ("요통계", "요통", True), ("기 침체", "기침", False), ("무 좀 더", "무좀", False), ("무좀더", "무좀", True)):
            with self.subTest(text=text):
                self.assertEqual(read(text, word), expected)

    def test_the_boundary_tests_of_the_old_concepts_module_look_at_the_real_symptom_table(self):
        # D9: 낱말 경계 시험이 운영 표를 돌려야 낱말 가로지름을 잡는다 — 시험 모듈의 도우미가 운영 표 그대로를 쓴다
        import test_topics_concepts as tc
        rows = {name: table for name, table, _entries in tc.boundary_tables()}
        self.assertIs(rows["증상"], cn.Tables.s_weak)


class PrefixCompoundTest(unittest.TestCase):                                                                             # Z12 (D-309, 델타 재검증 D3·D4)
    def test_the_table_is_the_documented_initial_value(self):
        prefixes = cn.HEALTH_SYMPTOM_PREFIX_KO
        self.assertEqual(tuple(prefixes), ("감기", "설사", "요통", "기침", "복통", "치통", "습진", "무좀", "이명"))
        self.assertEqual({key: len(value) for key, value in prefixes.items()}, {"감기": 30, "설사": 26, "요통": 17, "기침": 23, "복통": 15, "치통": 11, "습진": 19, "무좀": 10, "이명": 8})
        self.assertEqual(sum(len(value) for value in prefixes.values()), 159)
        for symptom, modifiers in prefixes.items():
            self.assertIn(symptom, cn.HEALTH_SYMPTOM_START_KO + cn.HEALTH_SYMPTOM_BARE_KO)
            self.assertEqual(len(modifiers), len(set(modifiers)), "중복 없음")
            for modifier in modifiers:
                self.assertTrue(all("가" <= char <= "힣" for char in modifier), modifier)
        self.assertEqual(set(cn.Tables.symptom_prefix), set(prefixes))
        self.assertFalse(hasattr(cn, "HEALTH_SYMPTOM_COMPOUND_KO"), "D-309: 허용 합성어 25개 목록은 수식어 표가 갈음했다")
        self.assertEqual([word for word in COMPOUNDS if word not in {modifier + symptom for symptom, modifiers in prefixes.items() for modifier in modifiers}], [], "옛 허용 합성어 25개는 모두 수식어 + 증상이다")

    def test_the_old_allow_list_words_and_the_verifier_genuine_compounds_are_read_and_stop_with_a_claim(self):
        self.assertEqual(len(GENUINE_COMPOUNDS), 132)
        self.assertEqual(len(set(GENUINE_COMPOUNDS) | set(COMPOUNDS)), 157)
        for word in COMPOUNDS + GENUINE_COMPOUNDS:
            for text in (f"{obj(word)} 즉시 줄이는 방법", f"{word} 바로 없애는 방법", f"즉시 {obj(word)} 없애는 방법"):
                with self.subTest(text=text):
                    self.assertEqual(stage(text), STOP)
            self.assertEqual(stage(f"예시 {word} 글"), EVIDENCE if word in EVIDENCE_COMPOUNDS else MARK)

    def test_the_lookalike_words_stay_general_in_every_frame(self):
        self.assertEqual(len(LOOKALIKE_WORDS), 60)
        for word in LOOKALIKE_WORDS:
            for text in (word, f"{word} 정리하는 방법", f"{obj(word)} 즉시 줄이는 방법", f"{word} 바로 줄이는 방법", f"{word} 하루 만에 해결하는 방법"):
                with self.subTest(text=text):
                    self.assertEqual(stage(text), GENERAL)
                    self.assertEqual(cn.health_signals([text]).symptom, ())

    def test_a_modifier_must_be_the_whole_part_before_the_symptom_so_wrist_and_ankle_cold_words_are_not_read(self):
        for text in ("손목감기 보호대", "발목감기 테이프", "팔목감기 밴드", "손목감기를 즉시 줄이는 법", "고목감기 예방", "대목감기 방법", "개코감기 방법"):
            with self.subTest(text=text):
                self.assertEqual(cn.health_signals([text]).symptom, ())
                self.assertEqual(stage(text), GENERAL)
        for text in ("목감기 예방 마스크 고르는 기준", "목감기를 즉시 줄이는 법", "코감기 약 보관"):
            with self.subTest(text=text):
                self.assertIn("감기", cn.health_signals([text]).symptom)

    def test_a_modifier_is_tied_to_its_own_symptom_so_hair_washing_is_not_a_cold(self):
        self.assertIn("머리", cn.HEALTH_SYMPTOM_PREFIX_KO["무좀"])
        self.assertNotIn("머리", cn.HEALTH_SYMPTOM_PREFIX_KO["감기"])
        for text in ("머리감기 순서", "머리감기를 즉시 줄이는 법"):
            self.assertEqual(cn.health_signals([text]).symptom, (), text)
        self.assertIn("무좀", cn.health_signals(["머리무좀 치료"]).symptom)

    def test_the_bare_symptom_reads_a_suffix_word_after_it_but_not_a_name(self):
        for text, expected in (("이명현상 바로 줄이는 방법", STOP), ("이명소리를 즉시 줄이는 방법", STOP), ("이명치료 기록 노트", EVIDENCE), ("이명개선 운동", MARK), ("이명희 작가", GENERAL), ("이명수 감독", GENERAL), ("이명훈 선수", GENERAL), ("이명원 대표", GENERAL)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)

    def test_an_exact_modifier_is_needed_not_just_a_listed_one_somewhere_in_the_word(self):
        # 수식어가 낱말 처음부터 증상 바로 앞까지 정확히 같아야 한다 — 한 글자 더 붙으면(`고목`) 아니다
        for modifier, symptom in (("목", "감기"), ("심한", "설사"), ("주부", "습진"), ("발", "무좀"), ("마른", "기침")):
            self.assertEqual(cn.health_signals([f"예시 {modifier}{symptom}를 글"]).symptom, (symptom,))
            self.assertEqual(cn.health_signals([f"예시 고{modifier}{symptom}를 글"]).symptom, ())
            self.assertEqual(cn.health_signals([f"예시 {modifier}가{symptom}를 글"]).symptom, ())


class QuitStopRestoreTest(unittest.TestCase):                                                                            # Z13 (D-308, 델타 재검증 D5)
    NAMED = tuple(medicine for medicine in cn.HEALTH_MEDICINE_KO if medicine not in cn.HEALTH_MEDICINE_GENERIC_KO)
    OUTCOME = ("사라지는", "좋아지는", "개선하는", "해소하는", "해결하는")

    def test_the_tables_are_the_documented_initial_values(self):
        self.assertEqual(cn.HEALTH_QUIT_OUTCOME_KO, ("좋아지", "사라지", "없어지", "개선", "해소", "해결", "완화", "호전", "치유"))
        self.assertEqual(cn.HEALTH_MEDICINE_GENERIC_KO, ("의약품", "처방약", "치료제"))
        self.assertTrue(set(cn.HEALTH_MEDICINE_GENERIC_KO) <= set(cn.HEALTH_MEDICINE_KO))
        self.assertEqual(len(self.NAMED), 13)

    def test_a_drug_name_with_a_stop_phrase_and_an_outcome_word_is_a_claim_without_any_symptom_word(self):
        texts = [f"{medicine} {quit} {outcome} 방법" for medicine in self.NAMED for quit in cn.HEALTH_QUIT_KO for outcome in self.OUTCOME]
        self.assertEqual(len(texts), 13 * 13 * 5)
        self.assertEqual([text for text in texts if stage(text) != STOP], [])
        self.assertEqual(cn.health_signals(["수면제 끊고 사라지는 방법"]).quit, ("끊고",))

    def test_a_generic_word_or_a_quantity_verb_does_not_make_it_a_claim(self):
        for medicine in cn.HEALTH_MEDICINE_GENERIC_KO:
            for outcome in self.OUTCOME:
                text = f"{medicine} 끊고 {outcome} 방법"
                with self.subTest(text=text):
                    self.assertNotEqual(stage(text), STOP, "일반 낱말(의약품·처방약·치료제) 곁은 그대로다 — 1차 수정 머리 대비 한계다(D-306)")
                    self.assertEqual(cn.health_signals([text]).quit, ())
        for text in ("의약품 구독 끊고 비용 줄이는 방법", "수면제 끊고 줄이는 방법", "스테로이드 구독 끊고 비용 낮추는 방법", "인슐린 구독 끊고 비용 낮추는 방법", "진통제 구독 안 먹고 지출 줄이는 법"):
            with self.subTest(text=text):
                self.assertNotEqual(stage(text), STOP)

    def test_a_stop_phrase_makes_the_new_instant_phrases_count_beside_a_drug_like_the_old_words(self):
        instants = ("하루 만에", "단번에", "한 번에", "한꺼번에", "일주일 만에", "5분 만에", "금세", "며칠 만에", "먹자마자", "하룻밤에")
        predicates = ("건강해진 비결", "달라진 이야기")
        texts = [f"{medicine} {quit} {instant} {predicate}" for medicine in cn.HEALTH_MEDICINE_KO for quit in ("끊고", "안 먹고") for instant in instants for predicate in predicates]
        self.assertEqual(len(texts), 16 * 2 * 10 * 2)
        self.assertEqual([text for text in texts if stage(text) != STOP], [])
        for old in ("즉시", "바로", "당장"):
            self.assertEqual(stage(f"수면제 끊고 {old} 건강해진 비결"), STOP)

    def test_without_a_stop_phrase_or_with_an_action_verb_the_instant_phrases_still_do_not_count_beside_a_drug(self):
        for text, expected in (("수면제 하루 만에 품절되는 이유", MARK), ("혈압약 며칠 만에 배송되는 이유", EVIDENCE), ("수면제 구독 끊고 하루 만에 배송되는 이유", MARK), ("수면제 구독 끊고 하루 만에 정리하는 방법", MARK),
                               ("항우울제 일주일 만에 받는 방법", MARK), ("수면제 한 번에 두 알 먹는 방법", MARK)):
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected)

    def test_the_stopping_signal_lists_the_stop_phrases_only_when_a_drug_word_is_there(self):
        self.assertEqual(cn.health_signals(["수면제 끊고 하루 만에 건강해진 비결"]).stopping, ("끊고",))
        self.assertEqual(cn.health_signals(["영양제 끊고 하루 만에 건강해진 비결"]).stopping, ())
        self.assertEqual(cn.health_signals(["수면제 하루 만에 품절되는 이유"]).stopping, ())
        self.assertEqual(cn.health_signals(["수면제 안 먹고 먹지 않아도 되는 방법"]).stopping, ("안 먹고", "먹지 않아도"))


class SolveVerbSymptomTest(unittest.TestCase):                                                                           # Z14 (D-310, 델타 재검증 D6)
    def effects(self, text):
        return [scope for _entry, _kind, scope in cn.health_signals([text]).scoped if scope == "effect"]

    def test_a_solve_verb_beside_a_new_instant_phrase_is_an_effect_when_a_symptom_is_the_object(self):
        for text in ("어깨 결림을 한 번에 풀어보는 스트레칭", "기침을 한 번에 풀어보는 가이드", "스트레스를 한꺼번에 풀어보는 체크리스트", "두통을 하루 만에 풀어보는 앱", "불면을 일주일 만에 풀어보는 노트", "영양제로 두통을 한 번에 풀어보는 방법"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)
                self.assertTrue(self.effects(text))

    def test_it_is_still_an_action_for_a_product_or_a_disease_or_a_quiz(self):
        for text in ("크레아틴 단번에 풀어보는 템플릿", "홍삼 먹자마자 풀어보는 퀴즈", "당뇨 한 번에 풀어보는 가이드", "비타민 한꺼번에 문제 풀어보는 앱", "오메가3 단번에 풀어보는 노트"):
            with self.subTest(text=text):
                self.assertNotEqual(stage(text), STOP)
                self.assertEqual(self.effects(text), [])

    def test_the_old_instant_words_keep_reading_the_solve_verb_as_an_effect(self):
        for text in ("스트레스를 즉시 풀어보는 방법", "피로를 바로 풀어주는 방법", "스트레스를 한 번에 풀어주는 방법"):
            with self.subTest(text=text):
                self.assertEqual(stage(text), STOP)

    def test_a_symptom_outside_the_object_window_does_not_turn_the_quiz_reading_into_an_effect(self):
        # 증상이 대상 창(즉각 표현 앞 두 낱말부터 서술어 끝까지) 밖에 있으면 퀴즈 읽기는 행동 그대로다 — 단계는 기준과 같은 근거 확인 필요(제품 + 증상)
        for text in ("크레아틴 단번에 풀어보는 템플릿 두통 정리", "두통 정리 크레아틴 단번에 풀어보는 템플릿"):
            with self.subTest(text=text):
                self.assertEqual(self.effects(text), [])
                self.assertEqual(stage(text), EVIDENCE)

class KnownLimitTest(unittest.TestCase):                                                                                 # Z8 (D-306) — 한계를 못박는다: 고치면 이 시험이 의식적으로 함께 바뀐다
    LIMITS = (
        ("설사 실패해도 바로 줄이는 방법", STOP, "`설사`(가령·비록)가 부사로 쓰인 글 — 낱말 처음이라 증상으로 읽힌다(P-7 남은 것)"),
        ("설사 같은 일이 일어나더라도 침착하게 대응하는 방법", MARK, "같은 한계 — 표시만이다"),
        ("실 감기 쉬운 도구 소개", MARK, "띄어 쓴 `실 감기`(실을 감는 일)는 마스크가 없다 — `거실 감기` 처럼 진짜 증상이 가려지기 때문(표시만)"),
        ("이명은 감독 작품 정리", MARK, "이름 셋째 글자가 조사 글자(`은`)인 사람은 `이명`(증상)으로 읽힌다 — 이름 `이명희`·`이명수` 는 거른다"),
        ("영양제 하루 만에 사라지는 가격 이유", STOP, "`사라지` 는 건강 결과 서술어 어간이라 제품 곁 `사라지는 가격` 도 효과로 읽힌다(P-8 남은 것)"),
        ("수면 100% 차단 귀마개", STOP, "`차단` 은 소음·광고도 막는 말인데 건강 낱말(수면)이 두 낱말 안이면 읽는다(P-1 남은 것)"),
        ("인슐린 구독 끊고 스트레스 줄이는 앱", STOP, "`스트레스` 가 증상 낱말이라 처방약 + 중단 + 줄이는 앱 도 단정으로 읽는다(P-6 남은 것)"),
        ("고지혈증 약 끊고 콜레스테롤 낮추는 방법", EVIDENCE, "`약` 만으로는 처방약 낱말이 아니라(표 밖) 복용 중단 단정이 걸리지 않는다"),
        ("소화불량이 곧바로 끝납니다", MARK, "`끝납니다`(끝나다)는 결과 서술어 어간에 없다"),
        ("체중 한 달 만에 5kg 감량", MARK, "증상뿐인 대상 + 효과 낱말이 대상 바로 뒤가 아니면 즉각 표현의 보충 읽기가 읽지 않는다"),
        ("비염 즉시 뚫리는 방법", EVIDENCE, "`뚫리` 는 결과 서술어 어간에 없다(질환만 있어 근거 확인 필요)"),
        ("통풍 단번에 해결하는 방법", GENERAL, "`통풍` 은 표에 없다(`통풍 발작`·`통풍 환자` 만 있다)"),
        ("스트레스를 즉시 풀어보는 방법", STOP, "옛 범위 낱말 곁에서는 `풀어보는`(퀴즈)도 `풀어` 로 읽는다 — 옛 중지를 낮추지 않는다"),
        ("두통을 바로 없애는지도", MARK, "붙여 쓴 `지도` 는 `는지`+조사 `도` 와 구별되지 않아 의문으로 읽는다"),
        ("통증 100% 해결되지 않는 이유", STOP, "`100%` 는 옛 코드처럼 부정·의문의 영향을 받지 않는다 — `통증 100% 줄이지 못하는 이유` 가 옛 코드에서도 중지인 것과 같다(결과 서술어도 같은 방식)"),
        # ---- 3차 수정(D-307–D-311) 뒤 남은 한계 — D-306 ⑪–⑯
        ("두통 자세히 즉시 없애는 방법", MARK, "D1 남은 것: 기준(main)부터 있던 한 낱말 마스크 24개가 글을 갈라 `증상 + 마스크 + 즉시` 를 표시만으로 낮춘다 — 기준과 같다(이 묶음이 더한 마스크는 모두 두 낱말)"),
        ("이 명 을 즉 시 줄 이 는 방 법", GENERAL, "D2 남은 것: 글자를 하나씩 띄운 글은 증상으로 읽지 않는다 — 2차 머리가 읽던 변이 글 8개가 내려갔다(기준에는 없던 새 낱말이라 기준 대비 하락은 아니다)"),
        ("목감기띠를 즉시 줄이는 법", STOP, "D4 남은 것: `목감기` 로 시작하는 낱말은 모두 읽는다 — `목감기띠`(목에 두르는 띠)도 걸린다"),
        ("환절기목감기를 즉시 줄이는 방법", GENERAL, "D3 남은 것: 수식어가 둘 붙은 합성어는 읽지 않는다 — 수식어 표는 낱말 처음에서 증상 낱말 앞까지가 수식어 하나와 정확히 같을 때만 읽는다"),
        ("꽃샘감기를 즉시 줄이는 방법", GENERAL, "D3 남은 것: 수식어 표에 없는 수식어(`꽃샘`)는 읽지 않는다(표는 초기값 — 운영자 확인)"),
        ("의약품 끊고 좋아지는 방법", EVIDENCE, "D5 남은 것: 일반 낱말(의약품·처방약·치료제) 곁은 결과어가 있어도 중지가 아니다"),
        ("수면제 끊고 줄이는 방법", EVIDENCE, "D5 남은 것: 약 이름 + 복용 중단 + `줄이는`·`낮추는` 같은 일반 효과 낱말만이면 근거 확인 필요다 — 1차 머리 대비 하락(중지 256 가운데 90)"),
        ("인슐린 구독 중단하고 비용 개선하는 방법", STOP, "D5 새 과탐: 약 이름 + 복용 중단 + 결과어(개선)는 비용 이야기여도 중지로 읽는다"),
        ("두통 퀴즈 한 번에 풀어보는 앱", STOP, "D6 남은 것: 증상 낱말이 대상 창 안에 있으면 `퀴즈` 가 있어도 효과로 읽는다 — 기준은 표시만이었다"),
        ("피로를 즉시 퇴치하는 방법", MARK, "D7: `제거`·`퇴치`·`차단`·`정복` 은 늘 단정 낱말 곁에서만 읽는다 — 즉각 표현 곁은 기준과 같다(하락 아님)"),
        ("통증을 단번에 차단하는 방법", MARK, "D7: 같은 한계 — 기준과 같다"),
    )

    def test_each_known_limit_is_pinned_with_its_current_stage(self):
        for text, expected, why in self.LIMITS:
            with self.subTest(text=text):
                self.assertEqual(stage(text), expected, why)
        self.assertEqual(len({text for text, _stage, _why in self.LIMITS}), len(self.LIMITS))

    def test_the_limits_are_written_in_the_decision_d306(self):
        row = next(line for line in (ts.ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8").splitlines() if line.startswith("| D-306 |"))
        for needle in ("DEFERRED", "는 지", "지도", "설사", "실 감기", "사라지는 가격", "차단", "스트레스", "끝납니다", "뚫리", "통풍", "풀어보는", "이명은",
                       "자세히", "이 명 을 즉 시", "목감기띠", "환절기목감기", "꽃샘감기", "의약품", "수면제 끊고 줄이는 방법", "인슐린 구독 중단하고 비용 개선하는 방법", "두통 퀴즈 한 번에 풀어보는 앱", "퇴치", "기준과 같다"):
            self.assertIn(needle, row)


class DocumentsTest(unittest.TestCase):                                                                                  # Y9·Z9
    ROUND_ONE = {
        "D-290": ("의문 꼬리", "지압법", "는지", "가이드", "낱말 경계", "_asks_after", "두통을 바로 없애는 지압법", "위임 규칙 근거"),
        "D-291": ("증상 열세 개", "질환 다섯 개", "마스크", "노안", "체력", "초기값", "운영자 확인", "위임 규칙 근거"),
        "D-292": ("해결 보장", "요통 100% 해결 보장", "효과 낱말 표", "영양제 오류 해결", "test_topics_corpus", "위임 규칙 근거"),
        "D-293": ("단번에", "한 번에", "한꺼번에", "하루 만에", "옛 중지 바닥", "곧바로", "HEALTH_INSTANT_UNKNOWN_KO", "위임 규칙 근거"),
        "D-294": ("처방약", "안전 우선", "당뇨약 안 먹고 낫는 방법", "고혈압약 끊어도 되는 방법", "끊어도 되나요", "운영자 확인", "위임 규칙 근거"),
        "D-295": ("변이", "회귀", "일상 문장", "바이트", "시험", "3.10", "위임 규칙 근거", "검증한 말뭉치 안에서"),
        "D-296": ("DEFERRED", "한계", "하룻밤", "풀다", "S + 하루 만에", "영어", "위임 규칙 근거", "D-298–D-306"),
    }
    ROUND_TWO = {
        "D-298": ("HEALTH_RESOLVE_KO", "체중 앱 오류 100% 해결", "800", "효과 낱말 표", "영양제 오류 해결", "floor_key", "위임 규칙 근거"),
        "D-299": ("HEALTH_INSTANT_UNKNOWN_KO", "탈출", "멈추", "영양제 하루 만에 품절되는 이유", "풀어보는", "V13", "건강 낱말 조각", "한 번에 유방암 치료", "위임 규칙 근거"),
        "D-300": ("HEALTH_INSTANT_MORE_KO", "HEALTH_INSTANT_NUMBERED_KO", "일주일 만에", "분만에", "한방에서", "운영자 확인 항목", "위임 규칙 근거"),
        "D-301": ("_question_closed", "없애는지압법", "384", "지도", "는 지", "위임 규칙 근거"),
        "D-302": ("HEALTH_QUIT_CURE_KO", "HEALTH_QUIT_OK_KO", "의약품 구독 끊고 비용 줄이는 방법", "2,880", "운영자 확인 항목", "위임 규칙 근거"),
        "D-303": ("HEALTH_SYMPTOM_START_KO", "HEALTH_SYMPTOM_COMPOUND_KO", "이명희", "체감기온", "52 → 59", "56 → 66", "바로잡", "목감기", "위임 규칙 근거"),
        "D-304": ("_SpanIndex", "_Spans", "5.9초", "(?<![0-9])", "SpeedTest", "위임 규칙 근거"),
        "D-305": ("변이", "회귀", "일상 손글", "정직", "3.10", "위임 규칙 근거"),
        "D-306": ("DEFERRED", "KnownLimitTest", "는 지", "지도", "설사", "실 감기", "사라지는 가격", "차단", "스트레스", "끝납니다", "뚫리", "통풍", "풀어보는", "이명은", "⑪", "⑯"),
    }

    ROUND_THREE = {
        "D-307": ("한눈에", "첫눈에", "눈 건강", "wordstart", "설 사진", "154", "SEP", "66 → 64", "_bare_diseases", "24개", "36만 6천", "위임 규칙 근거"),
        "D-308": ("HEALTH_QUIT_OUTCOME_KO", "HEALTH_MEDICINE_GENERIC_KO", "stopping", "수면제 끊고 좋아지는 방법", "4,800", "256", "90", "인슐린 구독 중단하고 비용 개선하는 방법", "운영자 확인", "위임 규칙 근거"),
        "D-309": ("HEALTH_SYMPTOM_PREFIX_KO", "159", "목감기띠", "손목감기", "396", "환절기목감기", "BARE_SYMPTOM_REST_KO", "운영자 확인", "위임 규칙 근거"),
        "D-310": ("풀어보는", "어깨 결림을 한 번에 풀어보는 스트레칭", "두통 퀴즈 한 번에 풀어보는 앱", "27", "위임 규칙 근거"),
        "D-311": ("변이", "회귀", "정직", "36만 6천", "53", "3.10", "합성 병합", "D-305", "위임 규칙 근거"),
    }

    def rows(self):
        text = (ts.ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        return text, {line.split(" | ")[0].lstrip("| "): line for line in text.splitlines() if line.startswith("| D-")}

    def test_the_decisions_d290_to_d296_exist_once_after_d279_and_say_what_they_decided(self):
        text, rows = self.rows()
        found = [line.split(" | ")[0].lstrip("| ") for line in text.splitlines() if line.startswith("| D-")]
        for number, words in self.ROUND_ONE.items():
            with self.subTest(decision=number):
                self.assertEqual(found.count(number), 1)
                self.assertGreater(found.index(number), found.index("D-279"))
                for word in words:
                    self.assertIn(word, rows[number])
        self.assertEqual([item for item in found if item in self.ROUND_ONE], list(self.ROUND_ONE))
        for number in self.ROUND_ONE:
            status = rows[number].rsplit(" | ", 1)[1]
            self.assertEqual([word for word in ("FIXING", "DECISION_REQUIRED", "DEFERRED", "VERIFIED", "CLOSED") if word in status], ["DEFERRED"] if number == "D-296" else ["FIXING"], "상태 낱말은 하나 — 독립 검증 전이라 FIXING, 알려진 한계 D-296 은 DEFERRED")

    def test_the_decisions_d298_to_d306_exist_once_after_d296_and_say_what_they_decided(self):
        text, rows = self.rows()
        found = [line.split(" | ")[0].lstrip("| ") for line in text.splitlines() if line.startswith("| D-")]
        for number, words in self.ROUND_TWO.items():
            with self.subTest(decision=number):
                self.assertEqual(found.count(number), 1)
                self.assertGreater(found.index(number), found.index("D-296"))
                for word in words:
                    self.assertIn(word, rows[number])
        self.assertEqual([item for item in found if item in self.ROUND_TWO], list(self.ROUND_TWO), "번호 순서대로")
        for number in self.ROUND_TWO:
            status = rows[number].rsplit(" | ", 1)[1]
            self.assertEqual([word for word in ("FIXING", "DECISION_REQUIRED", "DEFERRED", "VERIFIED", "CLOSED") if word in status], ["DEFERRED"] if number == "D-306" else ["FIXING"])

    def test_the_decisions_d307_to_d311_exist_once_after_d306_and_say_what_they_decided(self):
        text, rows = self.rows()
        found = [line.split(" | ")[0].lstrip("| ") for line in text.splitlines() if line.startswith("| D-")]
        for number, words in self.ROUND_THREE.items():
            with self.subTest(decision=number):
                self.assertEqual(found.count(number), 1)
                self.assertGreater(found.index(number), found.index("D-306"))
                for word in words:
                    self.assertIn(word, rows[number])
        self.assertEqual([item for item in found if item in self.ROUND_THREE], list(self.ROUND_THREE), "번호 순서대로")
        for number in self.ROUND_THREE:
            status = rows[number].rsplit(" | ", 1)[1]
            self.assertEqual([word for word in ("FIXING", "DECISION_REQUIRED", "DEFERRED", "VERIFIED", "CLOSED") if word in status], ["FIXING"])
        for needle in ("목감기띠", "환절기목감기", "수면제 끊고 줄이는 방법", "인슐린 구독 중단하고 비용 개선하는 방법", "두통 퀴즈 한 번에 풀어보는 앱", "피로를 즉시 퇴치하는 방법", "자세히", "이 명 을 즉 시", "D-308", "D-309"):
            self.assertIn(needle, rows["D-306"], "3차 수정 뒤 남은 한계와 새로 받을 결정을 D-306 이 적는다")

    def test_the_honest_wording_fixes_are_in_the_old_rows(self):
        _text, rows = self.rows()
        self.assertIn("그 집합들 안에서", rows["D-305"])
        self.assertIn("53건", rows["D-305"])
        self.assertNotIn("**내려간 글 0**. 건강 낱말이 없는 글은", rows["D-305"], "과장이던 문장은 바로잡았다")
        self.assertIn("수정 라운드 D-303 이 읽게 했다", rows["D-296"])
        self.assertNotIn("`복통`·`구토`·`콧물`·`무좀`·`습진`·`충치`", rows["D-296"], "낡은 문장(`복통`·`콧물`·`무좀`·`습진` 이 아직 읽히지 않는다)은 고쳤다")
        self.assertIn("①(`복통`·`콧물`·`무좀`·`습진` → D-303)", rows["D-296"])
        self.assertIn("3차 수정에서", rows["D-303"])

    def test_the_new_text_has_no_tilde_and_no_link(self):
        # 이 묶음이 쓴 글(D-290–D-311 행·변경 기록 세 항목·머리말의 이 묶음 문단)에는 물결표(~)와 링크가 없다 — 범위는 en dash 로 쓴다
        _text, rows = self.rows()
        for number in list(self.ROUND_ONE) + list(self.ROUND_TWO) + list(self.ROUND_THREE):
            with self.subTest(decision=number):
                self.assertNotIn("~", rows[number])
                self.assertNotIn("http", rows[number])
        log = (ts.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        for title in ("**건강 판정 미탐 보강**", "**건강 판정 미탐 보강 — 수정 라운드**", "**건강 판정 미탐 보강 — 3차 수정**"):
            entry = next(line for line in log.splitlines() if title in line)
            self.assertNotIn("~", entry)
            self.assertNotIn("http", entry)
        for module in (cn, sf):
            header = Path(module.__file__).read_text(encoding="utf-8").split('"""', 2)[1]
            mine = header[header.index("**미탐 보강(WP-B5"):]
            self.assertNotIn("~", mine)
            self.assertNotIn("http", mine)

    def test_no_other_number_between_d290_and_d319_is_used_here_except_the_one_another_work_package_owns(self):
        # D-297 은 다른 묶음(P4e)이 쓰는 번호다 — 병합 때 겹치지 않게 이 묶음은 D-290–D-296 과 D-298–D-311 만 쓴다(D-297 이 있어도 시험은 그대로 통과한다)
        text, _rows = self.rows()
        found = [line.split(" | ")[0].lstrip("| ") for line in text.splitlines() if line.startswith("| D-")]
        mine = set(self.ROUND_ONE) | set(self.ROUND_TWO) | set(self.ROUND_THREE)
        others = {item for item in found if len(item) == 5 and item[:4] in ("D-29", "D-30", "D-31") and item not in mine}
        self.assertTrue(others <= {"D-297"}, others)
        for number in mine:
            self.assertEqual(found.count(number), 1, f"{number} 은 한 번씩만 — 다른 묶음의 행이 같은 번호를 쓰면 병합 때 이 시험이 알려 준다")

    def test_the_decision_table_numbers_equal_the_table_sizes_in_the_code(self):
        _text, rows = self.rows()
        for needle in ("증상 39 → 52", "질환 71 → 76", "마스크 48 → 56", "효과 단정 서술 16 → 19"):
            with self.subTest(needle=needle):
                self.assertIn(needle, rows["D-291"] + rows["D-292"], "그때(D-291·D-292)의 값")
        self.assertEqual((len(cn.HEALTH_SYMPTOM_KO), len(cn.HEALTH_DISEASE_KO), len(cn.HEALTH_MASKS_KO), len(cn.HEALTH_ASSERT_EFFECT_KO)), (59, 76, 64, 19))
        for needle in (f"52 → {len(cn.HEALTH_SYMPTOM_KO)}", "56 → 66"):
            with self.subTest(needle=needle):
                self.assertIn(needle, rows["D-303"], "그때(D-303)의 값")
        self.assertIn(f"66 → {len(cn.HEALTH_MASKS_KO)}", rows["D-307"], "3차 수정(D-307)의 값")
        text = (ts.ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
        size_line = next(line for line in text.splitlines() if line.startswith("표 크기(WP-B5 3차 수정 뒤"))
        for needle in (f"건강 마스크 {len(cn.HEALTH_MASKS_KO)}", f"증상 {len(cn.HEALTH_SYMPTOM_KO)}", f"질환 {len(cn.HEALTH_DISEASE_KO)}", f"낱말 처음 증상 {len(cn.HEALTH_SYMPTOM_START_KO)}", f"증상 앞 수식어 {sum(len(words) for words in cn.HEALTH_SYMPTOM_PREFIX_KO.values())}",
                       f"뒤따르는 말 시작 {len(cn.BARE_SYMPTOM_REST_KO)}", f"복용 중단 결과어 {len(cn.HEALTH_QUIT_OUTCOME_KO)}", f"일반 약 낱말 {len(cn.HEALTH_MEDICINE_GENERIC_KO)}"):
            self.assertIn(needle, size_line)
        self.assertIn(f"338 → {len(cn.HEALTH_RESULT_SCOPE_KO)}", rows["D-299"])

    def test_the_changelog_has_one_entry_per_round_and_the_module_headers_name_the_work(self):
        log = (ts.ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertEqual(log.count("**건강 판정 미탐 보강**"), 1)
        entry = next(line for line in log.splitlines() if "**건강 판정 미탐 보강**" in line)
        for needle in ("WP-B5", "D-290", "D-296", "지압법", "의문 꼬리", "증상", "즉각 표현", "처방약", "초기값", "운영자 확인", "변이", "T2"):
            self.assertIn(needle, entry)
        self.assertNotIn("건강 낱말이 없는 글은 한 글자도 같음)", entry, "그 말뭉치 안에서만 같았다 — 정직한 표현(독립 검증 P-13)")
        self.assertIn("그 말뭉치 안에서", entry)
        self.assertEqual(log.count("**건강 판정 미탐 보강 — 수정 라운드**"), 1)
        second = next(line for line in log.splitlines() if "**건강 판정 미탐 보강 — 수정 라운드**" in line)
        for needle in ("WP-B5 2", "D-298", "D-306", "T2", "초기값", "운영자 확인 전", "체감기온", "요통 100% 해결", "영양제 하루 만에 품절되는 이유", "5.9초"):
            self.assertIn(needle, second)
        self.assertEqual(log.count("**건강 판정 미탐 보강 — 3차 수정**"), 1)
        third = next(line for line in log.splitlines() if "**건강 판정 미탐 보강 — 3차 수정**" in line)
        for needle in ("WP-B5 3", "D-307–D-311", "T2", "초기값", "운영자 확인 전", "한눈에", "손목감기", "36만 6천", "53", "증상별 앞 수식어 표", "D-306"):
            self.assertIn(needle, third)
        header = Path(cn.__file__).read_text(encoding="utf-8").split('"""', 2)[1]
        for needle in ("WP-B5", "D-290", "HEALTH_INSTANT_PHRASE_KO", "HEALTH_QUIT_", "운영자 확인 전", "_asks_after", "수정 라운드", "D-298", "D-306", "HEALTH_RESOLVE_KO", "HEALTH_SYMPTOM_START_KO", "_question_closed", "_SpanIndex",
                       "3차 수정", "D-307–D-311", "HEALTH_SYMPTOM_PREFIX_KO", "wordstart", "HEALTH_QUIT_OUTCOME_KO"):
            self.assertIn(needle, header)
        self.assertNotIn("HEALTH_SYMPTOM_COMPOUND_KO)·증상 일곱 더함", header, "허용 목록 문장은 수식어 표로 바뀐 것을 알린다")
        safety_header = Path(sf.__file__).read_text(encoding="utf-8").split('"""', 2)[1]
        self.assertIn("WP-B5", safety_header)
        self.assertIn("D-298–D-306", safety_header)
        self.assertIn("D-307–D-311", safety_header)
        plan = (ts.ROOT / "docs" / "TOPIC_ENGINE_PLAN.md").read_text(encoding="utf-8")
        self.assertIn("D-290–D-311", plan)
        self.assertLessEqual(len(plan.splitlines()), 400, "계획 문서는 400줄을 넘기지 않는다")
        self.assertIn("D-290–D-311", (ts.ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
