# Architecture

```text
scenario.yaml ──► tirai validate
      │
      ▼
tirai run --dry-run ──► agent-browser | BrowserSkill (bsk) ──► real Chrome/Edge tabs (app, DBX web)
      │                    │  fill / click / press / evaluate
      │                    └─ annotate.js injected per step (boxes, arrows, labels, blur)
      ▼
tirai run --record ──► driver recording per contiguous tab block ──► seg-NN-<tab>.mp4 + timeline.json
      │                                               └──► expect: db (read-only driver)
      ▼
tirai compose ──► ffmpeg: cut steps, header bar, title card, concat, burn subtitles
      └──► final.mp4, subtitles.srt, report.md/.html/.xlsx, timeline.final.json, manifest.sha256

tirai suite ──► one `tirai record` process per scenario (parallel with agent-browser) ──► suite.md, junit.xml, index.html
tirai diff  ──► step-*.png of two runs ──► diff.html, diff.json
record --from-step ──► browser checkpoint (~/.tirai/checkpoints) + database restore hook ──► tail spliced into timeline.json
```

| Component | Owner | Why |
|---|---|---|
| Browser control, screenshots, MP4 (default) | [agent-browser](https://github.com/vercel-labs/agent-browser) | single binary, no extension, headless or headed, 30 fps |
| Browser control in your own browser | [Tencent BrowserSkill](https://github.com/Tencent/BrowserSkill) | real logged-in browser; also powers `tirai capture` |
| Database UI in the browser | [DBX web](https://github.com/t8y2/dbx) | many database engines, password-protected web UI |
| Scenario, checks, annotations, timeline, composition | TIRAI | the evidence-specific parts |

Design rules:

- **Dry-run before record**: recording only happens for a scenario that already passes, so videos have no failed attempts.
- **Per-tab segments**: both drivers record a single tab, so the runner starts a new segment on every tab switch and composition restores scenario order.
- **Checks are independent of pixels**: DOM checks read the page; DB checks query read-only, because DBX renders result cells on a canvas.
- **Fail closed**: a missing selector, annotation target or env var fails the step; so do an emulation setting the
  page does not report back and a database hook that exits non-zero.
- **No transactions around app writes**: the app commits on its own connections, so re-runs are made safe with
  `{{run_id}}`, `cleanup:`, database snapshot/restore hooks, and checkpoints that resume a recording without
  running the earlier steps again.

The previous spec-to-test platform (TypeScript workspaces) is preserved on branch `archive/tirai-v1`.
