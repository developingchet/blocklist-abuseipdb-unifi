import csv
from datetime import datetime, timedelta, timezone
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import sync

from sync import parse_feed, write_feed, latest_upstream_revision

NOW = datetime(2026, 11, 11, 19, 0, tzinfo=timezone.utc)


def fixture(count=16, updated=NOW):
    entries = [f"198.51.100.{n}" for n in range(count)]
    return (f"# Last updated: {updated:%Y-%m-%d %H:%M:%S UTC}\n"
            f"# Number of ips: {count}\n" + "\n".join(entries) + "\n").encode()


class FeedTests(unittest.TestCase):
    def setUp(self):
        clock = patch.object(sync, "utc_now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)

    def publish(self, output, count=16, previous=None):
        with patch.object(sync, "latest_upstream_revision", return_value="a" * 40), \
                patch.object(sync, "download", return_value=fixture(count)), \
                patch.object(sync, "MIN_ENTRIES", 1):
            sync.synchronize(output, previous)

    @staticmethod
    def snapshot(output):
        return {p.name: p.read_bytes() for p in output.iterdir()}

    def test_unchanged_published_revision_skips_all_feed_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            published = root / "published"
            self.publish(published)
            before = self.snapshot(published)
            destination = root / "next"
            with patch.object(sync, "latest_upstream_revision", return_value="a" * 40) as revision, \
                    patch.object(sync, "download") as download, \
                    patch.object(sync, "build_snapshot") as build:
                changed = sync.synchronize(destination, published / "manifest.json", skip_unchanged=True)
            self.assertFalse(changed)
            revision.assert_called_once_with()
            download.assert_not_called()
            build.assert_not_called()
            self.assertFalse(destination.exists())
            self.assertEqual(self.snapshot(published), before)

    def test_local_skip_preserves_snapshot_and_repairs_missing_or_modified_feeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "feeds"
            self.publish(output)
            before = self.snapshot(output)
            with patch.object(sync, "latest_upstream_revision", return_value="a" * 40), \
                    patch.object(sync, "download") as download:
                self.assertFalse(sync.synchronize(output, skip_unchanged=True))
                download.assert_not_called()
            self.assertEqual(self.snapshot(output), before)
            for filename in ("abuseipdb-s100-1d.txt", "abuseipdb-s100-3d.csv",
                             "abuseipdb-s100-365d-unifi-08.txt"):
                for missing in (False, True):
                    with self.subTest(filename=filename, missing=missing):
                        path = output / filename
                        if missing:
                            path.unlink()
                        else:
                            path.write_text("203.0.113.1\n")
                        with patch.object(sync, "latest_upstream_revision", return_value="a" * 40), \
                                patch.object(sync, "download", return_value=fixture()), \
                                patch.object(sync, "MIN_ENTRIES", 1):
                            self.assertTrue(sync.synchronize(output, skip_unchanged=True))
                        self.assertEqual(self.snapshot(output), before)

    def test_changed_revision_rebuilds_all_windows_with_one_revision_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            published, destination = root / "published", root / "next"
            self.publish(published)
            with patch.object(sync, "latest_upstream_revision", return_value="b" * 40) as revision, \
                    patch.object(sync, "download", return_value=fixture()) as download, \
                    patch.object(sync, "MIN_ENTRIES", 1):
                self.assertTrue(sync.synchronize(destination, published / "manifest.json", skip_unchanged=True))
            revision.assert_called_once_with()
            self.assertEqual(download.call_count, 10)
            self.assertTrue(all(f"/{'b' * 40}/" in call.args[0] for call in download.call_args_list))
            self.assertEqual(len(json.loads((destination / "manifest.json").read_text())["feeds"]), 10)

    def test_first_run_with_skip_enabled_still_publishes_every_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "feeds"
            with patch.object(sync, "latest_upstream_revision", return_value="a" * 40), \
                    patch.object(sync, "download", return_value=fixture()) as download, \
                    patch.object(sync, "MIN_ENTRIES", 1):
                self.assertTrue(sync.synchronize(output, skip_unchanged=True))
            self.assertEqual(download.call_count, 10)
            self.assertTrue((output / "manifest.json").is_file())

    def test_unchanged_revision_cannot_hide_stalled_publication_or_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            published, destination = root / "published", root / "next"
            self.publish(published)
            original = (published / "manifest.json").read_text()
            for field in ("generated_at", "upstream_updated_at"):
                manifest = json.loads(original)
                target = manifest if field == "generated_at" else manifest["feeds"]["abuseipdb-s100-365d"]
                target[field] = sync.timestamp(NOW - timedelta(hours=3, seconds=1))
                (published / "manifest.json").write_text(json.dumps(manifest))
                with patch.object(sync, "latest_upstream_revision", return_value="a" * 40), \
                        patch.object(sync, "download") as download, \
                        self.assertRaisesRegex(ValueError, "overdue"):
                    sync.synchronize(destination, published / "manifest.json", skip_unchanged=True)
                download.assert_not_called()
                self.assertFalse(destination.exists())

    def test_legacy_manifest_is_rebuilt_even_when_revision_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            published, destination = root / "published", root / "next"
            self.publish(published)
            manifest = json.loads((published / "manifest.json").read_text())
            del manifest["schema_version"]
            del manifest["generated_at"]
            for detail in manifest["feeds"].values():
                del detail["upstream_updated_at"]
            (published / "manifest.json").write_text(json.dumps(manifest))
            with patch.object(sync, "latest_upstream_revision", return_value="a" * 40), \
                    patch.object(sync, "download", return_value=fixture()) as download, \
                    patch.object(sync, "MIN_ENTRIES", 1):
                self.assertTrue(sync.synchronize(destination, published / "manifest.json", skip_unchanged=True))
            self.assertEqual(download.call_count, 10)
            self.assertIn("generated_at", json.loads((destination / "manifest.json").read_text()))

    def test_cli_reports_changed_output_for_workflow_publication_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            for changed in (True, False):
                result = Path(tmp) / str(changed)
                with patch.object(sync, "synchronize", return_value=changed) as convert, \
                        patch.object(sync.sys, "argv", ["sync.py", "--skip-unchanged"]), \
                        patch.dict(sync.os.environ, {"GITHUB_OUTPUT": str(result)}):
                    self.assertEqual(sync.main(), 0)
                self.assertEqual(result.read_text(), f"changed={str(changed).lower()}\n")
                self.assertTrue(convert.call_args.kwargs["skip_unchanged"])

    def test_growth_then_shrink_preserves_parts_using_published_manifest(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sync, "CHUNK_SIZE", 4), \
                patch.object(sync, "MIN_PARTS", {}):
            root = Path(tmp)
            first, second = root / "first", root / "second"
            self.publish(first, 9)
            self.publish(second, 8, first / "manifest.json")
            manifest = json.loads((second / "manifest.json").read_text())
            for detail in manifest["feeds"].values():
                self.assertEqual(len(detail["unifi_parts"]), 3)
                self.assertEqual(sum(p["entries"] for p in detail["unifi_parts"]), 8)
                self.assertTrue(all((second / p["file"]).is_file() for p in detail["unifi_parts"]))

    def test_failed_refresh_preserves_every_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "feeds"
            self.publish(output)
            before = self.snapshot(output)
            def broken(url):
                return b"invalid\n" if "-365d.ipv4" in url else fixture(20)
            with patch.object(sync, "latest_upstream_revision", return_value="b" * 40), \
                    patch.object(sync, "download", side_effect=broken), \
                    patch.object(sync, "MIN_ENTRIES", 1), self.assertRaises(ValueError):
                sync.synchronize(output)
            self.assertEqual(self.snapshot(output), before)
            self.assertFalse((output.parent / ".feeds.lock").exists())

    def test_local_refresh_keeps_parts_and_rejects_unfillable_reservation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sync, "CHUNK_SIZE", 4), \
                patch.object(sync, "MIN_PARTS", {}):
            output = Path(tmp) / "feeds"
            self.publish(output, 9)
            self.publish(output, 8)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertTrue(all(len(d["unifi_parts"]) == 3 for d in manifest["feeds"].values()))
            before = self.snapshot(output)
            with self.assertRaisesRegex(ValueError, "nonempty parts"):
                self.publish(output, 2)
            self.assertEqual(self.snapshot(output), before)

    def test_install_failure_rolls_back_old_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "feeds"
            self.publish(output)
            before = self.snapshot(output)
            real_rename = Path.rename
            def fail_install(path, target):
                if path.name == "snapshot":
                    raise OSError("simulated installation failure")
                return real_rename(path, target)
            with patch.object(Path, "rename", fail_install), self.assertRaises(OSError):
                self.publish(output, 20)
            self.assertEqual(self.snapshot(output), before)
            self.assertFalse((output.parent / ".feeds.previous").exists())

    def test_failed_rollback_retains_recovery_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "feeds"
            self.publish(output)
            before = self.snapshot(output)
            real_rename = Path.rename
            def fail_install_and_restore(path, target):
                if path.name in ("snapshot", ".feeds.previous"):
                    raise OSError("simulated failure")
                return real_rename(path, target)
            with patch.object(Path, "rename", fail_install_and_restore), self.assertRaises(OSError):
                self.publish(output, 20)
            backup = output.parent / ".feeds.previous"
            self.assertEqual(self.snapshot(backup), before)
            with self.assertRaisesRegex(ValueError, "Recovery snapshot"):
                self.publish(output)

    def test_existing_lock_blocks_concurrent_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "feeds"
            lock = output.parent / ".feeds.lock"
            lock.touch()
            with self.assertRaisesRegex(RuntimeError, "lock exists"):
                self.publish(output)
            self.assertTrue(lock.exists())
            self.assertFalse(output.exists())

    def test_unmanaged_output_and_corrupt_state_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "feeds"
            output.mkdir()
            (output / "important.txt").write_text("keep me")
            with self.assertRaisesRegex(ValueError, "without a manifest"):
                self.publish(output)
            (output / "manifest.json").write_text("{}")
            before = self.snapshot(output)
            with self.assertRaises(ValueError):
                self.publish(output)
            self.assertEqual(self.snapshot(output), before)

    def test_previous_state_is_not_silently_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "feeds"
            self.publish(output)
            (output / "important.txt").write_text("keep me")
            before = self.snapshot(output)
            with self.assertRaisesRegex(ValueError, "unmanaged"):
                self.publish(output)
            self.assertEqual(self.snapshot(output), before)

    def test_freshness_rejects_missing_duplicate_stale_and_future_metadata(self):
        for raw in (b"# Number of ips: 1\n1.2.3.4\n", fixture(updated=NOW - timedelta(hours=3, seconds=1)),
                    fixture(updated=NOW + timedelta(hours=1)),
                    fixture() + b"# Number of ips: 16\n", fixture() + b"# Last updated: bad\n"):
            with self.subTest(raw=raw[:100]), self.assertRaises(ValueError):
                sync.source_updated_at(raw, "test", NOW)
        self.assertEqual(sync.source_updated_at(fixture(), "test", NOW), NOW)

    def test_stale_upstream_cannot_replace_valid_feeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "feeds"
            self.publish(output)
            before = self.snapshot(output)
            with patch.object(sync, "latest_upstream_revision", return_value="a" * 40), \
                    patch.object(sync, "download", return_value=fixture(updated=NOW - timedelta(days=1))), \
                    self.assertRaisesRegex(ValueError, "stale"):
                sync.synchronize(output)
            self.assertEqual(self.snapshot(output), before)

    def test_watchdog_checks_all_windows_and_generation_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "feeds"
            self.publish(output)
            manifest = json.loads((output / "manifest.json").read_text())
            with patch.object(sync, "download", return_value=json.dumps(manifest).encode()):
                sync.check_health("https://example.test/manifest.json")
            for field in ("generated_at", "upstream_updated_at"):
                bad = json.loads(json.dumps(manifest))
                target = bad if field == "generated_at" else bad["feeds"]["abuseipdb-s100-365d"]
                target[field] = sync.timestamp(NOW - timedelta(hours=3, seconds=1))
                with patch.object(sync, "download", return_value=json.dumps(bad).encode()), \
                        self.assertRaisesRegex(ValueError, "overdue"):
                    sync.check_health("https://example.test/manifest.json")

    def test_health_failure_identifies_stale_window_and_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "feeds"
            self.publish(output)
            manifest = json.loads((output / "manifest.json").read_text())
            manifest["feeds"]["abuseipdb-s100-365d"]["upstream_updated_at"] = sync.timestamp(NOW - timedelta(hours=6))
            with self.assertRaisesRegex(ValueError, r"365d upstream data is overdue:.*6\.0 hours old; maximum 3\.0 hours"):
                sync.validate_freshness(manifest, NOW)

    def test_download_retries_transient_errors_but_not_not_found(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"good"
        transient = HTTPError("https://example.test", 503, "retry", {}, None)
        with patch.object(sync, "urlopen", side_effect=[transient, response]) as request, \
                patch.object(sync.time, "sleep"):
            self.assertEqual(sync.download("https://example.test"), b"good")
            self.assertEqual(request.call_count, 2)
        with patch.object(sync, "urlopen", side_effect=HTTPError("https://example.test", 404, "missing", {}, None)) as request:
            with self.assertRaises(HTTPError):
                sync.download("https://example.test")
            self.assertEqual(request.call_count, 1)

    def test_oversized_download_is_rejected(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"12345"
        with patch.object(sync, "MAX_BYTES", 4), patch.object(sync, "urlopen", return_value=response), \
                self.assertRaisesRegex(ValueError, "safety limit"):
            sync.download("https://example.test")

    def test_download_retries_interrupted_reads_and_bounds_retry_after(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"good"
        failures = [sync.IncompleteRead(b"partial", 20), ConnectionResetError("reset"),
                    HTTPError("https://example.test", 429, "limited", {"Retry-After": "9999"}, None)]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(sync, "urlopen", side_effect=[failure, response]), \
                    patch.object(sync.time, "sleep") as sleep:
                self.assertEqual(sync.download("https://example.test"), b"good")
                self.assertEqual(sleep.call_args.args[0], 120 if isinstance(failure, HTTPError) else 1)

    def test_decorated_source_is_stripped_without_reordering(self):
        raw = (
            b"# Aggregated Blocklist for AbuseIPDB\n"
            b"# Number of ips: 3\n"
            b"1.2.3.4          # US 64500 Example ASN\n"
            b"192.0.2.0/24     # ZZ - Example subnet\n"
            b"5.6.7.8 # EU\n"
        )
        self.assertEqual(parse_feed(raw, "test"), ["1.2.3.4", "192.0.2.0/24", "5.6.7.8"])

    def test_rejects_corruption_and_empty_feeds(self):
        for source in (b"", b"# comments only\n", b"1.2.3.4\nnot-an-ip\n", b"1.2.3.4,as123\n"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                parse_feed(source, "test")

    def test_rejects_mismatched_declared_count(self):
        with self.assertRaisesRegex(ValueError, "declares 2 entries"):
            parse_feed(b"# Number of ips: 2\n1.2.3.4\n", "test")

    def test_rejects_duplicate_addresses(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_feed(b"1.2.3.4\n1.2.3.4\n", "test")

    def test_rejects_ipv6_and_noncanonical_cidr(self):
        for entry in (b"2001:db8::1\n", b"192.0.2.1/24\n", b"01.2.3.4\n"):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                parse_feed(entry, "test")

    def test_csv_and_shards_are_lossless(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            entries = ["192.0.2.1", "192.0.2.2", "198.51.100.0/24", "203.0.113.1", "203.0.113.2"]
            import sync
            original = sync.CHUNK_SIZE
            try:
                sync.CHUNK_SIZE = 2
                info = write_feed(output, "sample", entries)
            finally:
                sync.CHUNK_SIZE = original
            self.assertEqual(info["entries"], 5)
            self.assertEqual(len(info["unifi_parts"]), 3)
            self.assertEqual((output / "sample.txt").read_text().splitlines(), entries)
            with (output / "sample.csv").open(newline="") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows, [[ip] for ip in entries])
            self.assertEqual((output / "sample.csv").read_text().splitlines(), entries)
            parts = []
            for item in info["unifi_parts"]:
                self.assertLessEqual(item["entries"], 2)
                parts += (output / item["file"]).read_text().splitlines()
            self.assertEqual(parts, entries)
            # Every published feed is headerless, with no comments or metadata.
            for feed in sorted(output.glob("*.txt")) + sorted(output.glob("*.csv")):
                lines = feed.read_text().splitlines()
                self.assertTrue(lines, feed.name)
                self.assertTrue(all("#" not in line and line in entries for line in lines), feed.name)


    def test_exact_unifi_chunk_boundary(self):
        # Verify the mirror's configured 100,000-entry chunk boundary.
        entries = [f"198.{(n >> 16) & 255}.{(n >> 8) & 255}.{n & 255}" for n in range(100_001)]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            info = write_feed(output, "boundary", entries)
            self.assertEqual(len(info["unifi_parts"]), 2)
            self.assertTrue(all(0 < x["entries"] <= 100_000 for x in info["unifi_parts"]))
            self.assertEqual(
                sum(len((output / x["file"]).read_text().splitlines()) for x in info["unifi_parts"]),
                len(entries),
            )

    def test_stable_unifi_part_urls_when_source_shrinks(self):
        entries = [f"198.51.100.{i}" for i in range(16)]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            for count in (16, 9):
                info = write_feed(output, "stable", entries[:count], minimum_parts=8)
                self.assertEqual(len(info["unifi_parts"]), 8)
                self.assertEqual(
                    [line for part in info["unifi_parts"] for line in
                     (output / part["file"]).read_text().splitlines()],
                    entries[:count],
                )
            self.assertTrue(all((output / f"stable-unifi-{n:02d}.txt").exists() for n in range(1, 9)))

    def test_end_to_end_generates_every_window_and_link_on_first_run(self):
        entries = [f"198.51.100.{n}" for n in range(16)]
        raw = fixture()
        sha = "0123456789abcdef0123456789abcdef01234567"
        def fake_download(url):
            return (json.dumps({"sha": sha}).encode() if url == sync.REVISION_API else raw)
        with tempfile.TemporaryDirectory() as tmp, patch.object(sync, "download", side_effect=fake_download), patch.object(sync, "MIN_ENTRIES", 16):
            output = Path(tmp)
            sync.synchronize(output)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(len(manifest["feeds"]), 10)
            self.assertEqual(manifest["upstream_revision"], sha)
            self.assertTrue(all(item["entries"] == 16 for item in manifest["feeds"].values()))
            self.assertTrue(all(f"/{sha}/" in item["upstream_url"] for item in manifest["feeds"].values()))

            catalog = (output / "README.md").read_text()
            self.assertEqual(len([line for line in catalog.splitlines() if line.startswith("| ")]) - 2, 10)
            for days in sync.DAYS:
                name = f"abuseipdb-s100-{days}d"
                feed = manifest["feeds"][name]
                self.assertEqual((output / feed["txt"]).read_text().splitlines(), entries)
                self.assertEqual((output / feed["csv"]).read_text().splitlines(), entries)
                self.assertEqual(len(feed["unifi_parts"]), sync.MIN_PARTS.get(days, 1))
                self.assertEqual(
                    [line for part in feed["unifi_parts"] for line in (output / part["file"]).read_text().splitlines()],
                    entries,
                )
                for filename in (feed["txt"], feed["csv"], *(p["file"] for p in feed["unifi_parts"])):
                    self.assertIn(f"/feeds/{filename}", catalog)
                    self.assertTrue(all("#" not in line for line in (output / filename).read_text().splitlines()))
            self.assertEqual(len(list(output.glob("*.txt"))), 10 + sum(sync.MIN_PARTS.get(d, 1) for d in sync.DAYS))
            self.assertEqual(len(list(output.glob("*.csv"))), 10)

    def test_invalid_upstream_prevents_publication(self):
        raw = fixture(2)
        def download_with_one_bad_source(url):
            if url == sync.REVISION_API:
                return b'{"sha":"0123456789abcdef0123456789abcdef01234567"}'
            return b"2001:db8::1\n" if "-14d.ipv4" in url else raw

        with tempfile.TemporaryDirectory() as tmp, patch.object(sync, "download", side_effect=download_with_one_bad_source), patch.object(sync, "MIN_ENTRIES", 2):
            output = Path(tmp)
            with self.assertRaisesRegex(ValueError, "invalid IPv4"):
                sync.synchronize(output)
            self.assertFalse((output / "manifest.json").exists())


    def test_invalid_upstream_revision_is_rejected(self):
        for payload in (b"not-json", b"{}", b'{"sha":"main"}', b"[]"):
            with self.subTest(payload=payload), patch.object(sync, "download", return_value=payload):
                with self.assertRaises(ValueError):
                    latest_upstream_revision()


if __name__ == "__main__":
    unittest.main()
