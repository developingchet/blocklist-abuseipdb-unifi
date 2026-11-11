# Contributing

Search [existing issues](https://github.com/developingchet/blocklist-abuseipdb-unifi/issues)
before reporting a bug or suggesting a feature. Use the issue forms and include
the feed URL, affected window, commit or workflow run, and reproduction steps.
For import problems, include your gateway model and UniFi OS/Network versions.
Remove credentials and private network details from logs.

Report vulnerabilities privately as described in the [security policy](.github/SECURITY.md).
Participants must follow the [code of conduct](CODE_OF_CONDUCT.md).

## Development

Use Python 3.10+ and Git/Bash for the publication integration test. No third-party
runtime packages, live gateway, or API key are required for the test suite.

```sh
python3 -m unittest discover -s tests -v
```

Use `python` on Windows. Keep changes focused, add behavior tests for fixes,
and explain what changed and how it was verified in the pull request.

- Preserve upstream entries and order; do not add scoring or filtering.
- Keep feeds headerless and existing part URLs stable.
- Preserve the last usable snapshot on validation or download failures.
- Keep credentials out of code, logs, issues, and fixtures.
- Pin Actions to full commit SHAs and keep automation dependencies hash-locked.
- Update the affected documentation when behavior changes.

Discuss large changes or new runtime dependencies before implementing them.
See [operations](docs/OPERATIONS.md) for local conversion and recovery.

Project code and documentation use the MIT license. Mirrored third-party data
is excluded; contributions must not imply additional redistribution rights.
