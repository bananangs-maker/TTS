# TTS 1.3 · Rams-inspired interface

- Selected B monogram redrawn as a small, scalable SVG; sidebar, sign-in and favicon share the same asset.
- Neutral light gray navigation, white workspace, dark text, navy selection and chart accents.
- Flat panel boundaries, consistent control sizes, readable metadata, tabular figures and restrained corners.
- Six existing screens share the same design system. Reduced-motion preference respected; keyboard focus retained.
- Existing source links, actual-data-only policy and personal-data access rules remain in force.

## Apply to the existing Render deployment

Upload only these four files to the same `research_os/static/` directory in GitHub:

- `app.css`
- `app.js`
- `index.html`
- `tts-mark.svg`

Commit the changes. If Render Auto-Deploy is enabled, wait for deployment; otherwise select Deploy latest commit in Render. Refresh the app. The sidebar shows v1.3.

Do not replace GitHub Actions or secrets for this design update. No database migration or collector restart is needed.

## Validation

21 Python tests and 8 client tests passed. Desktop browser preview used the previously collected real local database. Overview, news navigation, Economic Monitor and chart range controls were checked. Responsive CSS retained and updated; no mobile-device browser verification in this revision. Production Render deployment is pending repository upload.
