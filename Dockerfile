FROM python:3.12-slim

# Установка ffmpeg
RUN apt update && apt install -y ffmpeg

# Установка зависимостей проекта
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

CMD ["python", "main.py"]