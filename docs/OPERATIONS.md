# Operating the mirror

[Back to README](../README.md)

## Local commands

Requires **Python 3.10+** and its standard library. Use `python` instead of `python3` on Windows.

```sh
python3 -m unittest discover -s tests -v
python3 sync.py --output feeds
```

Repeat with the same output directory to preserve established part URLs. The default command always rebuilds, including after converter changes. To skip a fresh, unchanged upstream revision:

```sh
python3 sync.py --output feeds --skip-unchanged
```

Local skips verify feed hashes; missing or altered feeds are rebuilt. Legacy manifests are rebuilt once to add freshness metadata. An unchanged but stale snapshot fails instead of being silently reused.

When generating in a new directory, preserve subscriptions using the previous published manifest:

```sh
python3 sync.py --output new-feeds --previous-manifest feeds/manifest.json
```

Do not delete the published manifest or reset the `feeds` branch. It tracks the number of part URLs to retain. Invalid state stops publication. If a window shrinks below its established number of nonempty parts, publication also fails rather than removing subscribed URLs.

## Publication safeguards

All ten inputs come from one pinned upstream commit. Validation rejects invalid entries, duplicates, count mismatches, missing metadata, sources older than three hours, and timestamps more than ten minutes in the future.

Actions reads the previous manifest before conversion and fetches the full mirror branch only when publication is needed. A lease protects against overwriting concurrent changes. The generated branch contains a single parentless commit, avoiding reachable history growth; old commits remain subject to GitHub's retention and collection policies. Pushes and pull requests run tests without publishing.

## Recovery

**GitHub Actions:** inspect the failed run, resolve its error, and rerun manually. The last successfully published feeds remain available.

**Local runs:** conversion stages beside the output directory, then renames directories with rollback on installation failure. Unrelated files in the output directory are rejected. Do not serve this directory directly when uninterrupted availability is required: installation has a brief rename gap and is not power-loss transactional.

Concurrent runs are blocked by `.feeds.lock`. After an interrupted run:

1. Confirm no converter is running.
2. If `.feeds.previous` exists, preserve it. Restore it to `feeds` when the output is absent. If both exist, inspect both before choosing the valid snapshot.
3. Remove any stale lock after recovery, then rerun.

Names above assume `--output feeds`; other output names use the same naming pattern.

## Monitoring and deployment checks

The hourly watchdog shares GitHub Actions' scheduler. For unattended operation, use an independent monitor that checks `manifest.json`: `generated_at` and every feed's `upstream_updated_at` should be no older than three hours. A stopped scheduler cannot report its own failure.

Publication commit messages include the actual UTC publication date and time.
To verify publication after a converter or workflow update, manually run
**Sync AbuseIPDB feeds** with **force_republish** enabled. It still validates
source freshness and all feeds; normal hourly runs continue skipping unchanged
revisions. Tests run on every pull request, including documentation changes, so
the required `test` check is always reported.
CodeQL, OpenSSF Scorecard, Dependabot, and Socket provide the same automation
checks used by the maintainer's other repositories. Socket requires the
`SOCKET_SECURITY_API_KEY` Actions secret. If it is absent, the workflow explicitly
reports a skipped scan. Tool dependencies live under `.github/requirements` and
are installed with hashes; they are not dependencies of the converter.

After the first hosted run, verify all generated URLs, imported UniFi counts, firewall policy references, and a subsequent automatic gateway refresh. Local tests cannot certify the gateway integration.

Hourly mirroring and a daily gateway refresh can still leave data roughly 25 hours behind upstream under normal timing, and longer when jobs are delayed or fail. UniFi downloads parts independently, so imports are not transactional across multiple URLs.
