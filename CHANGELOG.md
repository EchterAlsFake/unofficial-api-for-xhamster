# 3.0.0

Release 3.0.0

Update pagination handling, validation, and documentation.

Changes since 2.6.5:

```text
README.md                      |  18 ++++
 pyproject.toml                 |   4 +-
 xhamster_api/api.py            | 188 ++++++++++++++++++++++++++++++-----------
 xhamster_api/modules/consts.py |   2 +
 4 files changed, 159 insertions(+), 53 deletions(-)
```

# Changelog

## 2.6.5 — 2026-10-27

- Restore shorts and moments extraction from current page data and DOM layouts.
- Keep profile shorts on the correct listing route and preserve regional URL hosts.
- Read listing metadata from hydrated page data so later cards retain thumbnails and durations.
- Avoid incompatible quality filters for VR search and recognize Full HD and UHD videos correctly.
- Handle missing short metadata safely and add compatible user, video and shorts aliases.
- Route shorts and moments through the CLI.
- Use the published `eaf-base-api>=4.2.5` dependency.

