# Annotations reference

`annotate.js` renders inside its own shadow root (`position:fixed`, `pointer-events:none`, max z-index),
so it never changes how the page behaves. It is injected once per page load (TIRAI re-sends it only
when the page lost it); each step starts clean.

| Shape | Scenario form | Notes |
|---|---|---|
| `box` | `box: { target: "#email", label: "Email" }` | rounded rectangle |
| `circle` | `circle: { target: ".error" }` | ellipse around target |
| `underline` | `underline: { target: "#total" }` | line under the target |
| `strike` | `strike: { target: ".old-price" }` | line through the target |
| `arrow` | `arrow: { target: ".error", from: right, label: "Error", length: 110, curve: 0.3 }` | `from`: left, right, top, bottom, top-left, top-right, bottom-left, bottom-right; `curve` (-1…1) bends the shaft to one side; the tail is shortened (or comes from the opposite side) so it stays in the frame |
| `callout` | `callout: { target: "#save", label: "Saves without validation", from: auto }` | speech bubble with a tail to the target; `from`: auto (above, else below), top, bottom, left, right; flips side when there is no room |
| `magnify` | `magnify: { target: "#total", factor: 2.5, label: "Expected 5,800" }` | loupe beside the target with an enlarged copy of it (canvas pixels included); `factor` 1.2–6 (default 2), `from`: auto, right, left, bottom, top. The copy is a snapshot taken when drawn; masked/blurred content stays covered in it. Large targets (a whole page section) are refused: point it at a cell, value or small group |
| `text` | `text: { target: "#total", label: "Sum is wrong" }` | floating label |
| `badge` | `badge: { target: "#save", n: 1, pos: top-right }` | numbered marker; omit `n` (or `n: auto`) to number badges 1, 2, 3… within the step; `pos`: top-left (default), top-right, bottom-left, bottom-right, left, right |
| `highlight` | `highlight: { target: ".row-2" }` | translucent marker fill (yellow) |
| `blur` | `blur: { target: "#password" }` | masks sensitive content; always instant |

Common options: `color` (default `#2563eb` blue — semantic: `#2563eb` neutral/action, `#16a34a` PASS/verified,
`#d97706` warning/edge, `#dc2626` error/FAIL only), `style` (`info`, `success`, `warning`, `error`: those same
colours by name; ignored when `color` is also given), `width` (3), `padding` (6), `label`, `labelPos` (right, left, top, bottom),
`anim`, `duration`, `id`. Labels that would overlap an earlier label in the same step move down (or up)
until they are clear.

## Targets

| Form | Example |
|---|---|
| CSS selector | `"#email"` (first visible match; open shadow roots are searched when the light DOM has none) |
| Visible text | `{ text: "Sign in", within: "form", exact: true, nth: 0 }` (also inside open shadow roots) |
| Viewport rect | `{ x: 100, y: 200, w: 300, h: 40 }` |
| Relative to element | `{ selector: "canvas", rel: { x: 0, y: 26, w: 120, h: 26 } }` |
| Canvas data grid (DBX) | `{ grid: { column: status, toColumn: failed_logins, row: 1 } }` |

Grid targets take x/width from DOM header cells (`.data-grid-header-cell`) and y from the canvas body
(`canvas.canvas-grid-surface`, 26 px rows); override with `header`, `body`, `rowHeight`.

A missing target throws, so the step fails instead of silently recording a wrong frame. Shapes follow
their target on scroll, resize and re-layout. When a framework re-renders the element, the target is
looked up again; while it cannot be found (removed or hidden) the shape is hidden rather than left at
the old position. `spotlight` holes follow their targets the same way.

## Animation

| `anim` | Behaviour |
|---|---|
| `draw` (default) | strokes draw on once (~0.4 s), arrow grows tail to tip, highlight wipes left to right, label fades in last |
| `fade` | fade in ~0.2 s |
| `none` | appears instantly (strict evidence) |

No looping or pulsing: BrowserSkill records at roughly 12 fps, so repeated motion looks jerky.
Removing annotations fades them out in 0.16 s. Set a default for a page with `__ann.config({ anim: "none" })`.

## Action callouts and expectation HUD

When recording with `settings.action_annotate: true` and `settings.show_expects: true` (paired with
`camera: action` and `pace: human`), TIRAI drives two more overlays automatically:

- **`__ann.actionCallout(target, label, { color, spotlight })`** / **`__ann.clearAction()`**: highlights each
  interactive control (`click`, `fill`, `clear`, `select`, `press`, `download`, `upload`, `hover`) with a rounded
  box and a floating pill (labelled from the element's accessible name/text, or from `label:` on the action)
  while the camera zooms onto it, then clears before the next action. With `spotlight: true` on the step
  or in `settings:`, the rest of the page is dimmed around the control.
- **`__ann.expectHud(rows, { pos, passColor, failColor })`** / **`__ann.clearExpectHud()`**: a dark
  **EXPECTATIONS** card in a viewport corner (`top-right` by default) that ticks off every `expect:` item
  (`✓` green / `✗` red, plus the actual value on failure) and boxes each checked DOM target. A box that
  cannot be drawn (the element is gone) is reported as a run warning; the expectation result itself stands.

## Privacy masking

`privacy: { mask: [email, phone, card, token], patterns: [...], selectors: [...], keep: [...] }` installs
`__ann.mask()`: matching text and input values get an opaque cover that follows the text every frame, so
layout shifts never uncover it. It rescans on DOM and text edits and covers:

- the page and its open shadow roots;
- same-origin iframes (including `srcdoc`).

Cross-origin iframes and closed shadow roots cannot be read from the page; mask them with a `blur`
target or `privacy.selectors` on the iframe element, and keep `privacy.ocr` on as the safety net.
If masking cannot start when a page loads, the page is covered entirely and the step fails.
