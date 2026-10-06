FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CURABOT_STATE_DIR=/data
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 curabot \
    && mkdir /data && chown curabot:curabot /data
COPY src/ ./
USER curabot
CMD ["python", "-u", "curabot.py"]
