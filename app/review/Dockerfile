FROM python:3.12-slim
WORKDIR /srv/review
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV REVIEW_DB=/data/review.db PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 9100
# one worker (SQLite writer), threads for concurrent readers
CMD ["gunicorn", "-w", "1", "--threads", "8", "-b", "0.0.0.0:9100", "app:app"]
