# Builds the dashboard, then serves it and the API from one Python process.

FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml ./backend/
COPY backend/src ./backend/src
RUN pip install --no-cache-dir ./backend
COPY --from=web /web/dist ./frontend/dist

ENV HOUSE_AGENT_FRONTEND_DIST=/app/frontend/dist \
    HOUSE_AGENT_DATABASE_URL=sqlite:////data/house_agent.db \
    HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000
# One process only: the scheduler and search runs live in it.
CMD ["house-agent", "serve"]
