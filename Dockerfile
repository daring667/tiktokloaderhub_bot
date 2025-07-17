FROM python:3.12-slim AS build
RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg build-essential libffi-dev \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python3", "-m", "main"]
