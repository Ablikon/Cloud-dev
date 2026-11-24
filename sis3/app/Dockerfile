# Pinned to a digest, not a tag: python:3.12-slim-bookworm moves, these bytes do not.
# (slide 4 — "app:1.4.2 is a movable pointer; app@sha256:... is the exact bytes")
FROM python:3.12-slim-bookworm@sha256:82836454a795d9d75549a9e157fd08dbac6c383292cf89e99f4248a97ce6b2ff

# Dependencies before application code, so editing worker.py reuses the pip layer
# instead of reinstalling boto3 on every build (slide 4 — layer caching).
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker.py .

# A task is not a server: nothing here should ever need root.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin worker
USER 10001

ENV PORT=8080 \
    PYTHONUNBUFFERED=1
EXPOSE 8080

ENTRYPOINT ["python", "worker.py"]
