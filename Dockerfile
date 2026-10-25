# The Python API, run on Google Cloud Run. Firebase Hosting serves static/ and
# forwards /api/** here (see firebase.json).
FROM python:3.12-slim
# zoneinfo needs time zone data; the slim image has none.
RUN pip install --no-cache-dir tzdata
WORKDIR /app
COPY campfinder campfinder
COPY seed seed
COPY static static
COPY manage.py .
COPY data/campsites.db data/campsites.db
ENV HOST=0.0.0.0 PYTHONUNBUFFERED=1
CMD ["python3", "manage.py", "serve"]
