---
version: alpha
colors:
  canvas: "#f3f6fa"
  surface: "#ffffff"
  ink: "#152c42"
  muted: "#536779"
  primary: "#075985"
  accent: "#075985"
  success: "#1d5a43"
  warning: "#8a4b10"
  danger: "#9e2236"
typography:
  display:
    fontFamily: "Charter, Georgia, serif"
  body:
    fontFamily: "system-ui, sans-serif"
  data:
    fontFamily: "ui-monospace, monospace"
spacing:
  unit: "4px"
rounded:
  panel: "8px"
---
# Daily SEO Reviewer

## Overview

A product report for maintainers deciding which technical SEO conditions need investigation. The reference is a laboratory inspection sheet: calm blue ink, explicit provenance, readable evidence. The signature is a finding ledger with a status-colored left edge and source references, not ornamental charts or a promotional hero. Avoid marketing dashboards, glowing dark panels, and newspaper columns. English UI, Asia/Yerevan dates, light theme only.

## Colors

Runtime source of truth: `seo_reviewer/rendering/styles.css` CSS variables. The frontmatter records their role/value mapping. Status always has a text label. White surfaces on a cool gray canvas; blue links; dark amber warnings; red critical states; green healthy states. Borders and focus rings use named CSS tokens as well.

## Typography

Display family only for page titles; system sans for prose; monospace for run IDs, URLs and digests. Body 16px/1.6, section headings 22px, report title 36px (28px on phones), data 13px. External fonts are unnecessary. Long values wrap; factual values are never hidden behind hover.

## Layout

A centered 1080px reading surface with a compact masthead and latest/archive navigation. Report sections follow the implementation brief: title/date, status/freshness, coverage, summary, priorities/evidence/actions, resolved and verification items, history, archive/data links, limitations. Spacing follows a 4px base. At 680px and below columns stack. Document owns vertical scroll; semantic tables may scroll horizontally inside labeled regions. Tables keep a 760px minimum width and scroll horizontally in their labeled region on phones. History is limited to 20 rows per report; archive lists use static pages of 30 reviews.

## Elevation & Depth

Flat panels with borders. No decorative shadows or motion. No JavaScript, web fonts, or runtime requests. Browser-native link and disclosure behavior.

## Shapes

8px panel corners, generous section separation, strong focus outlines. A finding's left border conveys category only alongside its severity text.

## Components

Shared `base.html` owns landmarks/navigation and stylesheet; `report.html` is reused for latest and every archived review; `archive.html` shares that shell. `render.py` owns URL safety, timestamps, freshness, pagination and factual data projections. All values pass through Jinja autoescaping; AI prose is plain text. Empty, healthy, baseline-only, partial, failed, unverified and AI fallback states have explicit text.

## Do's and Don'ts

Show authoritative facts before advisory AI prose. Keep code-derived counts and statuses outside AI sentences. Link to JSON evidence and full repository snapshots; do not publish crawled HTML as executable pages. Keep latest and archive layout identical. Do not add form controls, a client framework, or deceptive interactive rows.
