FROM python:3.11-slim

# Create a non-root user; pin uid for reproducible volume permissions.
RUN groupadd --system --gid 1001 app \
 && useradd  --system --uid 1001 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Install deps as root (cleaner site-packages perms), then drop privileges.
COPY --chown=app:app requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

# /app/static/uploads is written at runtime by the app — make sure the user owns it.
RUN mkdir -p /app/static/uploads && chown -R app:app /app/static

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=3).status==200 else 1)"

CMD ["sh", "entrypoint.sh"]
