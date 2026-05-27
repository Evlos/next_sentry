default:
	flask --app app run --host=0.0.0.0 --port=30808

repomix:
	repomix --include "*.py,templates/**" -o next_sentry.xml

test:
	DSN="http://1d8a70a5f11144a29150c34ad779f425@192.168.233.107:30808/1" python test_report.py
