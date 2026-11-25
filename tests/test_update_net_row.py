"""`net/endpoints.py` 의 `update_check` 행(UPDATE 갈래가 확정, D-790)과 `update/source.py` 의 주소·내려받기 — 접속 틀 위에서의 동작을 가짜 서버로 확인한다.

지키는 것:
  1) 주소 만들기: 최신 릴리스의 두 파일과 태그가 정해진 릴리스의 자산만 만들어지고 나머지(다른 이름·모양이 틀린 태그·경로 구분자·점 구간)는 접속 **전에** 거절된다. 표의 소유자는 글 저장소와 같은 상수 하나에서 온다.
  2) 이동: 같은 호스트의 태그 길 → 자산 호스트로 따라가고(최대 세 번), 표 밖 호스트·평문·사용자 정보·네 번째 이동·표 밖 길은 `NET_RESPONSE_INVALID`(이유: 이동)이고 그 호스트로는 연결하지 않는다. 접근 토큰·쿠키는 어디에도 실리지 않는다.
  3) 내려받기: `request_to_file` 은 내려받기 길(태그 길)에서만 되고 최신 길·다른 용도에서는 접속 전에 거절된다. 크기 상한은 매니페스트의 `size`, 응답이 정한 이름은 쓰지 않는다.
  4) `User-Agent` 에 버전을 싣지 않는 용도는 `update_check` 하나뿐이고 나머지 용도는 그대로 `ChanceBlogDesktop/<버전>` 이다.
  5) 디스크 여유·검증·낡은 폴더 정리 같은 작은 규칙(`source.check_disk`·`verify_staged`·`find_staged_run`)도 여기서 본다.
네트워크 없이 돈다(가짜 소켓).
"""
import dataclasses
import hashlib
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

import net_support as ns  # noqa: E402
import outgoing_support as og  # noqa: E402
import update_flow_support as fs  # noqa: E402
import update_support as us  # noqa: E402

from chanceblog_desktop.errors import AppError  # noqa: E402
from chanceblog_desktop.net import client, endpoints, errors  # noqa: E402
from chanceblog_desktop.publish import gitrepo  # noqa: E402
from chanceblog_desktop.update import manifest, source  # noqa: E402

TAG_URL = f"https://github.com{fs.BASE}/download/v1.0.1/a.bin"


class RowTest(unittest.TestCase):
    def test_the_row_is_the_documented_one_and_no_placeholder_remains(self):
        row = endpoints.ENDPOINTS["update_check"]
        self.assertEqual((row.host, row.max_redirects, row.redirect_hosts, row.accept, row.send_version), ("github.com", 3, ("release-assets.githubusercontent.com",), "*/*", False))
        self.assertEqual((row.download_timeout, row.max_download), (600.0, 200 * 1024 * 1024))
        self.assertEqual(endpoints.MAX_UPDATE_FILE, manifest.MAX_FILE_BYTES, "표의 내려받기 상한과 매니페스트의 파일 크기 상한이 같다")
        self.assertEqual(endpoints.PLACEHOLDER_USES, ())
        self.assertEqual(endpoints.RELEASE_BASE, f"/{gitrepo.EXPECTED_OWNER}/chanceblog-desktop/releases")
        self.assertEqual([route.shown for route in row.routes], ["/(릴리스 최신 매니페스트)", "/(릴리스 자산)"])
        self.assertEqual([route.download for route in row.routes], [False, True])
        self.assertEqual(endpoints.table_problems(), [])
        self.assertEqual([use for use, endpoint in endpoints.ENDPOINTS.items() if not endpoint.send_version], ["update_check"])
        self.assertEqual(endpoints.user_agent("1.2.3"), "ChanceBlogDesktop/1.2.3")
        self.assertEqual(endpoints.user_agent("1.2.3", versioned=False), "ChanceBlogDesktop")

    def test_the_asset_host_belongs_to_no_other_use_and_the_table_has_exactly_five_hosts(self):
        hosts = {use: ({endpoint.host} | set(endpoint.redirect_hosts)) for use, endpoint in endpoints.ENDPOINTS.items()}
        self.assertEqual([use for use, found in hosts.items() if endpoints.RELEASE_ASSET_HOST in found], ["update_check"])
        self.assertEqual(len(set().union(*hosts.values())), 5)
        self.assertLessEqual(len(hosts["update_check"]), 2, "NET 의 '업데이트 확인의 호스트는 최대 둘' 규칙 그대로")

    def test_the_route_texts_are_module_constants_built_from_the_owner_constant(self):
        self.assertTrue(endpoints.MANIFEST_PATH.startswith(endpoints.RELEASE_BASE) and endpoints.ASSET_PATH.startswith(endpoints.RELEASE_BASE))
        self.assertIn(gitrepo.EXPECTED_OWNER, endpoints.RELEASE_BASE)


class UrlBuildingTest(unittest.TestCase):
    def test_only_the_two_latest_files_and_valid_tagged_assets_get_an_address(self):
        base = f"https://github.com{fs.BASE}"
        self.assertEqual(source.latest_url("update-manifest.json"), base + "/latest/download/update-manifest.json")
        self.assertEqual(source.latest_url("update-manifest.json.sig"), base + "/latest/download/update-manifest.json.sig")
        self.assertEqual(source.asset_url("v1.0.1", "ChanceBlogDesktopApp-1.0.1-stable-full.nupkg"), base + "/download/v1.0.1/ChanceBlogDesktopApp-1.0.1-stable-full.nupkg")
        self.assertEqual(source.asset_url("v0.9.0-rc.2", "releases.stable.json"), base + "/download/v0.9.0-rc.2/releases.stable.json")
        for name in ("other.json", "", "../update-manifest.json", "update-manifest.json.sig.bak", None, "UPDATE-MANIFEST.JSON"):
            with self.assertRaises((ValueError, KeyError), msg=repr(name)):
                source.latest_url(name)
        for tag, name in (("1.0.1", "a.bin"), ("v1.0", "a.bin"), ("v1.0.1-beta.1", "a.bin"), ("v1.0.1/../x", "a.bin"), ("v1.0.1", "../a.bin"), ("v1.0.1", "a/b"), ("v1.0.1", ".hidden"), ("v1.0.1", "a" * 101),
                          ("v1.0.1", "CON"), ("v1.0.1", "x."), ("", "a.bin"), (None, "a.bin"), ("v1.0.1", None), ("v1.0.1+3", "a.bin"), ("v1.0.1\n", "a.bin"), ("v１.0.1", "a.bin")):
            with self.assertRaises(ValueError, msg=repr((tag, name))):
                source.asset_url(tag, name)

    def test_every_address_the_module_builds_passes_the_connection_table(self):
        for url in (source.latest_url("update-manifest.json"), source.latest_url("update-manifest.json.sig"), source.asset_url("v1.0.1", "a.bin")):
            self.assertTrue(any(route.method == "GET" and route.matches(url.split("github.com", 1)[1]) for route in endpoints.ENDPOINTS["update_check"].routes), url)


class RedirectTest(unittest.TestCase):
    def run_request(self, server, url=None, *, to_file=None, **kwargs):
        harness = fs.FlowHarness(self, server)
        with harness, og.Tripwire() as wire:
            try:
                if to_file is None:
                    result = harness.client.request("update_check", "GET", url or source.latest_url("update-manifest.json"), **kwargs)
                else:
                    result = harness.client.request_to_file("update_check", "GET", url or TAG_URL, to_file, **kwargs)
            except errors.NetError as error:
                result = error
        self.assertEqual(wire.calls, [])
        return harness, result

    def chain(self, hops, *, final_host=fs.CDN_HOST, final_path="/x?sig=1"):
        server = fs.ReleaseServer()
        server.redirect("github.com", f"{fs.BASE}/latest/download/update-manifest.json", f"https://github.com{fs.BASE}/download/v1.0.1/update-manifest.json")
        previous = f"{fs.BASE}/download/v1.0.1/update-manifest.json"
        for index in range(hops - 2):
            nxt = f"{fs.BASE}/download/v1.0.{index + 2}/update-manifest.json"
            server.redirect("github.com", previous, f"https://github.com{nxt}")
            previous = nxt
        server.redirect("github.com", previous, f"https://{final_host}{final_path}")
        server.put(final_host, final_path, b'{"ok": true}')
        return server

    def test_the_documented_two_hop_chain_works_and_a_fourth_hop_is_refused(self):
        harness, response = self.run_request(self.chain(2))
        self.assertEqual((response.status, response.body, [host for host, _ in harness.dials]), (200, b'{"ok": true}', ["github.com", "github.com", fs.CDN_HOST]))
        harness, response = self.run_request(self.chain(3))
        self.assertEqual(response.status, 200)
        harness, error = self.run_request(self.chain(4))
        self.assertIsInstance(error, errors.NetError)
        self.assertEqual(error.code, "NET_RESPONSE_INVALID")
        self.assertIn(errors.REASON_REDIRECT, error.rendered().message)
        self.assertEqual(len(harness.dials), 4, "네 번째 이동은 따라가지 않는다")

    def test_a_redirect_to_an_unlisted_host_plain_text_userinfo_port_or_a_bad_path_never_connects(self):
        for label, location in (("다른 호스트", "https://evil.example.test/x?sig=1"), ("평문", f"http://{fs.CDN_HOST}/x?sig=1"), ("사용자 정보", f"https://u@{fs.CDN_HOST}/x?sig=1"), ("포트", f"https://{fs.CDN_HOST}:8443/x?sig=1"),
                                ("닮은 이름", f"https://{fs.CDN_HOST}.evil.example.test/x?sig=1"), ("하위 이름", f"https://x.{fs.CDN_HOST}/x?sig=1"), ("옛 호스트", "https://objects.githubusercontent.com/x?sig=1"),
                                ("나쁜 글자", f"https://{fs.CDN_HOST}/x?sig=<script>"), ("조각", f"https://{fs.CDN_HOST}/x#frag"), ("표 밖 길(같은 호스트)", f"https://github.com/{gitrepo.EXPECTED_OWNER}/chanceblog/releases/latest/download/update-manifest.json"),
                                ("API 길", f"https://github.com/repos/{gitrepo.EXPECTED_OWNER}/chanceblog-desktop/releases/latest")):
            with self.subTest(label=label):
                server = fs.ReleaseServer()
                server.redirect("github.com", f"{fs.BASE}/latest/download/update-manifest.json", location)
                harness, error = self.run_request(server)
                self.assertIsInstance(error, errors.NetError, label)
                self.assertEqual(error.code, "NET_RESPONSE_INVALID", label)
                self.assertEqual([host for host, _ in harness.dials], ["github.com"], "둘째 연결은 만들어지지 않는다")

    def test_the_asset_host_cannot_redirect_to_a_listed_host_and_loops_are_refused(self):
        server = fs.ReleaseServer()
        server.redirect("github.com", f"{fs.BASE}/latest/download/update-manifest.json", f"https://{fs.CDN_HOST}/a?sig=1")
        server.redirect(fs.CDN_HOST, "/a?sig=1", f"https://{fs.CDN_HOST}/a?sig=1")
        harness, error = self.run_request(server)
        self.assertEqual((error.code, len(harness.dials)), ("NET_RESPONSE_INVALID", 2), "같은 주소로 돌아오는 이동")

    def test_neither_a_token_nor_a_cookie_can_be_attached_and_no_request_carries_one(self):
        harness, error = self.run_request(self.chain(2), bearer="tok.en")
        self.assertEqual((error.code, error.detail, harness.dials), ("UNEXPECTED_ERROR", "update_check:bearer", []))
        harness, response = self.run_request(self.chain(2))
        for sock in harness.made:
            self.assertNotRegex(bytes(sock.sent).decode("ascii"), r"(?i)authorization|cookie")

    def test_a_download_needs_the_download_route_and_is_refused_on_the_latest_route_before_connecting(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness, error = self.run_request(self.chain(2), source.latest_url("update-manifest.json"), to_file=Path(tmp) / "x.part", max_bytes=100)
            self.assertEqual((error.code, error.detail, harness.dials), ("UNEXPECTED_ERROR", "update_check:download", []))
            self.assertFalse((Path(tmp) / "x.part").exists())

    def test_the_download_goes_through_the_tag_route_and_the_asset_host_and_writes_only_the_chosen_file(self):
        body = bytes(range(200)) * 10
        server = fs.ReleaseServer()
        server.redirect("github.com", f"{fs.BASE}/download/v1.0.1/a.bin", f"https://{fs.CDN_HOST}/p?sig=1&rscd=attachment%3B+filename%3Devil.exe")
        server.put(fs.CDN_HOST, "/p?sig=1&rscd=attachment%3B+filename%3Devil.exe", body, headers=[("Content-Disposition", 'attachment; filename="../../evil.exe"')])
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "chosen.part"
            harness, response = self.run_request(server, to_file=dest, max_bytes=len(body), expected_sha256=hashlib.sha256(body).hexdigest())
            self.assertEqual((response.status, response.file_size, dest.read_bytes()), (200, len(body), body))
            self.assertEqual(sorted(path.name for path in Path(tmp).iterdir()), ["chosen.part"], "응답이 정한 이름·경로는 쓰지 않는다")
            self.assertFalse((Path(tmp).parent / "evil.exe").exists())

    def test_the_size_cap_is_the_callers_exact_size_and_a_longer_body_is_refused_with_the_file_removed(self):
        body = b"x" * 1000
        server = fs.ReleaseServer()
        server.redirect("github.com", f"{fs.BASE}/download/v1.0.1/a.bin", f"https://{fs.CDN_HOST}/p?sig=1")
        server.put(fs.CDN_HOST, "/p?sig=1", body)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "x.part"
            harness, error = self.run_request(server, to_file=dest, max_bytes=999)
            self.assertEqual(error.code, "NET_RESPONSE_INVALID")
            self.assertFalse(dest.exists())

    def test_other_uses_cannot_reach_the_release_host_or_the_asset_host(self):
        for use in ("pages_site", "blogger_oauth", "blogger_read", "blogger_draft"):
            harness = fs.FlowHarness(self, fs.ReleaseServer(), switches=ns.USE_SWITCHES[use])
            with harness:
                with self.assertRaises(errors.NetError) as caught:
                    harness.client.request(use, "GET", f"https://{fs.CDN_HOST}/x?sig=1")
            self.assertEqual((caught.exception.code, harness.dials), ("UNEXPECTED_ERROR", []), use)


class SmallRulesTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(holder.cleanup)
        self.folder = Path(holder.name) / "update"

    def test_the_disk_rule_is_three_times_the_files_plus_the_backup_and_the_boundary_passes(self):
        needed = source.check_disk(self.folder, [100, 50], 70, lambda folder: 10 ** 9)
        self.assertEqual(needed, 150 * 3 + 70)
        source.check_disk(self.folder, [100, 50], 70, lambda folder: needed)
        with self.assertRaises(AppError) as caught:
            source.check_disk(self.folder, [100, 50], 70, lambda folder: needed - 1)
        self.assertEqual(caught.exception.code, "DISK_FULL")
        self.assertEqual(source.check_disk(self.folder, [1], -5, lambda folder: 3), 3, "음수 백업 예상은 0 으로 센다")
        self.assertEqual(source.DISK_MULTIPLIER, 3)

    def test_the_default_free_space_reader_walks_up_to_an_existing_folder(self):
        self.assertGreater(source.default_free_bytes(self.folder / "not" / "there" / "yet"), 0)

    def test_the_restage_check_reads_the_disk_again_and_catches_a_changed_or_missing_file(self):
        release = fs.Release("1.0.1")
        verified = manifest.read_and_verify(release.manifest_bytes, release.signature, keyring=fs.RING)
        run = self.folder / "staging" / "r1"
        run.mkdir(parents=True)
        files = {}
        for role in ("package", "feed"):
            entry = verified.file(role)
            (run / entry.name).write_bytes(release.bodies[entry.name])
            files[role] = run / entry.name
        staged = source.StagedUpdate(run, files, verified)
        self.assertTrue(source.verify_staged(staged))
        path = files["feed"]
        original = path.read_bytes()
        path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        with self.assertRaises(AppError) as caught:
            source.verify_staged(staged)
        self.assertEqual((caught.exception.code, caught.exception.detail), ("UPDATE_SIGNATURE_INVALID", "restage:feed"))
        path.write_bytes(original + b"x")
        with self.assertRaises(AppError):
            source.verify_staged(staged)
        path.unlink()
        with self.assertRaises(AppError):
            source.verify_staged(staged)

    def test_the_kept_run_is_found_by_the_version_in_its_manifest_copy(self):
        release = fs.Release("1.0.1")
        other = fs.Release("1.0.2")
        for name, item in (("a", release), ("b", other)):
            run = self.folder / "staging" / name
            run.mkdir(parents=True)
            (run / source.MANIFEST_COPY).write_bytes(item.manifest_bytes)
        broken = self.folder / "staging" / "c"
        broken.mkdir()
        (broken / source.MANIFEST_COPY).write_bytes(b"{broken")
        self.assertEqual(source.find_staged_run(self.folder, "1.0.1").name, "a")
        self.assertEqual(source.find_staged_run(self.folder, "1.0.2").name, "b")
        self.assertIsNone(source.find_staged_run(self.folder, "9.9.9"))
        self.assertIsNone(source.find_staged_run(self.folder / "nowhere", "1.0.1"))

    def test_the_source_module_formats_nothing_from_the_response(self):
        text = (ROOT / "src" / "chanceblog_desktop" / "update" / "source.py").read_text(encoding="utf-8")
        for word in ("response.headers", "Content-Disposition", "Location", ".format(", "os.system"):
            self.assertNotIn(word, text, word)


if __name__ == "__main__":
    unittest.main()
