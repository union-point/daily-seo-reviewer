# Report behavior

Source: README.md collection/detection/review contracts and the user's HTML reports and daily delivery milestone.

- Shared ownership: `base.html` navigation, `report.html` report states, `archive.html` archive pagination, `styles.css` tokens and scrollbar baseline, `render.py` factual projections.
- Latest and archived reviews use the same template. Latest means the newest collection timestamp among saved reviews, not the most recently regenerated narrative.
- A static report shows collection time, publication time, and freshness at publication. It makes no live freshness claim after deployment.
- No forms, mutations, loading states, dialogs, selection, or runtime network requests. Links and disclosures use native semantics with visible focus. Empty archive explains that collection must run first.
- English, Gregorian dates with explicit Asia/Yerevan zone. Mobile reflow preserves actions/evidence; tables scroll within their own labeled region.
- Accessibility baseline: semantic headings/landmarks, keyboard links/disclosures, visible focus, text status, and WCAG AA contrast. Native controls accept platform-owned behavior.
- Daily Issue summary uses code-derived facts and actions. One run-ID marker prevents duplicates across delivery retries; a failed publication produces an explicit delivery warning instead of linking an older review as current.
- Permission/delivery source: repository workflow and existing `GitHubDelivery`; generated review data remains public under the established public repository contract. No raw response bodies are copied into the Pages artifact.
