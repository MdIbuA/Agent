# syntax=docker/dockerfile:1
# Qaid — UAE e-invoicing readiness agent. One command:
#   docker build -t qaid . && docker run -p 8000:8000 -v qaid-data:/data qaid
# then open http://localhost:8000
#
# Behind a TLS-inspecting corporate proxy, pass its CA as a build secret (used only during
# installs, never stored in the image) plus the standard proxy build args:
#   docker build --secret id=extra_ca,src=proxy-ca.crt \
#     --build-arg HTTPS_PROXY=http://proxy:3128 --build-arg HTTP_PROXY=http://proxy:3128 -t qaid .

# ---- 1. Build the web UI ------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=secret,id=extra_ca,required=false,mode=0444 \
    if [ -f /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi \
 && npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- 2. Runtime: Python API + agent + local OCR ------------------------------
FROM python:3.12-slim
RUN --mount=type=secret,id=extra_ca,required=false,mode=0444 \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources \
 && CA=""; if [ -f /run/secrets/extra_ca ]; then CA="-o Acquire::https::CaInfo=/run/secrets/extra_ca"; fi \
 && apt-get $CA update \
 && apt-get $CA install -y --no-install-recommends tesseract-ocr libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt ./
RUN --mount=type=secret,id=extra_ca,required=false,mode=0444 \
    if [ -f /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi \
 && pip install --no-cache-dir -r requirements.txt
COPY ira/ ira/
COPY benchmarks/ benchmarks/
COPY scripts/ scripts/
COPY data/ data/
COPY --from=web /web/dist web/dist

# Run as an unprivileged user; invoices and the profile persist in the /data volume.
RUN useradd --create-home --uid 10001 qaid && mkdir -p /data && chown qaid /data
USER qaid
ENV HOST=0.0.0.0 PORT=8000 QAID_DB=/data/workspace.db PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["python", "-m", "ira.server"]
