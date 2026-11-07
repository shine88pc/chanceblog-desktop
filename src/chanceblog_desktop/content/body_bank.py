"""본문 생성의 분야 낱말과 분야별 '확인할 항목' 목록(순수 자료 — 파일·네트워크·시계·난수 없음).

본문은 후보의 키워드밖에 모른다(제품인지 장소인지 문제인지 글자만으로는 알 수 없다). 그래서 키워드(와 주제·보조 키워드)에서 **분야**를 낱말로 읽고(`domain_of`), 분야마다 '무엇을 확인할지'
('확인 없이도 참이 되는 일반적·구조적 항목')를 적어 둔 목록(`BANKS`)을 문단의 구체적 낱말로 쓴다. 목록에는 사양·가격·평가·수치·효과를 말하는 낱말이 없고 모두 명사구다(시험이 전수 확인한다).

**분야는 확실히 읽을 수 있을 때만 읽는다**(독립 검증 H1): 후보의 글을 낱말 단위(띄어쓰기로 나뉜 한글 덩어리·영문 덩어리)로 쪼개 낱말 경계에서만 맞추고(`청소기를`·`무선청소기` 는 '청소기', `한 도시` 는 '한도' 가 아니다),
뜻이 둘로 갈리는 낱말(`프로그램`·`설정`·`설치`·`한도`·`카페` …)은 신호로 쓰지 않으며, 둘 이상의 분야가 비슷하게 읽히면 읽지 않는다. 못 읽으면 `generic`(일반) 이고 일반 틀만 쓴다 —
채널 프로필의 주제·역할은 분야를 짐작하는 데 쓰지 않는다(블로그의 주제가 글의 주제가 되어 엉뚱한 분야 문장이 나오는 일이 없게). 분야 전용 낱말은 이 파일의 목록(`BANKS`)에만 있고 문장 틀에는 없다(시험이 지킨다).
협찬 가능 분야 태그(`monetization_focus`)와 분야의 대응(`FOCUS_TAGS`)도 여기에 있다 — 후보의 분야가 프로필의 협찬 가능 분야에 해당하면 협찬 자리 안내만 확인 권장에 둔다.
건강·금융·법률 낱말(`SENSITIVE_WORDS`)이 키워드에 있으면 주의사항에 '일반 정보만 다뤘으니 전문가·공식 기관에 확인' 문단이 들어간다(조언을 만들지 않는다). 후보의 글에 단정·최상급·효과 낱말(`ASSERTION_WORDS`)이 있으면
본문이 그 낱말을 그대로 되풀이하므로 확인 권장 맨 위에 경고를 한 줄 둔다.
"""
from __future__ import annotations

import re
import unicodedata

DOMAINS = ("appliance", "pc_hw", "software", "travel", "life", "generic")
GENERIC = "generic"
DOMAIN_KO = {"appliance": "생활가전", "pc_hw": "PC·기기", "software": "소프트웨어·서비스", "travel": "여행·장소", "life": "생활 문제", "generic": "일반"}
# 분야를 알려 주는 낱말 — 한 낱말(띄어쓰기로 나뉜 덩어리)이 이것과 같거나, 이것에 조사가 붙었거나('청소기를'), 이것으로 끝나는 합성어('무선청소기')일 때만 맞는다. 띄어쓰기가 든 항목은 낱말 둘 이상(구)이다.
# 뜻이 둘로 갈리는 낱말은 일부러 뺐다(프로그램 — 운동 프로그램·설정 — 목표 설정·설치 — 가구 설치·한도·업데이트·오류·코드·계정·구독·요금제·토큰·연동·개발·배포·저장소·카페·동네·절약·배수·부품·거치대·쿨러·믹서·블렌더·스팀·스크립트 …).
# 영문은 글자·숫자 덩어리가 낱말과 똑같을 때만 맞는다 — 영문 'ai' 가 'email' 속에 든 것을 분야 신호로 읽지 않으려는 것이다.
TRIGGERS_KO = {
    "appliance": ("가전", "청소기", "제습기", "가습기", "공기청정기", "에어프라이어", "전기밥솥", "밥솥", "커피머신", "선풍기", "서큘레이터", "히터", "전기장판", "냉장고", "세탁기", "건조기", "식기세척기", "인덕션",
                  "전자레인지", "믹서기", "토스터", "정수기", "드라이기", "면도기", "다리미", "에어컨", "보일러", "로봇청소기", "온풍기", "전기포트", "청소 로봇"),
    "pc_hw": ("그래픽카드", "그래픽 카드", "메인보드", "파워서플라이", "모니터", "키보드", "마우스", "노트북", "데스크탑", "데스크톱", "웹캠", "헤드셋", "이어폰", "충전기", "케이블", "공유기", "보조배터리",
              "스마트폰", "태블릿", "주변기기", "스피커", "프린터", "외장하드", "저장장치", "컴퓨터", "하드웨어", "메모리"),
    "software": ("챗봇", "생성형", "소프트웨어", "업무 자동화", "매크로", "깃허브", "엑셀", "노션", "워크플로", "워크플로우", "클라우드", "파이썬", "플러그인", "확장프로그램", "확장 프로그램", "프롬프트", "앱"),
    "travel": ("숙소", "호텔", "펜션", "리조트", "게스트하우스", "여행", "캠핑", "글램핑", "맛집", "식당", "공원", "박물관", "미술관", "전시", "축제", "명소", "관광", "드라이브 코스", "당일치기", "주차", "체크인",
               "해수욕장", "온천", "스키장", "등산", "산책", "도서관", "여행지", "근교", "숙박", "야경", "전망대"),
    "life": ("곰팡이", "결로", "냄새", "얼룩", "누수", "배수구", "수납", "빨래", "세탁법", "환기", "습기", "벌레", "소음", "층간소음", "단열", "방한용품", "방한 용품", "난방", "난방비", "전기요금", "관리비", "정리정돈",
             "청소법", "청소 방법", "생활비", "해충"),
}
TRIGGERS_EN = {
    "appliance": ("dehumidifier", "humidifier", "purifier", "airfryer", "vacuum", "heater", "fridge", "washer", "dryer"),
    "pc_hw": ("gpu", "cpu", "ram", "vram", "ssd", "hdd", "nvme", "usb", "hdmi", "pc", "monitor", "keyboard", "mouse", "laptop", "nas", "router", "webcam", "headset", "wifi", "bluetooth", "motherboard", "psu"),
    "software": ("ai", "llm", "chatgpt", "gemini", "claude", "saas", "api", "github", "git", "python", "notion", "excel", "vpn", "app", "sdk", "cli", "docker", "windows", "android", "ios", "copilot", "prompt", "bot"),
    "travel": ("hotel", "camping", "resort", "trip", "travel"),
    "life": (),
}
# 분야 → 협찬 가능 분야 태그(`ChannelProfile.monetization_focus` 의 값) — 후보의 분야가 프로필의 협찬 가능 분야에 해당하는지 본다
FOCUS_TAGS = {
    "appliance": ("small_appliance",), "pc_hw": ("pc_peripheral", "pc_parts"), "software": ("ai_service", "work_automation"), "travel": ("lodging_travel",), "life": (), "generic": (),
}
# 한 낱말 뒤에 붙어도 같은 낱말로 읽는 조사·어미(닫힌 목록) — '청소기를'·'제습기의' 는 낱말 '청소기'·'제습기' 다
PARTICLES = ("은", "는", "이", "가", "을", "를", "의", "에", "에서", "에게", "에는", "에도", "에서는", "에서도", "로", "으로", "로는", "으로는", "로도", "으로도", "와", "과", "도", "만", "까지", "부터", "처럼", "보다",
             "마다", "라도", "이라도", "이나", "나", "이란", "란", "랑", "이랑", "라는", "이라는", "라고", "이라고", "라면", "이라면", "이며", "며", "하고", "엔")
_PARTICLES_LONG_FIRST = tuple(sorted(PARTICLES, key=len, reverse=True))
DOMINANCE = 1.5                                # 가장 높은 분야의 점수가 둘째 분야의 점수의 이만큼 이상일 때만 읽는다(비슷하게 읽히면 일반 — '노트북 소음' 은 3 대 2 라 노트북, '곰팡이 제습기' 는 3 대 3 이라 일반)
_HANGUL_WORD = re.compile("[가-힣]+")
_LATIN_WORD = re.compile("[a-z0-9]+")


def squash(text):
    """비교하는 모양 — 호환 문자를 풀고(NFKC) 모든 공백을 없애고 소문자로."""
    return "".join(unicodedata.normalize("NFKC", str(text)).split()).casefold()


def _normalized(texts):
    return [unicodedata.normalize("NFKC", str(text)).casefold() for text in texts if text]


def _stems(word):
    """낱말 하나 → 그 낱말과, 끝의 조사를 하나 뗀 꼴들('무선청소기를' → '무선청소기를'·'무선청소기')."""
    found = [word]
    for particle in _PARTICLES_LONG_FIRST:
        if word.endswith(particle) and len(word) > len(particle):
            found.append(word[:-len(particle)])
    return found


def _span_in(word, trigger):
    """낱말 안에서 `trigger` 가 맞는 자리(시작, 끝) — 낱말과 같거나, 조사를 떼면 같거나, 두 글자 이상의 낱말로 끝나는 합성어일 때만. 아니면 None. 낱말 한가운데·앞머리는 맞추지 않는다('한도시' 속의 '한도' 는 아니다)."""
    for stem in _stems(word):
        if stem == trigger:
            return 0, len(trigger)
        if len(trigger) >= 2 and stem.endswith(trigger):
            return len(stem) - len(trigger), len(stem)
    return None


def _korean_matches(texts, labeled):
    """`labeled`((이름표, 낱말) 쌍 — 낱말에 띄어쓰기가 있으면 낱말 둘 이상의 구)가 `texts` 에서 맞는 것들 — [(이름표, 낱말, 맞은 글자 수)]. 겹치면 긴 쪽만 센다('제습기' 와 그 끝의 '습기' 는 하나 — 이름표가 달라도)."""
    found = []
    for text in _normalized(texts):
        words = _HANGUL_WORD.findall(text)
        matches = []
        for label, trigger in labeled:
            parts = _HANGUL_WORD.findall(trigger)
            size = len(parts)
            for start in range(len(words) - size + 1):
                if size > 1 and words[start:start + size - 1] != parts[:-1]:
                    continue
                span = _span_in(words[start + size - 1], parts[-1])
                if span is None:
                    continue
                covered = {(start + shift, number) for shift in range(size - 1) for number in range(len(words[start + shift]))}
                covered |= {(start + size - 1, number) for number in range(*span)}
                matches.append((len("".join(parts)), label, trigger, covered))
        taken = set()
        for length, label, trigger, covered in sorted(matches, key=lambda item: -item[0]):
            if not covered & taken:
                taken |= covered
                found.append((label, trigger, length))
    return found


def korean_hits(texts, triggers):
    """한글 낱말 목록 `triggers` 가 `texts` 에서 낱말 경계로 맞는 것들 — [(낱말, 맞은 글자 수)]."""
    return [(trigger, length) for _label, trigger, length in _korean_matches(texts, [(word, word) for word in triggers])]


def latin_hits(texts, words):
    """영문 낱말 목록 `words` 가 `texts` 에서 글자·숫자 덩어리 하나와 똑같이 맞는 것들 — [(낱말, 글자 수)]."""
    runs = {run for text in _normalized(texts) for run in _LATIN_WORD.findall(text)}
    return [(word, len(word)) for word in words if word in runs]


def _scores(texts):
    """분야마다 맞은 낱말의 글자 수 합 — 한글 낱말은 모든 분야를 한꺼번에 맞춰 겹치면 긴 쪽만 센다."""
    scores = {domain: 0 for domain in DOMAINS}
    for domain, _trigger, length in _korean_matches(texts, [(domain, word) for domain in DOMAINS for word in TRIGGERS_KO.get(domain, ())]):
        scores[domain] += length
    for domain in DOMAINS:
        scores[domain] += sum(length for _word, length in latin_hits(texts, TRIGGERS_EN.get(domain, ())))
    return scores


def domain_of(texts):
    """후보의 글(키워드·주제·보조 키워드)에서 **확실히** 읽은 분야. 낱말이 하나도 없거나 둘 이상의 분야가 비슷하게 읽히면 `generic`(일반). 낱말이 길수록 무겁게 센다('그래픽카드' 가 'AI' 보다 분야를 더 잘 말한다).
    채널 프로필의 주제·역할 같은 후보 밖의 글로는 읽지 않는다(독립 검증 H1 — 블로그의 주제가 글의 분야가 되면 건강 글에 가전 문장이 나온다)."""
    scores = _scores(texts)
    ranked = sorted(DOMAINS[:-1], key=lambda domain: (-scores[domain], DOMAINS.index(domain)))
    best, second = ranked[0], ranked[1]
    if scores[best] <= 0 or (scores[second] > 0 and scores[best] < DOMINANCE * scores[second]):
        return GENERIC
    return best


def focus_hit(domain, monetization_focus):
    """분야가 프로필의 협찬 가능 분야 태그에 해당하는가."""
    return bool(set(FOCUS_TAGS.get(domain, ())) & set(monetization_focus or ()))


# ---- 건강·금융·법률 낱말 — 키워드에 있으면 주의사항에 전문가·공식 기관 확인 문단을 더한다 -----------------------------------------------------------
# 한글 낱말(두 글자 이상)은 띄어쓰기를 지운 글의 부분 문자열로 맞춘다('당뇨병'·'전세계약서' 같은 합성어를 잡으려는 것이다 — 안전한 쪽 기본값: 놓치는 것보다 한 줄 더 붙는 쪽).
# 한 글자 낱말(`SENSITIVE_SHORT`)과 영문 낱말(`SENSITIVE_EN`)은 낱말 경계로만 맞춘다('암호'·'암튼' 속의 '암', 'netflix' 속의 'etf' 는 신호가 아니다).
# 목록 밖의 낱말은 읽지 못한다(한계 — D-269): 이 목록은 시작 목록이고 후보의 글을 모두 읽는 사전이 아니다.
SENSITIVE_WORDS = {
    "health": ("영양제", "건강기능식품", "건강식품", "보충제", "비타민", "유산균", "의약품", "약국", "병원", "치료", "진료", "증상", "통증", "다이어트", "체중", "혈압", "혈당", "수면", "불면", "질환", "진단", "처방",
               "두통", "피로", "스트레스", "알레르기", "탈모", "임신", "육아", "의료",
               "당뇨", "비염", "아토피", "콜레스테롤", "관절", "우울", "공황장애", "불안장애", "치매", "골다공증", "지방간", "위염", "갑상선", "빈혈", "천식", "여드름", "변비", "안구건조", "갱년기", "항암",
               "항생제", "진통제", "해열제", "스테로이드", "한약", "시술", "수술", "성형", "임플란트", "라식", "보톡스", "예방접종", "백신", "건강검진"),
    "finance": ("투자", "주식", "코인", "가상자산", "대출", "보험", "연금", "세금", "환율", "펀드", "적금", "예금", "부동산", "신용", "재테크", "절세", "청약",
                "금리", "채권", "배당", "공모주", "레버리지", "마이너스통장", "주택담보", "분양", "재건축", "양도세", "소득세", "부가세", "연말정산", "세액공제", "상속세", "증여",
                "카드혜택", "리볼빙", "파산", "회생", "비트코인", "이더리움", "스테이킹", "퇴직연금", "저축"),
    "legal": ("법률", "소송", "계약서", "고소", "상속", "저작권", "특허", "세무", "임대차", "변호사", "판결", "벌금", "과태료", "법적", "약관",
              "이혼", "해고", "합의금", "퇴직금", "위자료", "양육권", "재산분할", "부당해고", "산재", "임금체불", "손해배상", "명예훼손", "모욕죄", "형사", "민사", "내용증명", "공증", "등기", "개인정보", "전세", "월세", "보증금",
              "상표", "근로계약", "근로기준법", "실업급여", "법원", "재판", "고발", "채무"),
}
SENSITIVE_SHORT = {"health": ("암",), "finance": (), "legal": ()}
SENSITIVE_EN = {"health": ("adhd",), "finance": ("etf", "isa", "irp"), "legal": ()}
SENSITIVE_KO = {"health": "건강", "finance": "금융", "legal": "법률"}


def sensitive_kind(texts):
    """키워드 쪽 글에서 읽은 민감 주제 — 'health'·'finance'·'legal'(낱말이 가장 많은 쪽, 동점이면 이 순서) 또는 None."""
    plain = squash(" ".join(str(text) for text in texts if text))
    counts = {kind: sum(1 for word in words if squash(word) in plain) + len(korean_hits(texts, SENSITIVE_SHORT[kind])) + len(latin_hits(texts, SENSITIVE_EN[kind])) for kind, words in SENSITIVE_WORDS.items()}
    best = max(counts, key=lambda kind: (counts[kind], -tuple(counts).index(kind)))
    return best if counts[best] else None


# ---- 단정·최상급·효과 낱말 — 후보의 글에 있으면 본문이 그대로 되풀이하므로 확인 권장 맨 위에 경고를 둔다(고치거나 거절하지 않는다) -------------------------------------------------
# 한글 낱말은 부분 문자열('효과적인'·'완벽한'·'최고급'), 낱말 경계로만 맞추는 낱말(`ASSERTION_BOUNDARY` — '가장자리' 속의 '가장' 은 아니다)과 영문 낱말은 따로. 목록에 없는 단정은 읽지 못한다(한계 — D-269).
ASSERTION_WORDS = ("최고", "최상", "최저", "최대", "최적", "최선", "압도", "완벽", "역대", "무조건", "반드시", "확실", "틀림없", "절대", "즉시", "즉각", "효과", "효능", "치료", "완치", "개선", "예방", "완화", "호전",
                   "회복", "해소", "보장", "베스트", "넘버원", "만능")
ASSERTION_BOUNDARY = ("가장", "제일")
ASSERTION_EN = ("best", "top")
_RANK_WORD = re.compile("(?<![0-9])1 ?(?:위|등)")           # '1위'·'1등' — 숫자 한 자리가 앞에 더 붙은 '11위' 는 아니다
RANK_WORD = "1위"
MAX_ASSERTION_SHOWN = 3


def assertion_hits(texts):
    """후보의 글에서 찾은 단정·최상급·효과 낱말 — 목록의 낱말(입력한 글이 아니라 고정 표의 낱말)을 목록 순서대로 최대 `MAX_ASSERTION_SHOWN` 개."""
    plain = squash(" ".join(str(text) for text in texts if text))
    found = [word for word in ASSERTION_WORDS if word in plain]
    found += [word for word, _length in korean_hits(texts, ASSERTION_BOUNDARY)]
    found += [RANK_WORD] if any(_RANK_WORD.search(text) for text in _normalized(texts)) else []
    found += [word for word, _length in latin_hits(texts, ASSERTION_EN)]
    return tuple(dict.fromkeys(found))[:MAX_ASSERTION_SHOWN]


# ---- 분야별 확인할 항목 — 모두 명사구(한 목록에서 서로 겹치지 않는다) ---------------------------------------------------------------------------------
# C 확인할 기준 · M 자주 하는 실수(…하는 것) · Z 가능한 원인 · W 확인할 곳(정보를 얻는 자료 — 문장에서 `W 같은 공식 자료` 로 쓴다) · P 관리 습관 · F (상황, 그 상황에서 먼저 볼 기준) 쌍(`…이라면` 앞에 상황, 뒤에 기준) · I 개요에서 확인할 정보
BANKS = {
    "appliance": {
        "C": ("놓을 자리와 설치 공간", "집 구조와 사용하는 방의 크기", "소비전력 표기", "소음 표기 방식", "필터나 소모품의 교체 방법", "청소와 관리가 쉬운 구조", "보증 범위와 서비스 접수 방법", "안전 인증 표시"),
        "M": ("사양표의 숫자만 보고 고르는 것", "소모품 비용을 따져 보지 않는 것", "놓을 자리를 재 보지 않고 정하는 것", "설명서를 읽지 않고 쓰기 시작하는 것", "보증 조건을 확인하지 않는 것", "이름이 비슷한 다른 모델과 헷갈리는 것"),
        "Z": ("전원이나 콘센트 연결 상태", "필터와 통로에 쌓인 먼지", "설치 위치와 주변 환경", "소모품의 교체 시기", "선택한 모드와 설정", "내부 부품의 이상"),
        "W": ("제품 설명서", "제조사 공식 누리집", "판매 페이지의 상세 안내", "서비스센터 안내"),
        "P": ("사용 뒤 비우고 닦는 습관", "소모품 교체 시기를 적어 두는 일", "설명서의 관리 항목을 정기적으로 훑어보는 일", "보관 장소의 습기와 먼지 점검"),
        "F": (("혼자 사는 집", "놓을 자리와 설치 공간"), ("공간이 좁은 집", "크기와 무게"), ("관리에 시간을 많이 쓰기 어려운 분", "청소와 관리가 쉬운 구조"), ("소음에 예민한 분", "소음 표기 방식"),
              ("식구가 여럿인 집", "사용하는 방의 크기와 집 구조")),
        "I": ("제품의 종류와 쓰임", "크기와 무게", "전원 방식", "구성품", "설명서 제공 여부"),
        "B": ("제품 설명서의 안전 안내", "전원을 끄고 플러그를 뽑아 두는 일", "작업 전의 상태를 사진으로 남기는 일", "쓰던 설정을 적어 두는 일"),
    },
    "pc_hw": {
        "C": ("연결 단자와 규격의 호환", "내 컴퓨터의 사양과 운영체제", "전원과 소비전력", "크기와 설치 공간", "발열과 소음 표기", "드라이버와 펌웨어 지원", "보증 범위와 서비스 방식", "사용 목적에 맞는 성능 범위"),
        "M": ("이름이 비슷한 다른 규격을 사는 것", "내 컴퓨터와의 호환을 확인하지 않는 것", "성능 수치만 보고 고르는 것", "케이스 크기와 전원 용량을 놓치는 것", "소프트웨어 지원 범위를 보지 않는 것", "설치 방법을 읽기 전에 분해부터 하는 것"),
        "Z": ("연결 단자나 케이블 상태", "드라이버와 펌웨어 버전", "전원 공급과 소비전력", "열과 통풍 환경", "설정이나 호환성 문제", "부품 자체의 불량"),
        "W": ("제조사 공식 지원 페이지", "제품 설명서", "제조사의 호환 목록", "판매 페이지의 상세 안내"),
        "P": ("드라이버와 펌웨어 점검", "먼지와 통풍 관리", "연결 단자 확인", "중요한 자료의 백업"),
        "F": (("문서 작업 위주로 쓰는 분", "내 컴퓨터와의 호환"), ("게임이나 영상 작업을 하는 분", "사용 목적에 맞는 성능 범위"), ("여러 기기를 함께 연결하는 분", "연결 단자와 규격"),
              ("한 번 사서 오래 쓰려는 분", "보증 범위와 드라이버 지원")),
        "I": ("제품 종류와 규격", "연결 방식", "전원 방식", "크기", "지원하는 운영체제"),
        "B": ("중요한 자료의 백업", "연결된 기기의 구성 기록", "작업 전의 설정 기록", "제품 설명서의 안전 안내"),
    },
    "software": {
        "C": ("무료와 유료로 나뉘는 기능의 범위", "사용량이나 횟수 제한 표기", "내 자료가 처리되는 방식에 관한 안내", "계정과 로그인 방식", "결제와 해지 방법", "지원하는 기기와 운영체제", "업데이트와 지원 정책", "내보내기와 백업 방법"),
        "M": ("약관과 개인정보 안내를 읽지 않고 쓰는 것", "무료 범위를 확인하지 않고 시작하는 것", "해지 방법을 보기 전에 결제 정보부터 넣는 것", "중요한 자료를 백업 없이 맡기는 것", "계정 하나에 모든 연결을 몰아 두는 것", "공식 안내 대신 오래된 글만 따라 하는 것"),
        "Z": ("계정이나 로그인 상태", "사용량 제한에 닿은 상태", "네트워크 연결 상태", "설정이나 권한", "프로그램 버전과 업데이트 상태", "서비스 쪽 점검이나 변경"),
        "W": ("공식 도움말", "이용 약관과 정책 페이지", "요금 안내 페이지", "공식 공지사항"),
        "P": ("보안 설정 점검", "중요한 자료의 정기 백업", "구독 상태와 결제 내역 확인", "업데이트 공지 확인"),
        "F": (("처음 써 보는 분", "무료로 쓸 수 있는 범위"), ("업무에 연결해 쓰려는 분", "내 자료가 처리되는 방식"), ("여러 서비스를 함께 쓰는 분", "계정과 연동 방식"), ("비용부터 따져 보려는 분", "결제와 해지 방법")),
        "I": ("서비스의 종류와 쓰임", "지원하는 환경", "계정 방식", "요금 구조", "제공하는 기능의 범위"),
        "B": ("중요한 자료의 백업", "현재 설정의 내보내기", "작업 전의 화면 기록", "계정과 접속 방법의 확인"),
    },
    "travel": {
        "C": ("예약 필요 여부와 취소 규정", "이용 방법과 순서", "위치와 이동 방법", "주차 가능 여부", "주변 시설의 위치", "운영 시간과 휴무", "함께 가는 사람에게 맞는 시설", "공식 안내에 적힌 이용 조건"),
        "M": ("예약 조건을 읽지 않고 정하는 것", "이동 시간을 빠듯하게 잡는 것", "운영 시간과 휴무를 확인하지 않는 것", "사진만 보고 시설을 짐작하는 것", "주차나 대중교통 정보를 놓치는 것", "취소 규정을 확인하지 않는 것"),
        "Z": ("예약 내용과 일정", "이동 경로와 교통 상황", "운영 여부", "날씨와 계절", "인원과 시간대", "시설 이용 조건"),
        "W": ("공식 누리집", "예약 페이지의 안내", "운영 주체의 공지", "지도 앱의 장소 정보"),
        "P": ("일정을 여유 있게 짜는 일", "예약 확인 내용을 저장해 두는 일", "출발 전 운영 정보를 다시 확인하는 일"),
        "F": (("아이와 함께 가는 분", "주변 시설의 위치"), ("부모님을 모시고 가는 분", "이동 방법과 주차"), ("혼자 다녀오려는 분", "예약 필요 여부와 취소 규정"), ("차 없이 이동하는 분", "대중교통 이동 방법"),
              ("짧게 다녀오려는 분", "운영 시간과 휴무")),
        "I": ("위치와 찾아가는 방법", "운영 시간", "이용 방법", "예약 방식", "주변 시설"),
        "B": ("예약 내용과 연락처 메모", "공식 안내의 확인", "일정과 이동 경로 메모", "취소 규정의 확인"),
    },
    "life": {
        "C": ("문제가 시작된 곳", "집의 환경과 상태", "필요한 도구와 재료", "안전하게 할 수 있는 범위", "들어가는 비용과 시간", "다시 생기지 않게 하는 방법"),
        "M": ("원인을 확인하기 전에 처리부터 하는 것", "여러 제품을 한꺼번에 섞어 쓰는 것", "제품의 안전 표시를 읽지 않는 것", "겉으로 보이는 곳만 닦고 마는 것", "한 번에 끝내려고 무리하는 것"),
        "Z": ("환기와 습도", "청소와 관리 주기", "배관이나 설비 상태", "생활 습관", "계절과 날씨", "집 구조"),
        "W": ("제품 사용 설명서", "관리사무소의 안내", "공식 안내문", "전문 업체의 안내"),
        "P": ("환기 습관", "정기적인 청소와 점검", "문제가 생기기 쉬운 곳을 미리 살펴보는 일", "소모품과 재료를 미리 갖춰 두는 일"),
        "F": (("집이 오래된 분", "문제가 시작된 곳"), ("아이나 반려동물과 사는 분", "안전하게 쓸 수 있는 재료"), ("혼자 해결하려는 분", "필요한 도구와 재료"), ("관리에 시간을 쓰기 어려운 분", "다시 생기지 않게 하는 방법")),
        "I": ("문제의 종류", "문제가 생긴 곳", "문제가 생긴 때", "집 구조", "지금까지의 관리 방법"),
        "B": ("작업 전의 상태 사진", "제품 사용 설명서의 안전 표시", "작업할 곳의 환기 상태", "필요한 도구와 재료 목록"),
    },
    "generic": {
        "C": ("사용 목적", "필요한 조건", "공식 안내에 적힌 내용", "들어가는 비용과 시간", "관련 규정이나 정책", "대안이 되는 선택지", "나에게 맞는 범위", "나중에 바꾸거나 되돌릴 수 있는지"),
        "M": ("목적을 정하지 않고 시작하는 것", "한 곳의 정보만 보고 정하는 것", "출처를 확인하지 않는 것", "조건을 적어 두지 않는 것", "나중에 바꿀 방법을 보지 않는 것"),
        "Z": ("준비 상태", "정해 둔 조건", "주변 환경", "하는 방법", "외부 요인", "예상하지 못한 변수"),
        "W": ("공식 누리집", "공식 안내 문서", "관련 기관의 안내", "이용 약관이나 정책 페이지"),
        "P": ("정해 둔 기준을 다시 점검하는 일", "기록을 남겨 두는 일", "바뀐 안내가 없는지 확인하는 일"),
        "F": (("처음 알아보는 분", "사용 목적"), ("시간이 많지 않은 분", "들어가는 비용과 시간"), ("분명한 기준이 필요한 분", "공식 안내에 적힌 내용"), ("주변에 물어볼 곳이 없는 분", "확인할 곳")),
        "I": ("종류와 쓰임", "필요한 조건", "진행 방식", "확인할 곳", "바뀔 수 있는 부분"),
        "B": ("작업 전의 상태 기록", "되돌릴 방법의 확인", "공식 안내의 확인", "필요한 준비물 목록"),
    },
}
# 문장 속에서 후보를 가리키는 말 — 글 유형에 따라 쓴다(제품·서비스·장소를 소개하는 글에서만 분야의 낱말을 쓰고, 나머지는 '이 주제'·'이 문제')
THING = {"appliance": "이 제품", "pc_hw": "이 제품", "software": "이 서비스", "travel": "이 장소", "life": "이 문제", "generic": "이 주제"}


def bank_of(domain):
    return BANKS[domain if domain in BANKS else GENERIC]


def pick(items, start, count):
    """`items` 에서 `start` 번째부터 `count` 개(끝에서 돌아서) — 같은 목록에서 서로 다른 항목만(`count` 가 목록보다 길면 목록 전체)."""
    size = len(items)
    count = min(count, size)
    return tuple(items[(start + offset) % size] for offset in range(count))


def pick_ordered(items, start, count):
    """`pick` 과 같은 항목을 고르되 **목록에 적힌 순서대로** 돌려준다 — 목록을 '쉬운 것에서 어려운 것' 순으로 적은 항목(원인 후보)에서 끝에서 돌아 고른 것이 앞뒤가 뒤바뀌어 나오지 않게(독립 검증 M1)."""
    size = len(items)
    count = min(count, size)
    return tuple(items[index] for index in sorted((start + offset) % size for offset in range(count)))


__all__ = ["ASSERTION_BOUNDARY", "ASSERTION_EN", "ASSERTION_WORDS", "BANKS", "DOMAINS", "DOMAIN_KO", "FOCUS_TAGS", "GENERIC", "PARTICLES", "SENSITIVE_EN", "SENSITIVE_KO", "SENSITIVE_SHORT", "SENSITIVE_WORDS", "THING",
           "TRIGGERS_EN", "TRIGGERS_KO", "assertion_hits", "bank_of", "domain_of", "focus_hit", "korean_hits", "latin_hits", "pick", "pick_ordered", "sensitive_kind", "squash"]
