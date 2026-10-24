# Build from this folder (compose.yml does this for you): docker build .
FROM python:3.13-alpine
RUN adduser -D hub && mkdir /data && chown hub /data
COPY hub.py pages.py /app/
COPY static /app/static
ENV ARTIFACT_HUB_DATA=/data ARTIFACT_HUB_HOST=0.0.0.0 PYTHONDONTWRITEBYTECODE=1
USER hub
EXPOSE 7172 7173
CMD ["python3", "-u", "/app/hub.py"]
