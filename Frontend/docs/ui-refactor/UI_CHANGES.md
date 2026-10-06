# Test Execution page — visual refactor

Scope: the Test Execution page body only (`#view-test-execution`) and its file-viewer dialog.
The sidebar, breadcrumb, global header and every other page are unchanged.

Screenshots were captured headless at the app's real window size (1366×768) and at the
existing breakpoints (1200 px, 900 px), before and after the change:

- `before/` — original UI
- `after/` — refactored UI
- `baseline/` — copies of the three original source files (for `diff -u`)

| # | View | Before | After |
|---|---|---|---|
| 01 | Setup (all cases selected) | ![](before/01_setup.png) | ![](after/01_setup.png) |
| 02 | Setup with smoke-run overrides | ![](before/02_setup_overrides.png) | ![](after/02_setup_overrides.png) |
| 03 | Setup, three cases selected | ![](before/03_setup_selected.png) | ![](after/03_setup_selected.png) |
| 13 | Setup, right column: spec values, run options, warning + Start | ![](before/13_setup_right_column.png) | ![](after/13_setup_right_column.png) |
| 14 | Setup at 1200 px / 900 px | ![](before/14_setup_1200.png) ![](before/14_setup_900.png) | ![](after/14_setup_1200.png) ![](after/14_setup_900.png) |
| 04 | Live run (captured ~6 s after Start) | ![](before/04_live_running.png) | ![](after/04_live_running.png) |
| 05 | Live run, finished | ![](before/05_live_done.png) | ![](after/05_live_done.png) |
| 06 | Results | ![](before/06_results.png) | ![](after/06_results.png) |
| 07 | Results, case detail | ![](before/07_results_detail.png) | ![](after/07_results_detail.png) |
| 08 | Results, manual review box | ![](before/08_results_review.png) | ![](after/08_results_review.png) |
| 09 | File viewer (image) | ![](before/09_file_modal_image.png) | ![](after/09_file_modal_image.png) |
| 12 | Results with cause cards (older run) | ![](before/12_results_old_exec.png) | ![](after/12_results_old_exec.png) |
| 10 | History | ![](before/10_history.png) | ![](after/10_history.png) |
| 11 | History, Compare | ![](before/11_history_compare.png) | ![](after/11_history_compare.png) |

## Changes by rule

### Rule 1: cards
- Every card on the page uses one style: white background, 1px `--base-2` border,
  10px radius (the radius `.panel` and `.tcg-card` already used), 16px padding and the
  existing subtle shadow `0 1px 2px rgba(15, 23, 42, 0.04)`.
- This covers `.panel` and `.tcg-card` (scoped to `.view-tex`) and the Results cause cards.
- Card headers lose the grey strip and bottom border.

### Rule 2: section headers
- Card titles (DEVICE, SCRIPT SET, RUN OPTIONS, TEST CASES, QUEUE, LIVE LOG, LIVE METRICS,
  MANUAL CHECKPOINTS, CASES, CASE DETAIL, PAST EXECUTIONS, COMPARISON), sub-headings
  (HARNESS PACKAGES, SPEC VALUES…, MANUAL REVIEW) and case-detail section titles share one
  style: uppercase, 12px, weight 500, `--text-muted`, 12px below.

### Rule 3: statuses as dot + text
- Every `.status-pill` on the page is now an 8px coloured dot followed by the label in
  secondary text, with no fill, border or padding. This covers readiness, queue status,
  verdicts in tables, harness package status, run state in Results, and state in History.
- Verdict counts (`.tex-count-chip`) in Results and History, and cause-card labels, use
  the same dot.
- Dot colours are existing values:

| Status | Colour |
|---|---|
| Success | `#16a34a` |
| Danger | `#dc2626` |
| Warning / manual / running | `#f59e0b` |
| Ready | `--brand-blue` |
| Blocked | `#9333ea` |
| Spec mismatch | `#f97316` |
| Neutral | `--base-4` |

- Exception: the Live run state (`#tex-live-state`) keeps a light `--base-1` fill.
- The case-table filter label (`#tex-results-filter`) is not a status, so it stays a
  plain grey chip without a dot.

### Rule 4: case list grid
- Case rows use a grid: `24px 120px 1fr 80px 140px` (checkbox, ID, name, duration,
  readiness), 40px minimum height, `--base-1` hover.
- Readiness is right-aligned in a fixed column, and the ⚠ device-change icon sits beside it.
- The selected-row blue fill was removed; the checkbox shows selection.
- The category header is one row: checkbox, name, then "X/Y selected" on the right. It is
  sticky while the list scrolls. There is no collapse arrow, because the page had no
  collapse behaviour.
- At the existing ≤1280 px breakpoint the five fixed columns leave no room for the name,
  so each row stacks onto two lines (ID and duration; name and readiness).

### Rule 5: progressive disclosure
- Script set spec values (17 in the current sets) are behind `▸ 17 spec values`,
  collapsed by default. They open into a scrollable list (max 240px) of `KEY` / value
  rows. With 5 or fewer values the list shows directly.
- The override list scrolls at 240px instead of collapsing (see Deviations).

### Rule 6: warnings next to Start
- The warnings box and Start row moved into their own card at the bottom of the right
  column, sticky to the bottom of the viewport.
- Warnings have a neutral surface with a 3px amber (`#f59e0b`) left accent.
- All callouts on the page use the same neutral style with a semantic left accent: blue
  for info, amber for warning, green for success.

### Rule 7: consistency and widths
- Setup: cases on the left (flexible), configuration column fixed at 360px.
- Live run: Queue 280px, log flexible, right column 320px.

### Rule 8: spacing
- 24px between cards and panes, 16px between sections inside a card, 8px between related
  items, 4px inside compact elements.
- Page padding is 24px at the top and 32px at the sides and bottom (`#view-test-execution.view`).

### Rule 9: typography
- Primary titles (execution title, case-detail title): 14px, weight 600.
- Secondary labels and metadata: 12–13px, `--text-muted`.
- Monospace (case IDs, log, spec keys, metric values, commands, JSON): the existing mono
  stack at 12px.

### Rule 10: tab bar
- The tabs moved under the page title and became underline tabs: 24px apart, 2px
  underline, active tab in `--primary-color`, inactive in `--text-muted`.
- The pulsing Live run dot is unchanged.

## Changes by area

### Setup
- The layout is swapped: Test cases on the left, Device / Script set / Run options /
  Start on the right. The markup was reordered, so keyboard tab order matches the visual
  order.
- Device card:
  - ↻ icon buttons (with `aria-label`) replace the "Refresh" text on Device and Script set;
  - model name in 14px, then "Android 14 (API 34) · Emulator";
  - divider, then Battery / Temperature / Thermal status in three columns;
  - divider, then HARNESS PACKAGES with dot + version / "Not installed".
- Script set card: the same key/value rows, then a divider and the spec values disclosure.
- Run options:
  - the timeout has its label above a 160px input;
  - override rows are compact (name | value | ×);
  - "+ Add override" is a text link;
  - "Smoke-run preset" is a ghost button.

### Live run
- The header (title, meta, state, controls, 4px progress bar, status line) is sticky at
  the top of the tab.
- Queue rows are two lines: ID and time, then name and status.
- Log:
  - separate columns for time (mono, muted) and case ID (mono, light), then the message;
  - metric lines are prefixed with a `METRIC` label and checkpoint lines with `CHECKPOINT`;
  - failures and errors keep the danger colour;
  - 12px mono.
- Manual checkpoints and the Results review box use a neutral surface with an amber left
  accent instead of an amber fill.
- The right column scrolls on its own; at ≤1280 px it wraps below as before.

### Results
- Verdict counts are dot + text.
- The pass rate is a 28px figure, right-aligned, with "Pass rate" below it.
- Cause cards show the count in 28px with the label (dot) below, a white card and a
  `--base-3` border on hover. When active they get a `--primary-color` border.
- Table headers are 12px uppercase muted; rows are 40px (32px in compact tables) and
  vertically centred.
- Case-detail sections have Rule 2 headers and no grey summary fill.

### History
- Verdict counts and state are dot + text; row hover matches Results.
- Compare: changed rows keep the existing `#fffbeb` highlight, and the A/B time columns
  are right-aligned.

## Deviations from the brief, and why

| Brief | What was done | Reason |
|---|---|---|
| Tailwind classes, no custom px | Plain CSS on the 4/8/16/24/32 scale | The app has no Tailwind; it is plain HTML/CSS/JS in Electron. |
| Mono 13px | Mono 12px everywhere | You chose 12px for the log; IDs use the same size for one mono tier. |
| Medium (500) section titles | 600 for the two primary titles, 500 for uppercase headers | Inter is not installed. The fallback fonts (Liberation/DejaVu) have no 500 weight, so 500 renders as regular. |
| Collapse arrow on categories | Not added | The page had no collapse behaviour, and the brief says not to add it. |
| Override list behind a disclosure | Scrollable list (max 240px) | The list re-renders on every add or remove, so a collapsed disclosure would hide the row just added. |
| Warning-coloured log lines | Not applicable | The log has no warning level: it has info, op, op_fail, metric, manual, cmd, error, case and case_bad. |
| 🔋 🌡 glyphs in the device card | Text labels in a three-column grid | No icon library, and no colour-emoji font on this machine. The refresh control uses the text glyph ↻ with an `aria-label`. |
| Delta column in Compare | Existing A/B time columns right-aligned | There is no delta column, and adding one would add data. |
| Snapshot / Storybook / e2e updates | Headless before/after screenshots plus a functional trace | The frontend has no test tooling. See `NO_FUNCTIONAL_CHANGES.md`. |

## Known visual trade-offs
- At 1366 px the fixed grid columns leave about 190px for case names, so long names are
  truncated with an ellipsis. The full objective is still in the hover tooltip.
- The sticky Start card overlaps the lower part of the right column until you scroll.
  That keeps Start and the warnings visible at all times.

## Follow-up: layout fixes and short device names
Screenshots are in `followup/` (after) and `followup/before/`, taken at 1366x768.
This follow-up supersedes both trade-offs above.

| Area | Problem | Fix |
| --- | --- | --- |
| Live run | The right column was a small scroll box, so the live screen was cropped and the metrics card was squashed. | The right column no longer scrolls on its own. The Device card with the live screen comes first, and the screenshot is scaled to the viewport height so the whole phone screen is visible. |
| Live run | The fixed 280 / 320 px side columns left the log about 370px wide. The sticky header covered the columns while scrolling. | Columns are 260 / flexible / 280 px with 16px gaps, and the header is no longer sticky. The queue and log fill the viewport height. |
| Setup | The sticky Start card covered Run options, and space was left empty under the case list. | Start is a normal card at the bottom of the right column. The case list is sticky and fills the viewport height. Case-row columns are 104 / 64 / 124 px, which leaves more room for names. |
| Results | Cause cards wrapped four-and-two, leaving empty slots. Pass rate and the category chip sat on rows of their own. The case table scrolled sideways. | Cause cards share each row and fit one row at 1366px. Pass rate sits beside the title. The verdict chips, category chips and actions share one bar. The table is wider (3 : 2), and the Reason column is hidden when the table is under 720px, because the same reason appears at the top of the case detail. |
| Page | 24px gaps everywhere. | 16px page, column and grid gaps; the view has 16px / 24px padding. |
| Device name | `emulator-5554 · Google sdk_gphone64_x86_64 · Emulator · Android 14` | `Emulator 5554 · Android 14`. Physical phones show `Manufacturer Model`, without a repeated manufacturer. The serial is still shown under the name in the Device card. |
