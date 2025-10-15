# Базовый образ
FROM python:3.11-slim

# Рабочая директория
WORKDIR /app

# Установка зависимостей ОС для Pillow, DeepFace, OpenCV и ffmpeg для аудио
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libsm6 libxrender1 libxext6 ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

# Копируем файлы зависимостей
COPY requirements.txt .

# Устанавливаем Python зависимости
RUN pip install --no-cache-dir -r requirements.txt --root-user-action=ignore

# Копируем весь код бота
COPY . .

# Порт для Render
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# Запуск приложения
CMD ["python", "main.py"]
