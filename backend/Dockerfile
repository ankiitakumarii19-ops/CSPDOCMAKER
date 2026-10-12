# CSPdocMaker backend — API, background worker and scheduler share this image.
# Built from the repository root:  docker build -f backend/Dockerfile .
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# LibreOffice turns the Word documents into PDF. The templates use Calibri
# and Cambria (Microsoft fonts Linux does not have); Carlito and Caladea are
# free fonts with the same letter widths, which LibreOffice swaps in
# automatically, so the documents keep their layout. Liberation covers
# Arial / Times New Roman / Courier New the same way.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libreoffice-writer-nogui \
      fonts-crosextra-carlito fonts-crosextra-caladea \
      fonts-liberation fonts-dejavu-core \
      libglib2.0-0 libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ /app/backend/
COPY templates/ /app/templates/
RUN sed -i 's/\r$//' /app/backend/docker-entrypoint.sh \
 && chmod +x /app/backend/docker-entrypoint.sh \
 && useradd --create-home --uid 1000 app \
 && mkdir -p generated_documents exported_documents logs app/assets/models credentials \
 && chown -R app:app /app

USER app
EXPOSE 8000
ENTRYPOINT ["/app/backend/docker-entrypoint.sh"]
CMD ["api"]
