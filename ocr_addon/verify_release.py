# -*- coding: utf-8 -*-
"""verify_release.py - 빌드 흐름의 '산출물 점검' 단계(결정 D-527·D-531): 올리기 직전에 압축 파일·SHA256SUMS·PACKAGE_INFO.json 을 **빌드 스크립트의 말이 아니라 파일 자체에서** 다시 읽어 확인한다.

확인하는 것: ① 올리는 폴더에 정해진 셋뿐 ② 압축 파일의 해시·크기가 SHA256SUMS·PACKAGE_INFO.json 과 같다 ③ 압축 파일의 항목이 모두 맨 위 폴더 `ocr` 아래의 안전한 이름이고, 안의 정보 파일(OCR_INFO.json)의 파일 목록과 한 줄씩(이름·크기·해시) 같다
④ 모델 2개·사전이 잠금 값(models.lock.json)과 같다 ⑤ **라이선스 고지 파일이 압축 파일 안에 있다 — `licenses/` 폴더에 파일이 있고(그중 GEOS 라이선스 전문 `licenses/shapely/LICENSE_GEOS` 가 꼭 있고) `THIRD_PARTY_NOTICES.txt` 가 비어 있지 않으며 GEOS·LGPL 을 말하고, GEOS 가 별도 DLL 파일로 있다**(운영자 확인 030 ②).
⑥ **'없어야 할 것'도 압축 파일 쪽에서 다시 본다**(독립 검증 S 의 SP-1): FFmpeg DLL·pem·crt·key·기본 모델(R2)과 OpenSSL·진짜 urllib3·certifi 같은 금지 부품(R3)을 빌드와 같은 규칙 함수(build_rules.py)로 다시 판정하고,
⑦ 정보 파일에 적힌 빌드 점검 결과(checks.ok·problems·selftest)가 통과인지도 본다 — 빌드가 점검에 실패하고도 산출물을 만들거나 점검이 건너뛰어지는 길이 다시 열려도(빌드가 먼저 막든 이 점검이 먼저 막든) 금지 부품이 든 압축 파일은 올라가지 못한다.
표준 라이브러리만 쓰고 파일을 쓰지 않으며 네트워크를 쓰지 않는다. 하나라도 어긋나면 종료 코드 1 이고 흐름이 빨갛게 끝나 아무것도 올리지 않는다(2 는 인자·폴더 문제).
사용: python ocr_addon/verify_release.py --release <release 폴더>
"""
import argparse
import hashlib
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import build_rules as rules  # noqa: E402

TOP = "ocr"                                               # 압축 파일 맨 위 폴더 = 앱이 본체 옆에서 찾는 폴더 이름
RELEASE_FILES = ("SHA256SUMS", "PACKAGE_INFO.json")
ZIP_NAME = re.compile(r"ChanceBlogDesktop-OCR-%s-win64\.zip" % rules.VERSION_PATTERN)
NOTICE_ENTRY = TOP + "/THIRD_PARTY_NOTICES.txt"
LICENSES_PREFIX = TOP + "/licenses/"
GEOS_LICENSE_ENTRY = LICENSES_PREFIX + "shapely/LICENSE_GEOS"      # 빌드(build_ocr_addon.py 의 missing_outputs)가 꼭 만드는 GEOS 라이선스 전문 — 고지문이 가리키는 그 파일
GEOS_DLL = re.compile(TOP + r"/_internal/(?:[^/]+/)*[^/]*geos[^/]*\.dll")
MAX_ENTRIES = 2000                                        # 앱의 추가 도구 확인(service/ocr_addon.py)의 파일 목록 상한과 같다 — 이보다 길면 앱이 거절한다
DEFAULT_LOCK = os.path.join(HERE, "models.lock.json")
REJUDGE = "[압축 파일에서 다시 판정] "                       # 빌드의 규칙(R2·R3)을 압축 파일 쪽에서 다시 적용한 결과라는 표시


def sha256_of(data):
    return hashlib.sha256(data).hexdigest()


def file_facts(path):
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
    return size, digest.hexdigest()


def safe_entry(name):
    """압축 파일 항목 이름이 `ocr/…` 아래의 안전한 상대 이름인가(절대 경로·`..`·역슬래시·드라이브·빈 조각이 없다)."""
    if not name.startswith(TOP + "/") or chr(92) in name or ":" in name or "\x00" in name:
        return False
    return all(part not in ("", ".", "..") for part in name.split("/"))


def checks_problems(inner):
    """정보 파일(OCR_INFO.json)에 적힌 빌드 점검 결과가 '통과'인가 — ok 가 참·문제 기록이 빈 목록·자가 점검 통과·종료 코드 0. 참/거짓 글자가 숫자 0 이나 1 로 둔갑하지 못하게 형을 엄격히 본다."""
    checks = inner.get("checks")
    if not isinstance(checks, dict):
        return ["정보 파일의 빌드 점검 기록이 없다(checks)"]
    problems = []
    if checks.get("ok") is not True:
        problems.append("정보 파일의 빌드 점검 기록이 통과가 아니다(checks.ok)")
    listed = checks.get("problems")
    if listed != []:
        if isinstance(listed, list):
            problems.append("정보 파일의 빌드 점검 기록에 문제가 남아 있다(checks.problems): " + "; ".join(str(item)[:120] for item in listed[:3]))
        else:
            problems.append("정보 파일의 빌드 점검 기록에 문제 목록 칸이 없다(checks.problems)")
    if checks.get("selftest_ok") is not True:
        problems.append("정보 파일의 빌드 점검 기록에서 자가 점검이 통과가 아니다(checks.selftest_ok)")
    code = checks.get("selftest_exit")
    if isinstance(code, bool) or code != 0:
        problems.append("정보 파일의 빌드 점검 기록에서 자가 점검 종료 코드가 0 이 아니다(checks.selftest_exit)")
    return problems


def part_names(entries):
    """R3 가 보는 부품 이름들 — 압축 파일의 맨 위 폴더(ocr/) 직속 이름·_internal 직속 이름(폴더 포함)·모든 .pyd·.dll 파일 이름(어느 깊이든). 빌드의 묶음 폴더 훑기와 같은 범위다."""
    names = set()
    for name in entries:
        parts = name[len(TOP) + 1:].split("/")
        names.add(parts[0])
        if parts[0] == "_internal" and len(parts) > 1:
            names.add(parts[1])
        if parts[-1].lower().endswith((".pyd", ".dll")):
            names.add(parts[-1])
    return names


def read_entries(path):
    """압축 파일 -> ({이름: (바이트, SHA-256)}, {글 파일 이름: 글}, 문제들). 항목은 하나씩 읽어 해시만 남긴다(CRC 도 이때 확인된다)."""
    problems, entries, texts = [], {}, {}
    try:
        with zipfile.ZipFile(path) as archive:
            items = [item for item in archive.infolist() if not item.is_dir()]
            if len(items) > MAX_ENTRIES:
                problems.append("압축 파일의 항목이 너무 많다(%d개, 상한 %d)" % (len(items), MAX_ENTRIES))
            for item in items:
                name = item.filename
                if not safe_entry(name):
                    problems.append("압축 파일에 안전하지 않은 이름이 있다: %r" % name)
                    continue
                if name in entries:
                    problems.append("압축 파일에 같은 이름이 두 번 있다: " + name)
                    continue
                data = archive.read(name)
                entries[name] = (len(data), sha256_of(data))
                if name in (TOP + "/OCR_INFO.json", NOTICE_ENTRY):
                    texts[name] = data.decode("utf-8", "replace")
                if name.startswith(LICENSES_PREFIX) and not data:
                    problems.append("비어 있는 라이선스 파일이 있다: " + name)
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError) as error:
        problems.append("압축 파일을 읽지 못했다(%s)" % type(error).__name__)
    return entries, texts, problems


def load_json(path, label, problems):
    try:
        with open(path, "rb") as handle:
            value = json.loads(handle.read().decode("utf-8"))
    except (OSError, ValueError):
        problems.append("%s 를 읽지 못했다" % label)
        return None
    if not isinstance(value, dict):
        problems.append("%s 가 객체가 아니다" % label)
        return None
    return value


def release_problems(release, lock=None):
    """올리는 폴더를 점검한다 -> (문제 글 목록, 보여 줄 사실 사전). `lock` 은 시험이 작은 가짜 값을 넣는 자리이고 흐름은 저장소의 models.lock.json 을 쓴다."""
    problems, facts = [], {}
    names = sorted(os.listdir(release))
    zips = [name for name in names if ZIP_NAME.fullmatch(name)]
    if len(zips) != 1:
        return ["압축 파일(ChanceBlogDesktop-OCR-<버전>-win64.zip)이 정확히 하나여야 한다(%d개)" % len(zips)], facts
    if names != sorted(zips + list(RELEASE_FILES)):
        problems.append("올리는 폴더에 정해진 셋(압축 파일·SHA256SUMS·PACKAGE_INFO.json)이 아닌 파일이 있거나 빠졌다: %s" % names)
    zip_path = os.path.join(release, zips[0])
    size, digest = file_facts(zip_path)
    facts.update({"zip": zips[0], "bytes": size, "sha256": digest})
    sums_path = os.path.join(release, "SHA256SUMS")
    try:
        with open(sums_path, "rb") as handle:
            lines = handle.read().decode("utf-8").splitlines()
    except OSError:
        lines = []
    if lines != ["%s  %s" % (digest, zips[0])]:
        problems.append("SHA256SUMS 가 압축 파일의 실제 SHA-256 한 줄과 다르다")
    outer = load_json(os.path.join(release, "PACKAGE_INFO.json"), "PACKAGE_INFO.json", problems)
    if outer is not None:
        if outer.get("package") != {"name": zips[0], "sha256": digest, "bytes": size}:
            problems.append("PACKAGE_INFO.json 의 package(이름·SHA-256·크기)가 압축 파일의 실제 값과 다르다")
        if outer.get("variant") != "outer":
            problems.append("PACKAGE_INFO.json 의 variant 가 outer 가 아니다")
    entries, texts, more = read_entries(zip_path)
    problems += more
    facts["entries"] = len(entries)
    info_name = TOP + "/OCR_INFO.json"
    inner = None
    if info_name not in entries:
        problems.append("압축 파일 안에 " + info_name + " 가 없다")
    else:
        try:
            inner = json.loads(texts[info_name])
        except ValueError:
            problems.append("압축 파일 안 OCR_INFO.json 이 JSON 이 아니다")
        else:
            if not isinstance(inner, dict):                  # 객체가 아니면 정보 파일 검사 전체(name·proto·checks·목록 대조)가 건너뛰어지므로 그 자체를 실패로 센다(독립 검증 S 의 SP-7)
                problems.append("압축 파일 안 OCR_INFO.json 이 객체가 아니다")
    if isinstance(inner, dict):
        if inner.get("name") != "ocr_addon" or inner.get("proto") != 1:
            problems.append("OCR_INFO.json 의 name·proto 가 앱이 요구하는 값(ocr_addon·1)이 아니다")
        problems += checks_problems(inner)
        listed = {}
        for item in inner.get("files") if isinstance(inner.get("files"), list) else []:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                listed[TOP + "/" + item["path"]] = (item.get("bytes"), item.get("sha256"))
        if not listed:
            problems.append("OCR_INFO.json 의 파일 목록이 비어 있다")
        for name, value in sorted(listed.items()):
            if name not in entries:
                problems.append("정보 파일 목록에 있는데 압축 파일에 없다: " + name)
            elif entries[name] != value:
                problems.append("정보 파일 목록의 크기·SHA-256 이 압축 파일 안 파일과 다르다: " + name)
        for name in sorted(set(entries) - set(listed) - {info_name}):
            problems.append("압축 파일에 있는데 정보 파일 목록에 없다: " + name)
        if outer is not None:
            same = {key: value for key, value in outer.items() if key not in ("variant", "package")} == {key: value for key, value in inner.items() if key != "variant"}
            if not same:
                problems.append("PACKAGE_INFO.json 이 압축 파일 안 OCR_INFO.json 과 (variant·package 칸 말고도) 다르다")
    for need in (TOP + "/ocr_worker.exe",):
        if need not in entries:
            problems.append("압축 파일 안에 " + need + " 가 없다")
    lock = lock if lock is not None else load_json(DEFAULT_LOCK, "models.lock.json", problems)
    lock_bad = rules.lock_problems(lock) if lock is not None else []
    problems += ["models.lock.json: " + item for item in lock_bad]
    if lock is not None and not lock_bad:
        expected = rules.expected_files(lock)
        for key, (want_size, want_sha) in sorted(expected.items()):
            if entries.get(TOP + "/" + key) != (want_size, want_sha):
                problems.append("모델·사전이 잠금 값과 다르거나 없다: " + key)
        sizes = {name[len(TOP) + 1:]: value[0] for name, value in entries.items()}
        problems += [REJUDGE + item for item in rules.bundle_file_problems(sizes, expected, lambda key: entries[TOP + "/" + key][1])]      # R2: FFmpeg DLL·pem 류·기본 모델·작업자 exe·모델 해시
    found = sorted({rules.module_key(name) for name in part_names(entries)} & set(rules.FORBIDDEN_MODULES))                                  # R3: OpenSSL·진짜 urllib3·certifi 같은 금지 부품
    if found:
        problems.append(REJUDGE + "R3 묶음에 있으면 안 되는 부품(OpenSSL·진짜 urllib3·certifi 등): " + ", ".join(found))
    notice = texts.get(NOTICE_ENTRY)
    if notice is None:
        problems.append("라이선스 고지 파일 THIRD_PARTY_NOTICES.txt 가 압축 파일 안에 없다")
    elif not notice.strip():
        problems.append("THIRD_PARTY_NOTICES.txt 가 비어 있다")
    elif "geos" not in notice.lower() or "lgpl" not in notice.lower():
        problems.append("THIRD_PARTY_NOTICES.txt 가 GEOS·LGPL 을 말하지 않는다(운영자 확인 030 ② 의 고지 대상)")
    if notice is not None and notice.strip():                # 고지문 [5] 절(모델·글자 사전의 이름·출처·라이선스 표기)이 압축 파일 쪽에서도 있어야 한다 — 빌드 쪽 문이 우회돼도 여기서 거른다(독립 검증 S2 의 I3, 감사 후속)
        sections = [line for line in notice.splitlines() if line.startswith("[5] ")]
        if len(sections) != 1:
            problems.append("THIRD_PARTY_NOTICES.txt 에 모델과 글자 사전의 [5] 절이 정확히 하나여야 한다(지금 %d개)" % len(sections))
        elif lock is not None and not lock_bad:
            part = notice[notice.index(sections[0]):]
            for key, (want_size, want_sha) in sorted(expected.items()):
                if "파일 %s (%d바이트, SHA-256 %s)" % (key, want_size, want_sha) not in part:
                    problems.append("고지문 [5] 절이 모델·사전의 잠금 값(크기·SHA-256)과 다르거나 없다: " + key)
    license_files = sorted(name for name in entries if name.startswith(LICENSES_PREFIX))
    facts["license_files"] = len(license_files)
    if not license_files:
        problems.append("라이선스 전문 폴더 licenses/ 에 파일이 없다(압축 파일 안 " + LICENSES_PREFIX + ")")
    if not any(GEOS_DLL.fullmatch(name.lower()) for name in entries):
        problems.append("GEOS 가 별도 DLL 파일로 들어 있지 않다(_internal 아래 geos*.dll — 바꿔 끼울 수 있다는 고지의 전제)")
    if GEOS_LICENSE_ENTRY not in entries:                    # 합친 빌드는 이 파일이 없으면 점검·정보 파일 단계에서 이미 멈춘다 — 그 방어선이 없었던 산출물도 여기서 거른다
        problems.append("GEOS 라이선스 전문 " + GEOS_LICENSE_ENTRY[len(TOP) + 1:] + " 가 압축 파일 안에 없다(고지문이 가리키는 파일 — 운영자 확인 030 ② 의 고지 대상)")
    return problems, facts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", required=True, help="build_ocr_addon.py 가 만든 release 폴더(압축 파일·SHA256SUMS·PACKAGE_INFO.json)")
    parser.add_argument("--lock", default=None, help="시험용: 모델 잠금 파일(기본은 이 폴더의 models.lock.json)")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.release):
        print("[산출물 점검] release 폴더가 없다", file=sys.stderr)
        return 2
    lock = None
    if args.lock:
        with open(args.lock, "rb") as handle:
            lock = json.loads(handle.read().decode("utf-8"))
    problems, facts = release_problems(args.release, lock)
    if problems:
        print("[산출물 점검] 실패 — 문제 %d건" % len(problems))
        for item in problems:
            print("  ★ " + item)
        return 1
    print("[산출물 점검] 통과 — %s %s바이트 SHA-256 %s · 항목 %d개 · 라이선스 파일 %d개 + THIRD_PARTY_NOTICES.txt" % (facts["zip"], format(facts["bytes"], ","), facts["sha256"], facts["entries"], facts["license_files"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
