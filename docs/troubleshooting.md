# Troubleshooting

| Symptom | Fix |
|---|---|
| `bsk doctor` shows no extension | open the browser with the BrowserSkill extension enabled and connected |
| `bsk open failed ... session <id> unknown` | a stale session holds the scope: `bsk session list`, `bsk close --session <id>`, or use `--scope <new>` |
| `requires an unused strict observation` / `control context no longer belongs` | page changed under an action; add `wait_for` before the next action. The runner already syncs before every action |
| `annotate: target not found` | selector not visible at annotation time; check `step-<id>.png` from the dry-run |
| DBX cells not found by text | DBX draws results on a canvas: use `{ grid: { column, row } }` targets and `expect: db` |
| Subtitles missing Vietnamese glyphs | set `TIRAI_FONT` (and `TIRAI_FONT_BOLD`) to a Unicode .ttf |
| `missing environment variable X` | export it; `tirai validate` lists every variable the scenario needs |
| Video is choppy | BrowserSkill records ~12 fps; keep `anim: draw`/`fade` short or use `anim: none` |
