FROM python:3.12-slim

WORKDIR /app
COPY server.py .
COPY favicon.ico .

ENV BIND=0.0.0.0
ENV PORT=80
ENV USE_SSL=0
ENV MEMORY_DIR=/data/memory
ENV HISTORY_FILE=/data/history.jsonl

EXPOSE 80

CMD ["python", "server.py"]
