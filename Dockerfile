# Pinned by digest (audit 2 #10): tag floats and can change silently between builds.
# Update via: docker pull python:3.11-slim && docker inspect python:3.11-slim --format '{{index .RepoDigests 0}}'
FROM python:3.11-slim@sha256:6d85378d88a19cd4d76079817532d62232be95757cb45945a99fec8e8084b9c2

# Create a non-root user; pin uid for reproducible volume permissions.
RUN groupadd --system --gid 1001 app \
 && useradd  --system --uid 1001 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Install deps as root (cleaner site-packages perms), then drop privileges.
COPY --chown=app:app requirements.txt .
# Upgrade pip + wheel + setuptools BEFORE installing requirements: closes
# pip CVE-2025-8869, CVE-2026-1703, CVE-2026-3219 and wheel CVE-2026-24049
# that ship by default in python:3.11-slim. Pinned ranges so a future
# regression in pip/wheel doesn't sneak in silently.
RUN pip install --no-cache-dir --upgrade "pip>=26.0" "wheel>=0.46.2" "setuptools>=78.1.1" \
 && pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

# /app/static/uploads is written at runtime by the app — make sure the user owns it.
RUN mkdir -p /app/static/uploads && chown -R app:app /app/static

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=3).status==200 else 1)"

CMD ["sh", "entrypoint.sh"]
