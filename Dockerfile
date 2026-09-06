# Multi-stage build: a slim runtime image with only installed packages and
# app code, no build toolchain, running as a non-root user.

FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim

RUN useradd --create-home --uid 1000 manifest
COPY --from=builder /install /usr/local
WORKDIR /app
COPY . .
RUN chown -R manifest:manifest /app
USER manifest

EXPOSE 8000

# docker-compose.yml's demo-ui service overrides this to run the Streamlit
# app instead -- same image, different command, no second Dockerfile.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
