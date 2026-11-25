FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
# Debian security updates; pip is not needed at run time (its vendored libraries are flagged by
# scanners): removed after the install. Tests bring it back with `python -m ensurepip`.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/* \
 && pip install -r requirements.txt \
 && pip uninstall -y pip

COPY aprs_stats ./aprs_stats

RUN useradd --system --uid 10001 aprs
USER aprs

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

CMD ["uvicorn", "aprs_stats.web:app", "--host", "0.0.0.0", "--port", "8000"]
