FROM python:3.12-slim

RUN pip install fastapi uvicorn

WORKDIR /app
COPY app.py .

RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]