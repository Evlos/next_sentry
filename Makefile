default:
	flask --app app run --host=0.0.0.0 --port=30808

repomix:
	repomix --include "*.py,templates/**" -o next_sentry.xml

test:
	DSN="http://c692807c97a1472ea062eb8e18f9a98a@192.168.233.107:30808/1" python test_report.py
