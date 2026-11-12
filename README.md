# blocklist-abuseipdb-unifi

[![Sync](https://github.com/developingchet/blocklist-abuseipdb-unifi/actions/workflows/sync.yml/badge.svg?branch=main)](https://github.com/developingchet/blocklist-abuseipdb-unifi/actions/workflows/sync.yml)
[![Socket](https://github.com/developingchet/blocklist-abuseipdb-unifi/actions/workflows/socket.yml/badge.svg?branch=main)](https://github.com/developingchet/blocklist-abuseipdb-unifi/actions/workflows/socket.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/developingchet/blocklist-abuseipdb-unifi/badge)](https://scorecard.dev/viewer/?uri=github.com/developingchet/blocklist-abuseipdb-unifi)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](CONTRIBUTING.md)
[![Code license: MIT](https://img.shields.io/badge/code_license-MIT-yellow.svg)](LICENSE)

An unofficial [borestad/blocklist-abuseipdb](https://github.com/borestad/blocklist-abuseipdb) mirror for UniFi. It is scheduled to check for updates **every hour** and publishes clean TXT/CSV feeds: one IPv4 address or CIDR per line, with **no headers, comments, or ASN annotations**.

**[Browse feeds and copy download URLs →](https://github.com/developingchet/blocklist-abuseipdb-unifi/tree/feeds)**

## UniFi setup

Requires a supported gateway running **UniFi OS 6.0.10+ and Network 11** with External Network Lists. See [Ubiquiti's release notes](https://community.ui.com/releases/UniFi-Network-Application-11-0-97/15662d06-8122-44e2-a1ba-af5d71b8a045).

1. Open the [feed directory](https://github.com/developingchet/blocklist-abuseipdb-unifi/tree/feeds) and choose **one time window**.
2. In **Settings → Networks → Network Lists → Create New**, choose **Type: IP**, **Source: Dynamic**. Create one list for **each UniFi part URL** in that window. Set refresh to **24 hours**.
3. Add those lists to your [firewall policies](https://help.ui.com/hc/en-us/articles/115003173168-Zone-Based-Firewalls-in-UniFi), then check imported counts and refresh status. Importing alone does **not** block traffic.

**Capacity:** This mirror splits feeds into parts of up to **100,000 entries**. That is the mirror's chunk size, not a verified gateway limit. Check your gateway's per-list and total capacity before importing; publishing a complete window does not guarantee it will fit. Ubiquiti describes external Network Lists in its [Network 11 overview](https://blog.ui.com/article/introducing-unifi-network-11), but that page does not specify numeric capacity limits. Choose one window; [borestad recommends 30 days or less](https://github.com/borestad/blocklist-abuseipdb#readme).

## Available feeds

All **10 windows** are published together on the first successful run:

`1d` · `3d` · `7d` · `14d` · `30d` · `60d` · `90d` · `120d` · `180d` · `365d`

| File | Contents |
| --- | --- |
| `abuseipdb-s100-<days>d.txt` | Complete window |
| `abuseipdb-s100-<days>d.csv` | Same entries, one column, no header |
| `abuseipdb-s100-<days>d-unifi-01.txt`, `-02.txt`, … | Parts of up to 100,000 entries each |

The feed directory lists every URL and count. Existing part URLs are preserved when counts shrink; **subscribe to any new parts when a window grows**. `manifest.json` records timestamps, hashes, and the upstream commit. Upstream's statistics-only `all` dataset is excluded.

## Host your own mirror

1. Confirm redistribution permission below, then put these files in a **public GitHub repository** with `main` as its default branch. Forks generate URLs for their own repository.
2. Enable Actions and allow the publishing job to [write repository contents](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions). Allow workflow force updates to the generated `feeds` branch.
3. Run **Actions → Sync AbuseIPDB feeds → Run workflow**. After it succeeds, open the `feeds` branch for download URLs.

No personal API key, server, containers, or third-party Python packages are needed.

## Updates

- **Scheduled at :23 each hour:** check upstream; download and publish only a new revision. Unchanged runs preserve timestamps.
- **After each sync attempt:** check public feed freshness. Data older than **3 hours** fails the check.
- Failed conversions preserve the last published feeds. Enable Actions failure notifications and inspect failed runs.

Times are UTC. [GitHub schedules can be delayed, dropped, or disabled](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule). UniFi refreshes separately; hourly mirroring does not change its polling interval. Parts may temporarily contain different revisions during a gateway refresh.

[Local commands, recovery, monitoring, and deployment checks](docs/OPERATIONS.md)

[Report a bug](https://github.com/developingchet/blocklist-abuseipdb-unifi/issues/new/choose) · [Contribute](CONTRIBUTING.md) · [Security disclosure](.github/SECURITY.md) · [Code of conduct](CODE_OF_CONDUCT.md)

## Credits and permission

Data comes from [borestad](https://github.com/borestad/blocklist-abuseipdb), [AbuseIPDB](https://www.abuseipdb.com/), [IPinfo](https://ipinfo.io/), and upstream's other sources. This project only converts formats; it adds no independent scoring or addresses and is not affiliated with those projects or Ubiquiti.

**Obtain authorization before publishing a public mirror.** Borestad does not declare a license; its permission to publish does not automatically cover redistribution. See [AbuseIPDB's terms](https://www.abuseipdb.com/legal) and [API documentation](https://docs.abuseipdb.com/).

The converter and project documentation are [MIT licensed](LICENSE). That license does not cover mirrored third-party data or grant redistribution rights to it.
