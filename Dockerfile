FROM python:3.12-slim

# 🧱 Установка системных зависимостей (для tgcrypto и ffmpeg)
RUN apt update && apt install -y \
    gcc \
    build-essential \
    libssl-dev \
    ffmpeg \
 && apt clean \
 && rm -rf /var/lib/apt/lists/*

# Установка зависимостей Python
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь проект
COPY . .

# Запуск
CMD ["python", "main.py"]
