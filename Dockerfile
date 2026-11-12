FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e '.[api,llm]'
EXPOSE 8000
CMD ["uvicorn", "invx.api:app", "--host", "0.0.0.0", "--port", "8000"]
