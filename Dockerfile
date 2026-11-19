FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
LABEL org.opencontainers.image.source=https://github.com/jumpingmushroom/framecurator \
      org.opencontainers.image.licenses=MIT
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd -r -u 1000 app && mkdir /app/data && chown app /app/data
ENV FRAMECURATOR_HOME=/app PYTHONUNBUFFERED=1
USER app
EXPOSE 8099
HEALTHCHECK CMD python -c "import urllib.request as u;u.urlopen('http://localhost:8099/healthz',timeout=3)"
CMD ["python", "-m", "framecurator.frame.app"]
