# Security Policy

## Supported versions

The current `main` branch receives security fixes. Older commits and forks must
be updated by their operators. Generated feeds follow the current converter.

## Report a vulnerability privately

**Do not post vulnerabilities, credentials, or exploit details in public issues.**

Use [GitHub private vulnerability reporting](https://github.com/developingchet/blocklist-abuseipdb-unifi/security/advisories/new).
Include the affected commit or workflow run, reproduction steps, expected and
actual behavior, and impact. Remove credentials and private network details.

We aim to acknowledge reports within **3 business days**, provide a status update
within **7 business days**, and remediate confirmed issues within **30 days**.
Critical issues receive expedited attention. These are best-effort targets.
We coordinate disclosure and credit reporters unless anonymity is requested.

## What this project covers

Report vulnerabilities in the converter, validation, publication workflows,
repository automation, or integrity of the published feeds here. The mirror
uses HTTPS, validates one pinned upstream snapshot, and preserves published
feeds when conversion fails. These controls do not replace vulnerability review.

The mirror does not independently score addresses. For upstream data errors,
contact [borestad](https://github.com/borestad/blocklist-abuseipdb) or
[AbuseIPDB](https://www.abuseipdb.com/). Report gateway vulnerabilities to
[Ubiquiti](https://www.ui.com/security). A vulnerability in how this mirror
handles upstream data still belongs here.

## Dependency and automation checks

Actions are pinned to commit SHAs and checked by Dependabot. CodeQL analyzes
Python and Actions, and OpenSSF Scorecard checks repository practices. The
converter has no third-party runtime packages. Socket scans automation/tool
dependencies when `SOCKET_SECURITY_API_KEY` is configured; without it the job
reports that scanning was skipped. Do not treat a skipped scan as acceptance.

GitHub schedules can be delayed or disabled. Operators should monitor published
manifest timestamps independently; gateway refreshes are separate from mirror
updates. See [operations](../docs/OPERATIONS.md).
