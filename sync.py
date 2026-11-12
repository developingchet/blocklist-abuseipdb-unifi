#!/usr/bin/env python3
"""Mirror borestad's annotated IPv4 feeds as plain TXT, CSV, and UniFi chunks."""

import argparse
from contextlib import contextmanager
import csv
from datetime import datetime, timedelta, timezone
import hashlib
from http.client import IncompleteRead
import math
import ipaddress
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SOURCE = "https://raw.githubusercontent.com/borestad/blocklist-abuseipdb"
REVISION_API = "https://api.github.com/repos/borestad/blocklist-abuseipdb/commits/main"
DAYS = (1, 3, 7, 14, 30, 60, 90, 120, 180, 365)
CHUNK_SIZE = 100_000
# Reserve stable UniFi part URLs even when upstream counts fluctuate downward.
# More parts are created automatically if growth requires them.
MIN_PARTS = {14: 2, 30: 2, 60: 2, 90: 3, 120: 4, 180: 5, 365: 8}
DEFAULT_REPOSITORY = "developingchet/blocklist-abuseipdb-unifi"
MAX_BYTES = 90 * 1024 * 1024
MIN_ENTRIES = 100  # Fail closed on unexpectedly tiny upstream files.
COUNT_PATTERN = re.compile(r"^#\s*Number of ips:\s*(\d+)\s*$", re.IGNORECASE)
UPDATED_PATTERN = re.compile(r"^#\s*Last updated:\s*(.*?)\s*$", re.IGNORECASE)
MAX_SOURCE_AGE = timedelta(hours=3)
MAX_PUBLICATION_AGE = timedelta(hours=3)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def source_updated_at(raw: bytes, source_name: str, now: datetime) -> datetime:
    """Require upstream metadata and reject stale or future-dated datasets."""
    lines = raw.decode("utf-8-sig").splitlines()
    dates = [match.group(1) for line in lines
             if (match := UPDATED_PATTERN.fullmatch(line.strip()))]
    counts = [line for line in lines if COUNT_PATTERN.fullmatch(line.strip())]
    if len(dates) != 1 or len(counts) != 1:
        raise ValueError(f"{source_name}: expected exactly one update timestamp and count header")
    try:
        updated = datetime.strptime(dates[0], "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(f"{source_name}: invalid update timestamp") from exc
    if updated > now + timedelta(minutes=10) or now - updated > MAX_SOURCE_AGE:
        raise ValueError(f"{source_name}: upstream timestamp is stale or in the future: {dates[0]}")
    return updated


def load_previous_manifest(path: Path) -> dict:
    """Fail closed if published state cannot safely preserve established URLs."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("upstream") != "borestad/blocklist-abuseipdb":
        raise ValueError("Invalid previous manifest identity")
    feeds = data.get("feeds")
    if not isinstance(feeds, dict) or set(feeds) != {f"abuseipdb-s100-{d}d" for d in DAYS}:
        raise ValueError("Invalid previous manifest feeds")
    for days in DAYS:
        name = f"abuseipdb-s100-{days}d"
        detail = feeds.get(name)
        if (not isinstance(detail, dict) or detail.get("txt") != f"{name}.txt"
                or detail.get("csv") != f"{name}.csv"):
            raise ValueError(f"{name}: invalid previous feed filenames")
        parts = detail.get("unifi_parts")
        if not isinstance(parts, list) or not parts or len(parts) > 10_000:
            raise ValueError(f"{name}: invalid previous parts")
        for index, part in enumerate(parts, 1):
            if not isinstance(part, dict) or part.get("file") != f"{name}-unifi-{index:02d}.txt":
                raise ValueError(f"{name}: invalid previous part filename")
            if type(part.get("entries")) is not int or not 0 < part["entries"] <= CHUNK_SIZE:
                raise ValueError(f"{name}: invalid previous part count")
        if type(detail.get("entries")) is not int or sum(p["entries"] for p in parts) != detail["entries"]:
            raise ValueError(f"{name}: inconsistent previous entry count")
    return data


@contextmanager
def output_lock(output: Path):
    lock = output.parent / f".{output.name}.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(f"Another sync may be running; lock exists: {lock}") from exc
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink()


def download(url: str) -> bytes:
    """Bound downloads and retry transient network/server failures."""
    for attempt in range(3):
        try:
            headers = {"User-Agent": "blocklist-abuseipdb-unifi/1.0"}
            if url == REVISION_API:
                headers["Accept"] = "application/vnd.github+json"
                if token := os.environ.get("GITHUB_TOKEN"):
                    headers["Authorization"] = f"Bearer {token}"
            request = Request(url, headers=headers)
            with urlopen(request, timeout=60) as response:
                content = response.read(MAX_BYTES + 1)
            if len(content) > MAX_BYTES:
                raise ValueError(f"Upstream file exceeds the {MAX_BYTES} byte safety limit: {url}")
            return content
        except (HTTPError, URLError, TimeoutError, ConnectionError, IncompleteRead) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise RuntimeError(f"Cannot download {url} after 3 attempts") from exc
            delay = 2**attempt
            if isinstance(exc, HTTPError):
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                if retry_after.isdigit():
                    delay = max(delay, min(int(retry_after), 120))
            time.sleep(delay)
    raise AssertionError("unreachable")


def latest_upstream_revision() -> str:
    """Freeze a single upstream commit so all ten feeds are from one snapshot."""
    try:
        data = json.loads(download(REVISION_API))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Upstream GitHub commit response is invalid JSON") from exc
    revision = data.get("sha") if isinstance(data, dict) else None
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Upstream GitHub API returned an invalid commit SHA")
    return revision


def parse_feed(raw: bytes, source_name: str) -> list[str]:
    """Remove comments, preserve original order, and validate every IP/CIDR."""
    try:
        lines = raw.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"{source_name}: upstream is not UTF-8") from exc

    entries: dict[str, None] = {}
    expected_count = None
    non_comment_count = 0
    for line_number, line in enumerate(lines, 1):
        match = COUNT_PATTERN.match(line.strip())
        if match:
            expected_count = int(match.group(1))
        value = line.partition("#")[0].strip()
        if not value:
            continue
        parts = value.split()
        if len(parts) != 1:
            raise ValueError(f"{source_name}:{line_number}: unexpected fields: {value[:100]!r}")
        ip = parts[0]
        try:
            # Require canonical networks; do not expand, truncate, or reinterpret.
            if "/" in ip:
                if str(ipaddress.IPv4Network(ip, strict=True)) != ip:
                    raise ValueError("non-canonical CIDR")
            elif str(ipaddress.IPv4Address(ip)) != ip:
                raise ValueError("non-canonical IPv4")
        except ValueError as exc:
            raise ValueError(f"{source_name}:{line_number}: invalid IPv4 entry: {ip!r}") from exc
        non_comment_count += 1
        entries[ip] = None

    if expected_count is not None and expected_count != non_comment_count:
        raise ValueError(
            f"{source_name}: source header declares {expected_count} entries; found {non_comment_count}"
        )
    if not entries:
        raise ValueError(f"{source_name}: empty upstream feed")
    if non_comment_count != len(entries):
        raise ValueError(f"{source_name}: duplicate entries in upstream feed")
    return list(entries)


def write_feed(output: Path, name: str, entries: list[str], minimum_parts: int = 1) -> dict:
    """Write headerless TXT/CSV and stable UniFi TXT shards of <=100k entries."""
    txt = output / f"{name}.txt"
    txt.write_text("\n".join(entries) + "\n", encoding="ascii", newline="\n")

    with (output / f"{name}.csv").open("w", encoding="ascii", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerows((ip,) for ip in entries)

    chunks = []
    parts = max(minimum_parts, math.ceil(len(entries) / CHUNK_SIZE))
    if parts > len(entries):
        raise ValueError(f"{name}: too few entries for {parts} nonempty parts")
    for index in range(parts):
        # Balanced partitions retain the original ordering and prevent unused
        # shard URLs from disappearing when upstream counts briefly shrink.
        start = len(entries) * index // parts
        stop = len(entries) * (index + 1) // parts
        part = entries[start:stop]
        if len(part) > CHUNK_SIZE:
            raise ValueError(f"{name}: a UniFi part exceeds {CHUNK_SIZE} entries")
        filename = f"{name}-unifi-{index + 1:02d}.txt"
        content = ("\n".join(part) + "\n").encode("ascii")
        (output / filename).write_bytes(content)
        chunks.append({"file": filename, "entries": len(part),
                       "sha256": hashlib.sha256(content).hexdigest()})

    return {
        "entries": len(entries),
        "txt": txt.name,
        "csv": f"{name}.csv",
        "sha256_txt": hashlib.sha256(txt.read_bytes()).hexdigest(),
        "unifi_parts": chunks,
    }


def write_catalog(output: Path, manifest: dict) -> None:
    """Publish an always-current clickable index of every feed on day one."""
    repository = os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("GITHUB_REPOSITORY must be owner/repository")
    base = f"https://raw.githubusercontent.com/{repository}/refs/heads/feeds"
    lines = [
        "# AbuseIPDB UniFi mirror: feed directory",
        "",
        "Unofficial format-only mirror of [borestad/blocklist-abuseipdb]"
        "(https://github.com/borestad/blocklist-abuseipdb), with upstream data including"
        " [AbuseIPDB](https://www.abuseipdb.com/). Not affiliated with either project.",
        "",
        "All 10 IPv4 time windows are published together. Every TXT and CSV is headerless,",
        "comment-free and contains one IPv4 address/CIDR per line. UniFi TXT parts contain",
        "at most 100,000 entries, the mirror's configured chunk size. Verify your gateway's",
        "per-list and total capacity before importing; full mirror availability does not guarantee it fits.",
        "",
        "| Window | Entries | Full TXT | Full CSV | UniFi TXT parts |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for days in DAYS:
        name = f"abuseipdb-s100-{days}d"
        details = manifest["feeds"][name]
        txt = f"[TXT]({base}/{details['txt']})"
        csv_link = f"[CSV]({base}/{details['csv']})"
        parts = ", ".join(
            f"[part {index}]({base}/{item['file']})"
            for index, item in enumerate(details["unifi_parts"], 1)
        )
        lines.append(f"| {days}d | {details['entries']:,} | {txt} | {csv_link} | {parts} |")
    lines += [
        "",
        f"Generated: {manifest['generated_at']}. Check source timestamps in the manifest.",
        "UniFi refreshes parts independently; a gateway can temporarily hold mixed revisions.",
        "When new parts appear, subscribe to every part to retain complete coverage.",
        "",
        f"Source revision: [`{manifest['upstream_revision']}`]"
        f"(https://github.com/borestad/blocklist-abuseipdb/commit/{manifest['upstream_revision']})",
        "",
        "[UniFi setup, capacity checks, updates and redistribution notice]"
        f"(https://github.com/{repository}#unifi-setup) | [Machine-readable manifest](manifest.json)",
        "",
    ]
    (output / "README.md").write_text("\n".join(lines), encoding="utf-8")


def build_snapshot(output: Path, previous: dict, revision: str) -> None:
    now = utc_now()
    print(f"Upstream snapshot: {revision}", flush=True)
    manifest = {
        "schema_version": 1,
        "generated_at": timestamp(now),
        "upstream_revision": revision,
        "mirror": "Unofficial UniFi TXT/CSV mirror of borestad/blocklist-abuseipdb",
        "upstream": "borestad/blocklist-abuseipdb",
        "upstream_url": "https://github.com/borestad/blocklist-abuseipdb",
        "chunk_size": CHUNK_SIZE,
        "feeds": {},
    }
    for days in DAYS:
        name = f"abuseipdb-s100-{days}d"
        url = f"{SOURCE}/{revision}/{name}.ipv4"
        raw = download(url)
        entries = parse_feed(raw, name)
        updated = source_updated_at(raw, name, utc_now())
        if len(entries) < MIN_ENTRIES:
            raise ValueError(f"{name}: only {len(entries)} entries, expected at least {MIN_ENTRIES}")
        previous_parts = previous.get("feeds", {}).get(name, {}).get("unifi_parts", [])
        details = write_feed(output, name, entries, max(MIN_PARTS.get(days, 1), len(previous_parts)))
        details["upstream_updated_at"] = timestamp(updated)
        details["upstream_url"] = url
        details["sha256_source"] = hashlib.sha256(raw).hexdigest()
        manifest["feeds"][name] = details
        print(f"{name}: {len(entries):,} entries, {len(details['unifi_parts'])} UniFi part(s)", flush=True)

    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_catalog(output, manifest)


def synchronize(output: Path, previous_manifest: Path | None = None, *, skip_unchanged: bool = False) -> bool:
    """Stage a whole snapshot; restore the old directory if installation fails.

    Directory replacement has a short rename gap, so serve Git-published feeds
    rather than this directory when uninterrupted HTTP availability is required.
    """
    if output.is_symlink():
        raise ValueError("Output must not be a symlink")
    output = output.absolute()
    if output.resolve() == Path.cwd().resolve() or output.resolve() in Path.cwd().resolve().parents:
        raise ValueError("Output must not replace the working directory or an ancestor")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output_lock(output):
        backup = output.parent / f".{output.name}.previous"
        if backup.exists():
            raise ValueError(f"Recovery snapshot exists; restore or remove it before retrying: {backup}")
        previous = {}
        local_manifest = output / "manifest.json"
        if output.exists():
            if not output.is_dir():
                raise ValueError("Output must be a directory")
            if any(output.iterdir()):
                if not local_manifest.is_file():
                    raise ValueError("Refusing to replace nonempty output without a manifest")
                previous = load_previous_manifest(local_manifest)
                expected = {"README.md", "manifest.json"}
                for detail in previous["feeds"].values():
                    expected.update((detail["txt"], detail["csv"]))
                    expected.update(p["file"] for p in detail["unifi_parts"])
                if any(p.name not in expected or not p.is_file() or p.is_symlink() for p in output.iterdir()):
                    raise ValueError("Output contains unmanaged files; refusing replacement")
        has_local_snapshot = bool(previous)
        external = {}
        if previous_manifest is not None:
            external = load_previous_manifest(previous_manifest)
            for name, detail in external["feeds"].items():
                if len(detail["unifi_parts"]) > len(previous.get("feeds", {}).get(name, {}).get("unifi_parts", [])):
                    previous.setdefault("feeds", {})[name] = detail
        revision = latest_upstream_revision()
        baseline = external or previous
        if (skip_unchanged and baseline.get("upstream_revision") == revision
                and baseline.get("schema_version") == 1
                and not (external and has_local_snapshot)):
            # Do not refresh timestamps on an unchanged source: a stalled
            # upstream must become an error, not look freshly published.
            validate_freshness(baseline, utc_now())
            if not has_local_snapshot or local_snapshot_intact(output, baseline):
                print(f"Upstream snapshot unchanged: {revision}; skipping feed downloads and publication", flush=True)
                return False
        with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as temporary:
            staging = Path(temporary) / "snapshot"
            staging.mkdir()
            build_snapshot(staging, previous, revision)
            had_output = output.exists()
            if had_output:
                output.rename(backup)
            try:
                staging.rename(output)
            except OSError:
                if had_output:
                    backup.rename(output)
                raise
            if had_output:
                shutil.rmtree(backup)
        return True


def local_snapshot_intact(output: Path, manifest: dict) -> bool:
    """Only skip a local rebuild when all existing feed bytes remain intact."""
    try:
        for detail in manifest["feeds"].values():
            files = [(detail["txt"], detail["sha256_txt"]), (detail["csv"], detail["sha256_txt"])]
            files.extend((part["file"], part["sha256"]) for part in detail["unifi_parts"])
            for filename, expected in files:
                if hashlib.sha256((output / filename).read_bytes()).hexdigest() != expected:
                    return False
    except (OSError, KeyError):
        return False
    return (output / "README.md").is_file()


def validate_freshness(data: dict, now: datetime) -> None:
    try:
        if data["upstream"] != "borestad/blocklist-abuseipdb":
            raise ValueError("Published manifest has an unexpected upstream identity")
        dates = [("Published manifest", data["generated_at"])] + [
            (f"abuseipdb-s100-{d}d upstream data", data["feeds"][f"abuseipdb-s100-{d}d"]["upstream_updated_at"])
            for d in DAYS
        ]
        for label, value in dates:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            age = now - date
            if age > MAX_PUBLICATION_AGE:
                raise ValueError(
                    f"{label} is overdue: timestamp {value}, {age.total_seconds() / 3600:.1f} hours old; "
                    f"maximum {MAX_PUBLICATION_AGE.total_seconds() / 3600:.1f} hours"
                )
            if age < -timedelta(minutes=10):
                raise ValueError(f"{label} is future-dated: {value}")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Published manifest has missing or invalid freshness metadata") from exc


def check_health(url: str) -> None:
    """Read-only check detects stale publication or stalled upstream."""
    validate_freshness(json.loads(download(url)), utc_now())
    print("Published mirror and all ten upstream windows are fresh", flush=True)



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("feeds"), help="Publication directory")
    parser.add_argument("--previous-manifest", type=Path, help="Previous published manifest, for stable part URLs")
    parser.add_argument("--skip-unchanged", action="store_true", help="Skip fresh, already-published upstream revisions")
    parser.add_argument("--check-url", help="Check a published manifest for freshness without publishing")
    args = parser.parse_args()
    try:
        if args.check_url:
            check_health(args.check_url)
        else:
            changed = synchronize(args.output, args.previous_manifest, skip_unchanged=args.skip_unchanged)
            if result_path := os.environ.get("GITHUB_OUTPUT"):
                with Path(result_path).open("a", encoding="utf-8") as result:
                    result.write(f"changed={str(changed).lower()}\n")
    except (OSError, ValueError, RuntimeError, HTTPError) as exc:
        print(f"SYNC FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
