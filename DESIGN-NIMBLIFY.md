# Armstrong unified interface — 2026-11-24

The approved static reference is now connected to the existing shared-data renderer.
`nimblify-system.css`, loaded last, is the authoritative visual baseline for overview,
milestones, reports, samples and drawers. The older stylesheets remain as structural
compatibility layers; there is no additional theme selector.

## Changes

- Shared 240px sidebar, 64px topbar search and real signed-in account details.
- Overview: four equal columns, consistent illustrated product-line icons, semantic
  status/percentage/progress colors, owners, affected models, recorded update dates
  and existing priority tags. Missing dates are labeled rather than inferred.
- Existing business-line, priority and sort controls remain. Status tabs reuse the
  existing status filter. Added an optional update-date range for project cards;
  it does not filter confirmations or reports and excludes unknown update dates.
- Global KPI controls sit below the cards, explicitly independent of local search.
- Milestone, sample, report and drawer components share typography, surfaces,
  rounded controls, status colors and table spacing. Mobile tables retain labeled
  row cards; mobile actions use a collapsible menu.
- New strings are added to the existing English dictionary. Navigation remains
  labeled for assistive technologies when the sidebar is collapsed.

## Data and permission boundaries

No backend endpoint, storage key, production record, role rule or save payload was
changed. New project, project/model editors, confirmations, samples, exports and
report generation continue to use their existing handlers.

## Verification

- Parsed all executable inline scripts in `app.html` and `index.html` with Node.
- Browser checks at 1280, 768 and 375px: card columns and equal heights; no document
  horizontal overflow. Mobile milestones/reports retain fields in row cards.
- Status/search/date filtering verified; global KPI counts remain unchanged.
- Isolated local API: milestone edit/save and refresh persistence, project creation.
  The native delete-confirmation dialog blocked browser automation; completion of
  that deletion was not verified. The local test server was restarted to discard
  all test changes. No production data was written during these checks.
- English overview, milestone table, report and sample editor checked for default
  Chinese UI strings. User-authored text is preserved in its original language.
- Viewer account: no project mutation controls, editable drawer fields or save action.

This is a visual integration. It does not add email delivery, automated scheduling
or backend account administration.

## Alignment review

Column alignment is now assigned to both headers and cells by the shared table
decorator. Text/people columns use a common left edge; dates, counts, progress,
statuses and actions use a common center axis. The rules cover Chinese and English
overview, milestone, report, sample and drawer tables. Mobile row cards reset
content to the left edge beneath their field labels.

Browser checks compared each visible column's computed alignment and horizontal
padding between its heading and all rows. All checked columns matched. Additional
checks covered equal card heights, report label/input edges and no page overflow
at 375px and 1280px. Narrow desktop milestone/confirmation tables scroll within
their own container so complete dates remain readable. Confirmation summary
headings and cards now share the same section inset.

## Dedicated confirmation center

The confirmation table and approver workload band now live in a separate
`confirmations` view, available from the sidebar/mobile navigation and
`?view=confirmations`. The overview retains project cards and global metrics.
Pending KPI controls and the topbar bell open the confirmation center; selecting
an approver filters their pending items. Clearing returns all unfinished items,
including records still in preparation.

The center follows the supplied reference: four equal white metric cards, a
rounded table panel and a rose-tinted horizontal approver band. Values come from
existing records. Avatars use initials, not invented staff portraits. Joint
confirmations count once in the total and once for each assigned approver.
The center is independent of the overview's business-line/priority filters.

Verified: four total unfinished rows vs. three pending rows in the isolated seed;
Armie selection returns two rows; overview no longer renders the confirmation
table; English default UI has no Chinese residue; 375px and 1280px have no page
overflow; four metric cards have identical height at desktop width. No backend
endpoint, record or permission was changed.
