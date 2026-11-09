# Production image: python stdlib only, runs as an unprivileged user.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    HOTEL_HOST=0.0.0.0 HOTEL_PORT=8000 HOTEL_DB=/data/hotel.db HOTEL_BACKUP_DIR=/data/backups \
    HOTEL_SEED_DEMO=0 HOTEL_TRUST_PROXY=1 HOTEL_SECURE_COOKIES=1
RUN useradd --system --uid 10001 --home /app hotel && mkdir -p /data && chown hotel /data
WORKDIR /app
COPY --chown=hotel:hotel hotel ./hotel
COPY --chown=hotel:hotel static ./static
COPY --chown=hotel:hotel run.py ./
USER hotel
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["python", "run.py"]
