# AGENTS.md

blocklist-abuseipdb-unifi converts the borestad blocklist into headerless TXT/CSV
feeds and UniFi-sized parts, then publishes them on the `feeds` branch.
README.md is the user guide; this file is for working on the converter and its
workflows.

## Layout

- `sync.py`: the converter, freshness watchdog and CLI. Standard library only.
- `tests/test_sync.py`: conversion, validation, publication safeguards and the
  watchdog, with network calls mocked.
- `tests/test_publication.py`: runs the publish shell from
  `.github/workflows/sync.yml` against a local bare Git repository.
- `.github/workflows/sync.yml`: hourly cron at :23 UTC and manual dispatch.
  Scheduled runs publish only when the upstream revision changes; a manual
  dispatch with `force_republish` rebuilds an unchanged revision.
- `.github/workflows/test.yml`: runs the suite on pushes to `main` and on every
  pull request, documentation changes included.
- `docs/OPERATIONS.md`: local conversion commands, recovery and deployment checks.

## Commands

```sh
python3 -m unittest discover -s tests -v
```

Use `python` on Windows. Run it from the repository root; `tests/test_sync.py`
imports `sync` from that directory. CI runs the same command on ubuntu-24.04.
The suite needs no API key, gateway, network access or third-party packages, but
`tests/test_publication.py` needs Git and Bash. A local conversion run is in
`docs/OPERATIONS.md`; it downloads from the upstream source and is not part of
offline test runs.

## Rules

- Preserve upstream entries and their order. Feeds stay headerless, without
  comments or ASN annotations, and existing part URLs stay stable.
- Preserve the last usable snapshot on validation or download failure. An
  unchanged but stale snapshot must fail, not be reused silently.
- Keep Actions pinned to full commit SHAs and automation tool dependencies
  hash-locked under `.github/requirements/`.
- Fixtures and examples use documentation IP ranges. Never use real abuse
  submissions, production firewall changes or live upstream feeds as tests.
- Keep credentials and private network details out of code, logs, issues and
  fixtures.
- The MIT license covers the converter and documentation, not the mirrored
  upstream data. Do not claim redistribution rights that the repository does not
  have; see README.md under "Credits and permission".
- Keep `CLAUDE.md`, `CLAUDE.local.md` and `.claude/` out of the repository. The
  committed `.gitignore` ignores these local agent instruction files, so a
  fresh clone keeps them untracked.
- This is a continuous data-feed repository without versioned releases. Do not
  add a changelog or release tag requirement for documentation changes.
- Commits follow Conventional Commits. Write docs, comments and commit messages
  for a reader who only sees the repository.
