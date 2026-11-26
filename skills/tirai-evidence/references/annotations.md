# Annotations reference

`annotate.js` renders inside a shadow root (`position:fixed`, `pointer-events:none`, max z-index),
so it never changes how the page behaves. It is re-injected on every step; each step starts clean.

| Shape | Scenario form | Notes |
|---|---|---|
| `box` | `box: { target: "#email", label: "Email" }` | rounded rectangle |
| `circle` | `circle: { target: ".error" }` | ellipse around target |
| `arrow` | `arrow: { target: ".error", from: right, label: "Error", length: 110 }` | `from`: left, right, top, bottom, top-left, top-right, bottom-left, bottom-right |
| `text` | `text: { target: "#total", label: "Sum is wrong" }` | floating label |
| `badge` | `badge: { target: "#save", n: 1 }` | numbered marker |
| `highlight` | `highlight: { target: ".row-2" }` | translucent marker fill (yellow) |
| `blur` | `blur: { target: "#password" }` | masks sensitive content; always instant |

Common options: `color` (default `#2563eb` blue — semantic: `#2563eb` neutral/action, `#16a34a` PASS/verified, `#d97706` warning/edge, `#dc2626` error/FAIL only), `width` (3), `padding` (6), `label`, `labelPos`
(right, left, top, bottom), `anim`, `duration`, `id`.

## Targets

| Form | Example |
|---|---|
| CSS selector | `"#email"` (first visible match) |
| Visible text | `{ text: "Sign in", within: "form", exact: true, nth: 0 }` |
| Viewport rect | `{ x: 100, y: 200, w: 300, h: 40 }` |
| Relative to element | `{ selector: "canvas", rel: { x: 0, y: 26, w: 120, h: 26 } }` |
| Canvas data grid (DBX) | `{ grid: { column: status, toColumn: failed_logins, row: 1 } }` |

Grid targets take x/width from DOM header cells (`.data-grid-header-cell`) and y from the canvas body
(`canvas.canvas-grid-surface`, 26 px rows); override with `header`, `body`, `rowHeight`.

A missing target throws, so the step fails instead of silently recording a wrong frame.

## Animation

| `anim` | Behaviour |
|---|---|
| `draw` (default) | strokes draw on once (~0.4 s), arrow grows tail to tip, highlight wipes left to right, label fades in last |
| `fade` | fade in ~0.2 s |
| `none` | appears instantly (strict evidence) |

No looping or pulsing: BrowserSkill records at roughly 12 fps, so repeated motion looks jerky.
Removing annotations fades them out in 0.16 s. Set a default for a page with `__ann.config({ anim: "none" })`.

## Step-by-step Action Callouts & Per-Expect HUD

When recording with `settings.action_annotate: true` and `settings.show_expects: true` (paired with `camera: action` and `pace: human`), TIRAI drives two additional shadow-DOM overlays automatically:

- **`__ann.actionCallout(target, label, { color, spotlight })`** / **`__ann.clearAction()`**: highlights each interactive control (`click`, `fill`, `clear`, `select`, `press`, `download`) with a rounded box + floating pill (auto-labeled from the element's accessible name/text, or from `label:` on the action) while the camera zooms onto it, then clears before the next action.
- **`__ann.expectHud(rows, { pos, passColor, failColor })`** / **`__ann.clearExpectHud()`**: renders a dark frosted **EXPECTATIONS** checklist card in the viewport corner (`top-right` by default) that ticks off every `expect:` item (`✓` green / `✗` red + `actual:` detail on failure) while boxing each checked DOM target, and remains visible alongside the step's final `annotate:` callouts.
