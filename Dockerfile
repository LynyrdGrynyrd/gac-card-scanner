# GAC Card Scanner: container image (CPU only, everything local).
# python:3.12-slim pinned by digest (Dependabot proposes updates); keep in step with Dockerfile.space
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libglib2.0-0 libgomp1 libgl1 curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/gac
# the tested, fully pinned dependency set (requirements.txt only lists the ranges)
COPY requirements.lock.txt .
RUN pip install -r requirements.lock.txt
COPY app ./app
# the app reads VERSION (version shown in the footer + update check) and mctrade-dryrun/ (MC Trade column map + file check)
COPY VERSION ./VERSION
COPY mctrade-dryrun ./mctrade-dryrun
COPY LICENSE THIRD-PARTY-NOTICES.md ./
# sample MC Trade contacts used for duplicate checks until live API access exists (copied into the data volume on first run)
COPY data/existing_contacts.csv ./data/existing_contacts.csv
COPY docker-entrypoint.sh ./
# nightly backups go to their own volume (audit 2026-10 P0-8: /srv/gac itself is root-owned and not in a volume)
ENV GAC_BACKUP_DIR=/srv/gac/backups
RUN chmod +x docker-entrypoint.sh && useradd -r -u 10001 gac && mkdir -p data/uploads data/exports certs backups && chown -R gac data certs backups
USER gac
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fsk http://localhost:8765/health || curl -fsk https://localhost:8765/health || exit 1
ENTRYPOINT ["./docker-entrypoint.sh"]
