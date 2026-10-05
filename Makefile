default:
	env READ_ONLY="true" flask --app app run --host=0.0.0.0 --port=30808

# Rebuild static/app.css from src/app.css. Node is a build-time dependency
# only — static/app.css is committed, so `python app.py` and the Docker image
# never need it.
css:
	npm run css

# Re-download the vendored woff2 subsets into static/fonts/.
fonts:
	npm run fonts

# Every foreground/background pair the UI renders, checked against WCAG AA.
# Reads the tokens out of src/app.css, so the audit cannot drift from the
# stylesheet.
contrast:
	node scripts/check-contrast.mjs

assets: fonts css contrast

# Rebuild CSS and check it in. Run this after editing any template.
build: css contrast

repomix:
	repomix --include "*.py,templates/**" -o next_sentry.xml

test:
	DSN="http://c692807c97a1472ea062eb8e18f9a98a@192.168.233.107:30808/1" python test_report.py
