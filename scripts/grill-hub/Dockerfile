# Build from the repo root, so the image gets the skill folder too (compose.yml does this for you):
#   docker build -f scripts/grill-hub/Dockerfile .
FROM python:3.13-alpine
RUN adduser -D grill && mkdir /data && chown grill /data
COPY grill-me-with-ui /app/grill-me-with-ui
COPY scripts/grill-hub/hub.py /app/hub.py
ENV GRILL_SKILL_DIR=/app/grill-me-with-ui GRILL_HUB_DATA=/data GRILL_HUB_HOST=0.0.0.0
USER grill
EXPOSE 7170 7171
CMD ["python3", "-u", "/app/hub.py"]
