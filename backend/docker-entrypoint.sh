#!/bin/sh
# One image, three jobs: "api" (the web server), "worker" (background jobs)
# and "beat" (the clock that starts the scheduled jobs).
set -e
cd /app/backend

# Face models for the photo step: small, checked against their recorded
# fingerprints, downloaded once into the models volume.
if [ ! -f app/assets/models/face_detection_yunet_2023mar.onnx ]; then
    python scripts/download_face_models.py || echo "WARNING: face models not downloaded; photo checks will be skipped until they are"
fi

case "$1" in
  api)
    # Bring the database up to date before serving (safe to repeat).
    alembic upgrade head
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers \
         --forwarded-allow-ips="*"
    ;;
  worker)
    exec celery -A app.celery_app worker --loglevel=INFO --concurrency=2
    ;;
  beat)
    exec celery -A app.celery_app beat --loglevel=INFO \
         --schedule /app/backend/logs/celerybeat-schedule
    ;;
  *)
    exec "$@"
    ;;
esac
