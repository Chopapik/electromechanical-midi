FROM node:22-bookworm-slim AS frontend
WORKDIR /app/web
COPY web/package*.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM frontend AS frontend-test
CMD ["npm", "test"]

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    SDL_AUDIODRIVER=alsa SDL_ALSA_AUDIO_DEVICE=hw:0,0
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg alsa-utils \
    && rm -rf /var/lib/apt/lists/*
COPY host/requirements.txt /app/host/requirements.txt
RUN pip install --no-cache-dir -r host/requirements.txt platformio
COPY host/ /app/host/
COPY firmware/ /app/firmware/
COPY config/ /app/config/
COPY scripts/ /app/scripts/
COPY --from=frontend /app/web/dist /app/web/dist
RUN mkdir -p /app/midi
EXPOSE 8000
CMD ["python", "-m", "host.web.server", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS backend-test
RUN apt-get update && apt-get install -y --no-install-recommends g++ \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir httpx
COPY Dockerfile compose.yaml .dockerignore /app/
CMD ["python", "-m", "unittest", "discover", "-s", "host/tests"]

FROM runtime AS app
