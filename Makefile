default:
	flask --app app run --host=0.0.0.0 --port=30808

repomix:
	repomix --include "*.py,templates/**" -o next_sentry.xml
