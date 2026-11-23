# Support

## Usage questions and setup help

Start with [UniFi setup](README.md#unifi-setup), [Available feeds](README.md#available-feeds), [Updates](README.md#updates) and [Operating the mirror](docs/OPERATIONS.md). If those do not answer the question, open a [Question / Support issue](https://github.com/developingchet/blocklist-abuseipdb-unifi/issues/new?template=question.yml) with the feed URL, time window, gateway model, UniFi OS/Network versions and what has already been tried.

Logs and manifests can contain tokens and private network details. Remove them before pasting anything into an issue, a log or a debug file.

## Bugs and feature requests

Use the [Bug report](https://github.com/developingchet/blocklist-abuseipdb-unifi/issues/new?template=bug_report.yml) form for wrong behaviour and the [Feature request](https://github.com/developingchet/blocklist-abuseipdb-unifi/issues/new?template=feature_request.yml) form for proposed changes. Issue forms are the public intake; this repository does not use GitHub Discussions.

## Security reports

Do not report a vulnerability in a public issue. Use [private vulnerability reporting](https://github.com/developingchet/blocklist-abuseipdb-unifi/security/advisories/new) and follow [the security policy](.github/SECURITY.md) for scope, reproduction limits and response targets.

## Upstream data and other products

For errors in the upstream blocklist, contact [borestad](https://github.com/borestad/blocklist-abuseipdb) or [AbuseIPDB](https://www.abuseipdb.com/). For gateway issues, contact [Ubiquiti](https://www.ui.com/security). Problems in this mirror's own conversion, validation or publication belong here.

## Responses

Issues are reviewed as time allows. Include the manifest revision, the affected feed URL and the workflow run so a question can be answered without a second round of requests. A passing test suite does not prove that a gateway imported the feeds; that needs a check against the gateway itself.

## Data rights

The MIT license covers the converter and documentation, not the mirrored feed content. Upstream redistribution terms have not been established in this repository. See [Credits and permission](README.md#credits-and-permission) before publishing another public mirror.
