"""'지어내지 않기' 검사 — 사용자가 입력했거나 믿을 수 있는 자료가 없으면 쓸 수 없는 말을 글에서 찾는다(요구서 v0.3.1 §6.3, docs/ARCHITECTURE.md §5 `check/`).

찾는 것은 두 갈래다.
  · **위반**(막는다) — 쓴 사람이 겪은 것처럼 단정하는 말: 직접 사용·체험했다(`experience_use`)·직접 방문했다(`experience_visit`)·구매했다(`experience_buy`)·수익을 얻었다(`experience_income`)·
    특정 효과나 느낌을 체감했다(`experience_effect`)·실제로 대화하거나 댓글을 받았다(`dialogue`)·실제로 있었던 사람이나 사례다(`case`).
  · **확인 권장**(막지 않는다) — 가격(`price`)·날짜(`date`)·시각이나 소요 시간(`time`)·통계나 비율(`stat`). 값이 틀렸는지는 알 수 없으니 작성일 기준으로 확인하라고 알릴 뿐이다.

한국어 낱말 규칙이라 오탐·미탐이 있다. 규칙은 '경험을 보고하는 과거형·경험형 어미'(사용해 보니·다녀왔습니다·구매했습니다 …)에 걸리게 하고, 아직 하지 않은 일을 안내하는 말(방문 전에 확인하는 것이 좋습니다·
사용해 보세요·구매했다면 …)·묻는 말·남의 글을 따옴표로 가리키는 말은 지나가게 한다. 낱말을 한 줄씩 늘리지 않고 **어간 × 어미**(체험·사용·착용·방문·구매 어간 × 해 보니·해 봤·다녀왔·갔더니 …)로 만들고,
'-했던·-했지만' 같은 꾸밈·대조꼴과 옮겨 전하는 말(…했다고 합니다)은 효과·수익 단정에서 뺀다. 어느 쪽이 걸리고 어느 쪽이 지나가는지는 `tests/test_check_claims.py` 의 예문 목록이 고정한다.
규칙은 띄어쓰기·구두점을 지운 글에 건다(`띄어 쓰든 붙여 쓰든 같은 말`). 정규식은 낱말 목록과 길이가 정해진 사이 글자만 써서 어떤 입력에서도 선형 시간에 끝난다.

경험을 입력한 사용자의 글은 예외다: `experience_given=True` 이면 사용자가 입력한 문장과 **정규화한 글이 똑같은 문장**만 위반에서 빼 준다(부분만 겹치는 문장은 빼지 않는다 — 한 줄에 사용자 문장과
다른 단정이 함께 있으면 다른 단정은 그대로 걸린다). 계획이 사용자 입력을 되풀이하는 줄 `이름(입력): 내용` 은 이름 부분을 떼고 내용만 견준다. `experience_given=False` 이면 어디에 있든 위반이다.
**위반은 한 건도 버리지 않는다**(개수 상한은 확인 권장에만 있다). 네트워크·파일은 쓰지 않는다.
"""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple

from ..errors import AppError

# ---- 분류 ---------------------------------------------------------------------------------------------------------------------
EXPERIENCE_USE = "experience_use"
EXPERIENCE_VISIT = "experience_visit"
EXPERIENCE_BUY = "experience_buy"
EXPERIENCE_INCOME = "experience_income"
EXPERIENCE_EFFECT = "experience_effect"
DIALOGUE = "dialogue"
CASE = "case"
PRICE = "price"
DATE = "date"
TIME = "time"
STAT = "stat"

VIOLATIONS = (EXPERIENCE_USE, EXPERIENCE_VISIT, EXPERIENCE_BUY, EXPERIENCE_INCOME, EXPERIENCE_EFFECT, DIALOGUE, CASE)
REVIEWS = (PRICE, DATE, TIME, STAT)
LABELS = {
    EXPERIENCE_USE: "직접 사용·체험했다는 주장", EXPERIENCE_VISIT: "직접 방문했다는 주장", EXPERIENCE_BUY: "구매했다는 주장", EXPERIENCE_INCOME: "수익을 얻었다는 주장",
    EXPERIENCE_EFFECT: "효과나 느낌을 체감했다는 주장", DIALOGUE: "실제 대화나 댓글", CASE: "실제로 있었다는 사람이나 사례",
    PRICE: "확인하지 않은 가격", DATE: "확인하지 않은 날짜", TIME: "확인하지 않은 시각·소요 시간", STAT: "확인하지 않은 통계·비율",
}
MAX_FINDINGS = 500                         # 확인 권장을 한 번에 돌려주는 최대 개수(아주 긴 글에서 결과가 끝없이 커지지 않게) — 위반에는 상한이 없다
MIN_FLAT = 2                               # 글자·숫자가 이보다 적은 문장은 검사하지 않는다(가장 짧은 낱말이 두 글자 — 아주 짧은 조각이 많은 글에서 시간을 아낀다)
RIGHT_SPAN = 14                            # 경험을 나타내는 말 바로 뒤 이 만큼의 글자에서 '하지 않은 일' 표지를 찾는다


class Claim(NamedTuple):
    category: str                          # 분류(위 상수) — `is_violation` 이 위반인지 확인 권장인지 알려 준다
    position: int                          # 걸린 문장의 번호(0부터) — 글을 문장으로 나눈 순서(`split_sentences`) 또는 넘긴 목록의 순서
    word: str                              # 근거 낱말(띄어쓰기를 지운 모양)


def is_violation(category):
    return category in VIOLATIONS


# ---- 글 다듬기 ---------------------------------------------------------------------------------------------------------------
_CLOSERS = frozenset("\"')]”’」』")
_BREAK_RUN = re.compile("[\n\r\u2028\u2029]+")
_TERMINATOR_RUN = re.compile("[.!?…。！？]+")
_NOT_ALNUM = re.compile(r"[\W_]+")
# 눈에 안 보이는 글자(폭 없는 글자·방향 제어·변형 선택자·한글 채움 글자·태그 …) — 낱말 사이에 끼워 규칙을 피하지 못하게, 글자를 합치기(NFKC) 전에 지운다
_INVISIBLE = re.compile("[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e\u2060-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufffb\U000e0000-\U000e0fff]")
# 따옴표로 묶은 말 바로 뒤에 '… 같은·라는·처럼' 이 붙으면 그 말을 쓰는 것이 아니라 가리키는 것이다('직접 써봤는데 좋았어요' 같은 후기)
_MENTION = re.compile("[\"'‘“「『][^\"'‘’“”「」『』]{1,80}[\"'’”」』]\\s{0,2}(?:와 같은|과 같은|같은|라는|이라는|처럼|등의|식의|이라는 말|라는 말)")
_ECHO_LABEL = re.compile(r"[^:：\n]{1,30}\(입력\)\s*[:：]\s*")                       # 계획이 사용자 입력을 되풀이하는 줄 `이름(입력): 내용`
_QUESTION_END = re.compile(r"(?:나요|까요|니까|어때요|어떠세요)$")
# 묻는 말인 척 끝에 물음표만 붙인 선언('편했어요?')이나 선언 뒤에 꼬리 질문을 붙인 문장('만족했습니다 아닌가요?')은 묻는 말이 아니다 — 문장 안에 과거형 서술(-았어요·-했습니다·-했네요·-했군요)이 있으면 겪은 일을 말하는 것이다
_PAST_STATEMENT = re.compile("(?:어요|습니다|네요|군요)")
_ASKING_WORD = re.compile("어땠|어떠했|뭐였|무엇이었|누구였|어디였|언제였|왜였|얼마였")          # '어땠어요?' 의 '땠어요' 는 서술이 아니라 묻는 말이다
# 효과·수익을 단정한 말 뒤의 '…다고 생각합니다·말할 수 있습니다·확신합니다' 는 남의 말을 옮기는 것이 아니라 자기 판단으로 단정하는 말이다
_OWN_VIEW = re.compile("(?:다고|다는)[가-힣]{0,4}?(?:생각|말할수|말해도|확신|믿|봅니다|봐요|느낍|느껴|느끼|평가|자부|단언|장담|여깁|여겨|판단|인정)")
_ASCII_WORDS = re.compile(r"[A-Za-z]{3}")


def split_sentences(text):
    """글을 문장으로 나눈다 — 마침표·물음표·느낌표(뒤에 닫는 따옴표·괄호가 붙어도 되고, 소수점 `3.5` 처럼 바로 뒤에 공백이 없는 것은 문장 끝이 아니다)와 줄바꿈에서 자른다. 빈 조각은 버린다.
    줄은 줄바꿈 묶음으로 나누고 문장 끝 글자 묶음은 정규식이 찾아 주므로(글자마다 파이썬이 훑지 않는다) 어떤 글에서도 선형 시간이다."""
    pieces = []
    for line in _BREAK_RUN.split(str(text)):
        start, size = 0, len(line)
        for match in _TERMINATOR_RUN.finditer(line):
            end = match.end()
            while end < size and line[end] in _CLOSERS:
                end += 1
            if end >= size or line[end].isspace():
                pieces.append(line[start:end])
                while end < size and line[end].isspace():
                    end += 1
                start = end
        pieces.append(line[start:])
    return [piece.strip() for piece in pieces if piece.strip()]


def flat(text):
    """띄어쓰기·구두점·기호를 지우고(글자·숫자만) 눈에 안 보이는 글자를 지우고 호환 문자를 풀고(NFKC) 소문자로 한 글 — 규칙을 거는 모양."""
    return _NOT_ALNUM.sub("", unicodedata.normalize("NFKC", _INVISIBLE.sub("", str(text))).casefold())


def _trie(words):
    """낱말들을 앞글자가 같은 것끼리 묶은 정규식 — `사용해보니|사용해봤` 대신 `사용해(?:보니|봤)`. 가장 긴 낱말이 먼저 걸린다(글자를 더 이을 수 있으면 이어 본다)."""
    root = {}
    for word in set(words):
        node = root
        for char in word:
            node = node.setdefault(char, {})
        node[""] = True

    def emit(node):
        branches = [re.escape(char) + emit(child) for char, child in sorted(item for item in node.items() if item[0])]
        if not branches:
            return ""
        body = "(?:" + "|".join(branches) + ")"
        return body + "?" if "" in node else body

    return emit(root)


def _literals(*words):
    return re.compile(_trie(words))


def _cross(stems, endings):
    """어간 × 어미 — 낱말 한 줄씩 늘리지 않고 곱으로 만든다."""
    return [stem + ending for stem in stems for ending in endings]


# ---- 경험을 단정하는 말(위반) ---------------------------------------------------------------------------------------------------
# HARD: 이 말이 있으면 그 자체로 '해 봤더니·다녀왔다·샀다' 같은 경험의 보고다(바로 뒤에 '하지 않았다·적이 없다·것처럼' 같은 표지가 없다면).
# SOFT: '방문했을 때' 처럼 때를 가리키는 말, '한 고객이' 처럼 누군가를 가리키는 말 — 같은 문장 뒤쪽에 과거형 서술('편했습니다')이 있고 문장이 안내(…하세요·…좋습니다)로 끝나지 않을 때만 경험이다.
_FIRST = "직접|제가|저는|내가|나는|저도|우리는|저희는|우리가족은|저희가족은|실제로|매일"
_TIME_MARK = "어제|그제|엊그제|며칠전|얼마전|지난주|지난달|지난번|지난해|지난여름|지난겨울|지난봄|지난가을|지난주말|지난휴가|지난연휴|작년|올여름|올겨울|오늘아침|오늘낮|오늘저녁|방금|아까|한달전|일주일전|이틀전|사흘전"
_BUY_PAST = ("샀", "주문했", "결제했", "구매했", "구입했", "받았", "질렀")
_SEE_STEMS = ("사용해", "써", "이용해", "체험해", "경험해", "착용해", "복용해", "설치해", "적용해", "테스트해", "실행해", "시도해", "활용해", "운영해", "시청해", "시식해", "시승해", "시착해", "구동해", "충전해",
              "연결해", "장착해", "접속해", "먹어", "마셔", "입어", "신어", "발라", "들어", "읽어", "돌려", "켜", "틀어", "타", "앉아", "누워", "만져", "깔아", "열어", "눌러", "만들어", "끓여", "구워",
              "복용해", "따라해", "따라서해")
_SEE_ENDS = ("보니", "봤", "보았", "본결과", "본후", "본뒤", "본소감", "본느낌", "본경험", "본바로는", "본결론")
_USE_PAST = ("사용했", "썼", "써왔", "이용했", "체험했", "경험했", "먹었", "마셨", "입었", "신었", "착용했", "복용했", "설치했", "운영했", "사용해왔", "써봤", "들었", "읽었", "시청했", "수강했", "참여했",
             "참석했", "따라해봤", "따라했", "겪었", "시도했", "가입했", "신청했", "등록했", "구독했", "해봤", "해보았", "해보니")
_VISIT_PAST = ("방문했", "다녀왔", "찾았", "찾아갔", "갔", "들렀", "묵었", "머물렀")
_DURATION = "(?:[0-9]{1,9}|한|두|세|네|다섯|여섯|일)(?:달|주일|주|개월|년)"
_USING = ("사용했", "사용해왔", "사용중", "써왔", "썼", "이용했", "이용해왔", "이용중", "복용했", "복용중", "먹었", "먹어왔", "착용했", "착용중", "체험했", "운영했", "운영중", "쓰고있", "사용하고있", "이용하고있",
          "복용하고있", "먹고있", "착용하고있", "운영하고있", "체험하고있")
_STAFF = "사장님|직원분|직원|점원|상담원|상담사|의사선생님|의사|선생님|담당자|매니저|기사님|원장님|약사님|사장|주인장|고객센터|관계자"
_KIN = "친구|지인|동료|가족|이웃|후배|선배|언니|오빠|누나|동생|아내|남편|엄마|아빠|어머니|아버지"
_SURNAMES = "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민나진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모"       # 직함 앞에 오는 성
_COMMON_SURNAMES = "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민"

_RULES = (
    (EXPERIENCE_USE,
     _literals(*_cross(_SEE_STEMS, _SEE_ENDS), "사용해왔", "써왔", "이용해왔", "복용해왔", "먹어왔", "입어왔", "써오고있", "사용해오고있", "이용해오고있", "직접사용한", "직접써본", "직접이용한", "직접체험한", "직접먹어본",
               "직접해본", "직접경험한", "직접착용한", "직접복용한", "직접테스트한", "직접설치한", "직접입어본", "직접타본", "직접사용했", "직접써왔", "직접이용했", "직접체험했", "직접경험했", "직접먹었",
               "직접착용했", "직접복용했", "직접테스트했", "직접해봤", "직접써봤", "직접써서", "따라했더니", "따라했는데", "따라했습니다", "따라했어요", "입어보고나서", "써보고나서", "먹어보고나서", "사용해보고나서", "이용해보고나서", "체험해보고나서", "착용해보고나서", "해봤더니", "해보았더니", "잘쓰고있", "계속쓰고있", "아직도쓰고있", "지금도쓰고있",
               "잘사용하고있", "계속사용하고있", "지금도사용하고있", "써보면서느낀", "쓰면서느낀", "사용하면서느낀", "이용하면서느낀", "써보면서느꼈", "쓰면서느꼈", "사용하면서느꼈", "이용하면서느꼈", "쓰다보니", "사용하다보니", "이용하다보니", "먹다보니",
               "입다보니", "신다보니", "타다보니", "복용하다보니", "착용하다보니", "운영하다보니", "체험하다보니", "실사용기준"),
     re.compile(rf"(?:{_FIRST})[가-힣]{{0,10}}?(?:{_trie(_USE_PAST)})|(?:체험단|서포터즈|협찬|제공받아|지원받아|무상으로제공받)[가-힣]{{0,10}}?(?:사용했|써봤|써보았|이용했|체험했|먹었|입었|착용했|복용했|설치했)"
                rf"|(?:{_TIME_MARK})[가-힣0-9]{{0,12}}?(?:{_trie(_USE_PAST)})|(?:써보면서|쓰면서|사용하면서|이용하면서|먹으면서|입으면서|착용하면서)[가-힣]{{0,10}}?(?:없었|있었|알게|좋았|불편했|편했|느꼈|느낀)"),
     re.compile(rf"{_DURATION}(?:째|동안|간)?[가-힣]{{0,3}}?(?:{_trie(_USING)})"),
     _literals("사용했을때", "써봤을때", "써보았을때", "이용했을때", "먹었을때", "입었을때", "체험했을때", "설치했을때", "착용했을때", "복용했을때")),
    (EXPERIENCE_VISIT,
     _literals("방문해보니", "방문해봤", "방문해보았", "방문했더니", "방문했는데", "방문했습니다", "방문했어요", "방문했다", "방문했네요", "다녀왔", "다녀오니", "다녀와보니", "다녀온후기", "다녀온소감",
               "제가다녀온", "직접다녀온", "직접다녀", "가보니", "가봤", "가보았", "찾아가보니", "찾아가봤", "찾아갔", "들러보니", "들러봤", "들렀", "직접방문했", "직접가봤", "직접가서", "직접찾아갔",
               "직접가본", "갔더니", "갔다가", "갔다왔", "다녀온곳", "다녀온장소", "다녀온가게", "다녀온식당", "다녀온카페", "다녀온맛집", "다녀온여행", "방문한곳", "방문했던곳", "방문한매장",
               "방문했던매장", "방문한식당", "찾아간곳", "찾았던곳", "묵었", "머물렀", "헤맸", "도착했더니", "도착해보니", "들어서자마자", "들어서니", "들어가보니", "들어갔더니", "나갔더니", "올라갔더니", "내려갔더니"),
     re.compile(rf"(?:{_FIRST}|{_TIME_MARK})[가-힣0-9]{{0,12}}?(?:{_trie(_VISIT_PAST)})(?:습니다|어요|아요|는데|다|고|네요|더니|지만)|(?:일주일|하루|이틀|사흘|한달|며칠|여름|겨울|주말|휴가|연휴)[가-힣]{{0,6}}?보냈(?:습니다|어요)"),
     None,
     _literals("방문했을때", "갔을때", "다녀왔을때", "찾아갔을때", "들렀을때", "가봤을때", "가보았을때", "다녀와서", "돌아와서")),
    (EXPERIENCE_BUY,
     _literals("사봤", "사보니", "질렀", "구매해봤", "구매해보니", "구매해보았", "구입해봤", "구입해보니", "직접구매했", "내돈내산", "배송받았", "수령했", "택배를받았", "택배로받았", "주문해서받", "포장을뜯", "뜯어보니",
               "뜯어봤", "개봉했", "언박싱했", "박스를열었"),
     re.compile(r"(?:샀|구매했|구입했|주문했|결제했)(?:다|습니다|어요|는데|고|네요|더니|지만|으며)|(?:구매|구입|주문|결제)(?:를|을)?(?:마쳤|완료했|했)(?:다|습니다|어요|는데|고|네요|더니|지만|으며)"
                r"|(?:이번에|최근에|얼마전|지난달|지난주|어제|오늘|새로|직접|제가|방금)[가-힣]{0,6}?(?:구입|구매|주문|결제)한|(?:새로|직접|제가|이번에|최근에)[가-힣]{0,4}?산(?:제품|물건|것|거|상품)"
                r"|(?:주문|구매|구입)한(?:제품|상품|물건)(?:이|을|은)?[가-힣]{0,6}?(?:도착|받았|왔)"
                rf"|(?:주문|결제)하고[가-힣0-9]{{0,10}}?(?:받았|도착했|왔)(?:습니다|어요|는데|다)|(?:{_TIME_MARK})[가-힣0-9]{{0,12}}?(?:{_trie(_BUY_PAST)})(?:습니다|어요|아요|는데|다|고|네요)"), None,
     _literals("구매했을때", "구입했을때", "샀을때", "주문했을때", "결제했을때")),
    (EXPERIENCE_INCOME,
     _literals("돈을벌었", "벌었습니다", "벌었어요", "벌었는데", "벌었다", "수익인증", "수익후기", "정산받았", "정산을받았", "돈을벌고있", "벌고있습니다", "벌고있어요", "벌고있는데", "수익이쏠쏠", "수익화에성공", "수익화성공", "입금받았", "지급받았", "수익을받았"),
     re.compile(r"수익(?:을|이|은)?(?:냈|났|얻었|올렸|봤|벌었|생겼|발생했|달성했)|수익(?:을|이)?[가-힣0-9]{0,6}?(?:내고있|올리고있)|수익(?:이|은|도)?[가-힣0-9]{0,12}?(?:늘고있|늘었|올랐|증가했|증가하고있|줄었|넘었|돌파했|달성했|기록했|발생하고있)"), None, None),
    (EXPERIENCE_EFFECT,
     _literals("효과를봤", "효과를보았", "효과를느꼈", "효과를경험", "효과가있었", "효과가좋았", "효과가없었", "체감했", "체감됐", "체감되었", "체감할수있었", "체감이컸", "체감상", "느꼈", "느껴졌",
               "느낄수있었", "실감했", "실감났", "차이를체감", "확실히달라졌", "눈에띄게좋아졌", "눈에띄게나아졌", "살이빠졌", "편리했", "편했", "불편했", "좋았", "아쉬웠", "만족스러웠", "만족했",
               "놀랐", "인상적이었", "훌륭했", "실망했", "부족했", "빨랐", "느렸", "조용했", "시끄러웠", "맛있었", "맛없었", "괜찮았", "깔끔했", "따뜻했", "시원했", "쾌적했", "저렴했", "비쌌", "후회했",
               "편안했", "안정적이었", "만족합니다", "만족해요", "만족스럽습니다", "만족스러워요", "만족스럽네요", "기대이상이었", "기대이상입니다", "기대이상이네요", "기대이상이라", "기대보다좋았",
               "기대보다만족", "기대에못미쳤", "느낌이들었", "느낌이났", "기분이좋았", "기분이나빴", "일품이었", "일품입니다", "별로였", "별로예요", "별로입니다", "별로네요", "최고였", "하루종일갔", "종일갔",
               "오래갔", "이틀갔", "버텼", "쉬웠", "어려웠", "복잡했", "간단했", "수월했", "무거웠", "가벼웠", "작았", "넉넉했", "좁았", "넓었", "길었", "짧았", "두꺼웠", "얇았", "밝았", "어두웠", "선명했",
               "부드러웠", "딱딱했", "촉촉했", "건조했", "따가웠", "아팠", "가려웠", "쫀득했", "바삭했", "눅눅했", "싱거웠", "담백했", "고소했", "느끼했", "향긋했", "매웠"),
     re.compile(r"(?:사용후|써본후|복용후|적용후|이용후|먹은후|바른후)[가-힣]{0,12}?(?:좋아졌|나아졌|달라졌|호전됐|빠졌|늘었|줄었)"
                r"|(?:확|많이|훨씬|완전히|눈에띄게)달라졌|(?:통증|증상|염증|피로|스트레스|붓기|뾰루지|두통|가려움|냄새|소음|컨디션|피부결|피부|몸|허리|무릎|어깨|눈)(?:이|가|은|는|도)?[가-힣]{0,6}?(?:줄었|사라졌|없어졌|나아졌|좋아졌|부드러워졌|가벼워졌|편해졌|개선됐|완화됐|가라앉았|빠졌|편안해졌|달라졌)"),
     None, None),
    (DIALOGUE,
     _literals("라고말씀하셨", "라고하셨", "라고말했", "라고했더니", "라고했습니다", "라고하더라", "라고물어보", "라고답했", "라고대답했", "라고답변", "라고알려주", "라고안내받", "라고들었",
               "라는말을들었", "이라고하셔서", "라고하시더라", "말하길", "말씀하시길", "하시더라고요", "더라고요", "더라구요", "더군요", "전화해보니", "전화했더니", "통화했", "통화해보니",
               "문의했더니", "문의해보니", "문의드렸", "상담받았", "상담해보니", "카톡으로물어", "카카오톡으로물어", "대화를나눴", "이야기를나눠", "이야기를들었", "얘기를들었", "직원분이말씀",
               "사장님이말씀", "사장님께서말씀", "고객님이말씀", "이웃님이댓글", "지인이알려줬", "지인에게들었", "친구에게들었", "친구가추천했", "지인이추천했", "고객센터에문의했"),
     re.compile(r"댓글(?:로|에|을)?[가-힣]{0,8}?(?:달렸|달았|남겼|남기셨|주셨|물어보셨|질문하셨|문의하셨|말씀하셨|써주셨|올라왔)|(?:다|라|자|냐|래|요)고(?:말씀하셨|말씀하시|말했|하셨|하시|했|하더|하셔서|해주셨|이야기했|답했|대답했|답변했|안내했|알려주셨|알려줬)"
                rf"|(?:{_STAFF})(?:께서|이|가|은|는|도)?[가-힣]{{0,8}}?(?:설명해주셨|안내해주셨|알려주셨|알려줬|말씀해주셨|말씀하셨|안내해줬|안내해주었|설명해줬|설명해주었|추천해주셨|추천해줬|추천해주었|도와주셨|도와줬|답해주셨|답변해주셨|권해주셨|권하셨|물어보셨|하셨)"
                rf"|(?:{_KIN})(?:께서|이|가)[가-힣]{{0,8}}?(?:추천해|권해|소개해|알려|보라고|하라고|사라고)|댓글(?:을|로)?(?:남겨|달아|써|보내|알려)?주(?:신|셨|었)|이웃님(?:께서|이)?[가-힣]{{0,8}}?(?:주셨|주신|남기셨|남겨주신|물어보셨|질문하셨|말씀하셨|알려주셨|달아주셨)|이웃님덕분에"),
     None, None),
    (CASE,
     _literals("실제사례", "실제로있었던", "실제로겪은", "제지인", "제친구", "제가아는", "지인의사례"),
     re.compile(rf"(?:[a-z]|[{_COMMON_SURNAMES}]|모)씨(?:는|가|께서)|[{_SURNAMES}](?:대리|과장|차장|부장|팀장|사원|대표|사장|선생|교수)(?:님)?(?:은|는|이|가|께서|도)|실제[가-힣]{{0,4}}사례"),
     None,
     re.compile(r"한고객(?:은|이|님)|어떤고객|한직장인|한주부|한학부모|한독자|한이웃|한사용자는|한분은|어떤분은|(?:저희|우리|제)(?:어머니|아버지|가족|부모님|아내|남편|언니|오빠|형|누나|동생|아이|아들|딸|엄마|아빠|친구|동료|지인|이웃)(?:도|는|가|께서)")),
)
# 경험을 나타내는 말 바로 뒤에 이런 표지가 있으면 '했다' 가 아니라 '하지 않았다·한 것처럼·했다면·아니라' 같은 말이다
_RIGHT_GUARD = ("적이없", "적은없", "적도없", "적없", "다면", "라면", "으면", "이면", "는지", "은지", "아니라", "아닌", "아니고", "아니며", "을때만", "을경우", "는경우", "한경우")
# 낱말 바로 뒤에 붙을 때만 보는 표지: '실제 사례처럼 쓰지 않는다'·'써 본 듯이'·'방문했다면'(`다` 까지 낱말에 들어 있으니 `면` 이 바로 이어진다)
_RIGHT_START = ("처럼", "듯", "척", "인양", "면")
# 낱말이 '~한·~본·~온'(꾸미는 말)로 끝날 때 바로 뒤에 이런 말이 오면 조건이거나 남의 경험을 가리키는 말이다: '직접 다녀온 경우에만'·'직접 사용한 사람은'
_NOUN_START = ("경우", "사람", "분들", "이들", "고객", "이용자", "사용자", "독자")
# 효과·수익을 단정하는 말 바로 뒤에서만: '…했다고 합니다'(남이 한 말을 옮김)·'…했던·…했지만·…했으나'(지난 모습을 대조하거나 꾸미는 말) — 겪은 일의 보고가 아니다
_QUOTED_START = ("다고", "라고", "다는", "다던", "대요", "답니다", "다며", "던", "지만", "으나", "다가", "을때", "을수", "을것", "을지")
_GUARDED_START = {EXPERIENCE_EFFECT: _QUOTED_START, EXPERIENCE_INCOME: _QUOTED_START}
# 글에 넣을 것을 만든다는 뜻의 '만들어 보았다' 를 가리는 말 — 바로 앞에 이런 말이 오면 겪은 일의 보고가 아니다
_MADE_AS = ("표로", "목록으로", "그림으로", "도표로", "그래프로", "리스트로", "요약으로", "표를", "문서로", "글로", "형태로", "방식으로", "순서로", "차례로")
_PAST = re.compile(r"(?:었|았|했|였|웠|렸|겼|랐|났|갔|왔|봤|썼|샀|줬|셨|컸|쌌|켰|떴|섰)(?:습니다|어요|아요|는데|다|네요|고|음|으며|지만|더니|죠)")
# '방문했을 때 …정리했습니다' 처럼 글을 쓰는 일을 가리키는 과거형은 경험의 보고가 아니다
_META_PAST = re.compile(r"(?:정리|작성|소개|안내|설명|준비|구성|구분|분류|제공|요약|비교|정돈|마련|추가|수정|보완|반영|표시|기록|공유|전달)했$|(?:담|적|모|묶|만들|추리|나누)었$|(?:담|모)았$|나눴$|추렸$")
_ADVICE_END = re.compile(r"(?:세요|십시오|바랍니다|권합니다|좋습니다|좋아요|됩니다|합니다만|드립니다|보세요|마세요|해야합니다|하시기바랍니다)$")

# ---- 확인하지 않은 값(확인 권장) --------------------------------------------------------------------------------------------------
_PRICE_FLAT = re.compile(r"(?<![0-9])[0-9]{1,15}(?:원|만원|천원|억원|달러|엔|유로|위안|불|원대|만원대|천원대)|(?:(?<![0-9])[0-9]|[일이삼사오육칠팔구십백천])만원|[일이삼사오육칠팔구십백천]{1,8}천원|(?<![0-9])[0-9]{1,9}만[0-9]{0,6}천?원|(?:usd|krw|eur|jpy|cny)[0-9]{1,15}|(?<![0-9])[0-9]{1,15}(?:usd|krw|eur|jpy|cny)")     # 숫자 반복은 길이를 정해 둔다 — 긴 숫자 줄에서 제곱 시간이 되지 않게
_PRICE_RAW = re.compile(r"[$₩€£¥]\s*[0-9]|[0-9]\s*[$₩€£¥]")
_DATE_FLAT = re.compile(r"(?<![0-9])(?:19|20)[0-9]{2}년|(?<![0-9])[0-9]{1,2}월[0-9]{1,2}일|(?:올해|작년|내년|지난해|재작년)[0-9]{1,2}월")
_DATE_RAW = re.compile(r"(?<![0-9])(?:19|20)[0-9]{2}\s*[-./]\s*[0-9]{1,2}\s*[-./]\s*[0-9]{1,2}(?![0-9])|(?<![0-9/.])[0-9]{1,2}\s*/\s*[0-9]{1,2}\s*(?:에|부터|까지|일|출시|발매|공개|발표|마감|시작|종료)")
_TIME_FLAT = re.compile(r"(?:오전|오후)[0-9]{1,2}시|(?<![0-9])[0-9]{1,2}시(?:부터|까지|에|경|정각|반|[0-9]{1,2}분)|(?<![0-9])[0-9]{1,6}(?:분|시간)(?:이|가|은|는|을|를|에|에는|만에)?(?:정도|가량|안에|이내|소요|걸|동안|간|운영|영업|내)|(?<![0-9])[0-9]{1,3}(?:일|주)(?:이내|안에|정도|가량|소요|걸)")
_TIME_RAW = re.compile(r"(?<![0-9])[0-9]{1,2}:[0-9]{2}(?![0-9])")
_STAT_FLAT = re.compile(r"(?<![0-9])[0-9]{1,9}(?:퍼센트|프로(?![가-힣]))|(?<![0-9])[0-9]{1,6}명중[0-9]{1,6}명|[가-힣0-9]{1,4}명중[가-힣0-9]{1,4}명|(?<![0-9])[0-9]{1,3}분의[0-9]{1,3}|(?<![0-9])[0-9]{1,6}배(?:이상|가량|정도)?(?:늘|증가|감소|줄|상승|하락|높|낮|빠르|넓|커|작|차이)"
                        r"|(?:통계|조사|연구|설문|보고서|자료|발표)(?:에|에서)?(?:따르면|의하면)|(?:통계|조사|연구|설문)결과|응답자")
_STAT_RAW = re.compile(r"[0-9]\s*%|%\s*[0-9]")

_HINT_FLAT = re.compile(r"[0-9]|따르면|의하면|결과|응답자|만원|천원|올해|작년|내년|지난해|재작년|usd|krw|eur|jpy|cny|명중|분의")      # 확인 권장 규칙이 걸리려면 문장에 이 중 하나는 있어야 한다 — 없으면 규칙을 하나씩 돌려 보지 않는다
_HINT_RAW = re.compile(r"[$₩€£¥%]")

# ---- 영어 문장(첫 사람 경험 단정) ----------------------------------------------------------------------------------------------
_EN_RULES = (
    (EXPERIENCE_USE, re.compile(r"\bi(?:'ve| have| had)? (?:tried|used|tested|installed|tasted|worn|been using|been trying)\b|\bi wore\b|\bused it\b|\b(?:after|since) (?:using|trying|testing|wearing)\b|\bin my (?:own |personal )?experience\b"
                                r"|\bmy (?:honest |personal |own )?(?:review|experience|impression|take)\b")),
    (EXPERIENCE_VISIT, re.compile(r"\b(?:i|we) (?:visited|went to|stayed at|dined at|checked in|came here)\b|\b(?:i|we) went\b|\bwe stayed\b")),
    (EXPERIENCE_BUY, re.compile(r"\b(?:i|we) (?:bought|purchased|ordered|paid for)\b|\bi got (?:it|this|mine)\b")),
    (EXPERIENCE_INCOME, re.compile(r"\bi (?:earned|made|got paid)\b")),
    (EXPERIENCE_EFFECT, re.compile(r"\bloved it\b|\bworked (?:well|great|perfectly|like a charm)\b|\bi (?:loved|liked|hated|enjoyed|was (?:impressed|satisfied|disappointed))\b")),
    (DIALOGUE, re.compile(r"\b(?:the )?(?:owner|staff|clerk|waiter|manager|doctor|agent) (?:told|said|recommended|explained)\b")),
)


def _reviews(sentence, flat_sentence):
    if not (_HINT_FLAT.search(flat_sentence) or _HINT_RAW.search(sentence)):
        return []
    found = []
    for category, patterns in ((PRICE, (_PRICE_FLAT, _PRICE_RAW)), (DATE, (_DATE_FLAT, _DATE_RAW)), (TIME, (_TIME_FLAT, _TIME_RAW)), (STAT, (_STAT_FLAT, _STAT_RAW))):
        for index, pattern in enumerate(patterns):
            match = pattern.search(flat_sentence if index == 0 else sentence)
            if match:
                found.append((category, flat(match.group(0)) or match.group(0).strip()))
                break
    return found


def _merge(*patterns):
    return re.compile("|".join(pattern.pattern for pattern in patterns if pattern is not None))


_COMPILED = tuple((category, _merge(hard, second, third), soft, _GUARDED_START.get(category, ())) for category, hard, second, third, soft in _RULES)


def _unguarded(flat_sentence, pattern, extra_start):
    """첫 번째로 걸리는 경험 단정 낱말(바로 뒤에 '하지 않은 일' 표지가 없는 것). 없으면 None."""
    for match in pattern.finditer(flat_sentence):
        tail = flat_sentence[match.end():match.end() + RIGHT_SPAN + 4].replace("아닌가요", "")[:RIGHT_SPAN]           # '…했습니다 아닌가요?' 의 '아닌' 은 부정이 아니라 되묻는 꼬리다(창 끝에서 잘리지 않게 넉넉히 잡고 지운 뒤 자른다)
        word = match.group(0)
        if word.startswith("만들어") and flat_sentence[max(0, match.start() - 5):match.start()].endswith(_MADE_AS):          # '표로 만들어 보았습니다' 는 글에 넣을 표를 만든 일이지 겪은 일이 아니다
            continue
        if any(guard in tail for guard in _RIGHT_GUARD) or tail.startswith(_RIGHT_START) or (extra_start and tail.startswith(extra_start) and not _OWN_VIEW.match(tail)) or (word[-1] in "한본온" and tail.startswith(_NOUN_START)):
            continue
        return word
    return None


def _timed(flat_sentence, soft):
    """'…했을 때'·'한 고객이' 형태 — 같은 문장 뒤에 (글 쓰는 일이 아닌) 과거형 서술이 있고 문장이 안내로 끝나지 않을 때만."""
    if soft is None or _ADVICE_END.search(flat_sentence):
        return None
    match = soft.search(flat_sentence)                              # 첫 낱말만 본다 — 뒤에 과거형 서술이 있으면 첫 낱말 뒤에도 있다(낱말마다 찾으면 긴 글에서 제곱 시간)
    if not match:
        return None
    for seen, past in enumerate(_PAST.finditer(flat_sentence, match.end())):
        if not _META_PAST.search(flat_sentence, max(match.end(), past.start() - 4), past.start() + 1):
            return match.group(0)
        if seen >= 2:                                               # 앞의 세 곳만 본다(긴 글에서 늘어지지 않게)
            break
    return None


def _violations(sentence, flat_sentence):
    found = []
    for category, patterns, soft, extra_start in _COMPILED:
        word = _unguarded(flat_sentence, patterns, extra_start) or _timed(flat_sentence, soft)
        if word:
            found.append((category, word))
    if _ASCII_WORDS.search(sentence):
        lowered = sentence.casefold()
        for category, pattern in _EN_RULES:
            match = pattern.search(lowered)
            if match:
                found.append((category, match.group(0)))
    return found


def _past_syllable(char):
    code = ord(char) - 0xAC00
    return 0 <= code < 11172 and code % 28 == 20 and char not in "셨겠있"          # 받침이 'ㅆ' 인 글자 — 과거형(았·었·했·였·봤·썼 …). 높임의 '셨'(어떠셨어요?)·추측·부탁의 '겠'(알려 주시겠어요?)·있다의 '있'(있어요) 은 과거 서술이 아니므로 뺀다


def _states_past(flat_sentence):
    """문장에 과거형 서술(-았어요·-했습니다·-했네요·-했군요, 맨 끝의 -했다)이 있는가 — '어땠어요' 같은 묻는 낱말은 서술로 치지 않는다."""
    text = _ASKING_WORD.sub("", flat_sentence)
    if len(text) > 1 and text.endswith("다") and _past_syllable(text[-2]):
        return True
    return any(match.start() and _past_syllable(text[match.start() - 1]) for match in _PAST_STATEMENT.finditer(text))


def _is_question(sentence, flat_sentence):
    """묻는 말('써 보니 어떠셨나요?')은 경험을 단정하지 않는다 — 물음표만 붙였거나 꼬리 질문을 단 선언('편했어요?'·'만족했습니다 아닌가요?')은 묻는 말이 아니다."""
    stripped = sentence.rstrip().rstrip("\"')]”’」』").rstrip()
    asks = stripped.endswith(("?", "？")) or bool(_QUESTION_END.search(flat(stripped)))
    return asks and not _states_past(flat_sentence)


def _sentences(text_or_sentences, item="검사할 글"):
    if isinstance(text_or_sentences, str):
        return split_sentences(text_or_sentences)
    if isinstance(text_or_sentences, (list, tuple)) and all(isinstance(piece, str) for piece in text_or_sentences):
        return list(text_or_sentences)
    raise AppError("CONTENT_INVALID", {"항목": item}, detail="글(문자열)이나 문장의 목록(list·tuple)이어야 한다")


def _user_keys(user_sentences):
    """사용자가 입력한 글의 열쇠(정규화한 글) — 목록의 항목 하나하나, 한 덩어리 글이면 문장 하나하나와 글 전체."""
    pieces = _sentences(user_sentences, "사용자가 입력한 글")
    if isinstance(user_sentences, str):
        pieces = [*pieces, user_sentences]
    return frozenset(key for key in (flat(piece) for piece in pieces) if key)


def _scan(text_or_sentences, experience_given, user_sentences, with_reviews):
    sentences = _sentences(text_or_sentences)
    exempt = _user_keys(user_sentences) if experience_given else frozenset()
    claims, reviews = [], 0
    for position, sentence in enumerate(sentences):
        scanned = _MENTION.sub(" ", sentence) if "같은" in sentence or "라는" in sentence or "처럼" in sentence or "등의" in sentence or "식의" in sentence else sentence
        flat_sentence = flat(scanned)
        if len(flat_sentence) < MIN_FLAT:
            continue
        original = flat_sentence if scanned is sentence else flat(sentence)
        found = _violations(scanned, flat_sentence)
        if found and (_is_question(scanned, flat_sentence) or (exempt and _exempt(sentence, original, exempt))):
            found = []
        for category, word in found:
            claims.append(Claim(category, position, word))
        if with_reviews and reviews < MAX_FINDINGS:
            for category, word in _reviews(sentence, original):
                if reviews >= MAX_FINDINGS:
                    break
                claims.append(Claim(category, position, word))
                reviews += 1
    return tuple(claims)


def _exempt(sentence, flat_sentence, exempt):
    """사용자가 입력한 문장과 정규화한 글이 똑같은가 — 계획이 사용자 입력을 되풀이하는 줄 `이름(입력): 내용` 은 이름을 떼고 내용만 견준다."""
    if flat_sentence in exempt:
        return True
    if "(입력" in sentence:
        match = _ECHO_LABEL.match(sentence)
        if match and flat(sentence[match.end():]) in exempt:
            return True
    return False


def find_claims(text_or_sentences, *, experience_given=False, user_sentences=()):
    """글(한 덩어리 글자 또는 문장 목록)에서 지어낸 것으로 보이는 말을 찾아 `Claim(분류, 문장 번호, 근거 낱말)` 의 튜플로 돌려준다(문장 번호 순, 한 문장 안에서는 위반이 먼저).
    위반(`VIOLATIONS`)과 확인 권장(`REVIEWS`)이 함께 나오며 `is_violation(claim.category)` 로 가른다. 글이 한 덩어리면 `split_sentences` 로 나눈 번호이고, 목록이면 그 목록의 번호다.

    `experience_given=True`(사용자가 경험을 입력했다)면 `user_sentences`(사용자가 입력한 글 — 한 덩어리 글자나 목록)의 문장과 **정규화한 글이 똑같은 문장**만 위반에서 뺀다(띄어쓰기·기호·대소문자 차이는 무시). 부분만 겹치는 문장은 빼지 않는다. 그 밖의 문장은 그대로 검사한다. `experience_given=False` 면 `user_sentences` 를 보지 않는다(경험을 입력하지 않았는데
    경험이 나오면 어디에서 왔든 위반). 확인 권장은 이 예외와 상관없이 나오고 `MAX_FINDINGS`(500)건까지이며, **위반에는 상한이 없다**. 비밀·파일·네트워크는 쓰지 않는다."""
    return _scan(text_or_sentences, experience_given, user_sentences, True)


def find_violations(text_or_sentences, *, experience_given=False, user_sentences=()):
    """`find_claims` 중 위반(막아야 하는 것)만 — 확인 권장은 아예 찾지 않아 더 빠르다."""
    return _scan(text_or_sentences, experience_given, user_sentences, False)


def find_reviews(text_or_sentences):
    """`find_claims` 중 확인 권장(막지 않는 것)만 — 가격·날짜·시각·통계."""
    return tuple(claim for claim in find_claims(text_or_sentences) if not is_violation(claim.category))


__all__ = [
    "CASE", "Claim", "DATE", "DIALOGUE", "EXPERIENCE_BUY", "EXPERIENCE_EFFECT", "EXPERIENCE_INCOME", "EXPERIENCE_USE", "EXPERIENCE_VISIT", "LABELS", "MAX_FINDINGS", "PRICE", "REVIEWS", "STAT", "TIME",
    "VIOLATIONS", "find_claims", "find_reviews", "find_violations", "flat", "is_violation", "split_sentences",
]
