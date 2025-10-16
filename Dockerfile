# Use an official lightweight Python image
FROM python:3.11-slim

# Prevent Python from writing .pyc, and ensure output is flushed
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install minimal system deps (ca-certificates for https)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --root-user-action=ignore

# Copy app code
COPY . .

# Create an unprivileged user and switch to it (avoids pip root warnings and is safer)
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Port used by Render
ENV PORT=8080

# Launch
CMD ["python", "main.py"]
