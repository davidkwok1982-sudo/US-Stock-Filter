FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY data ./data
ENV KAI_LUT_CACHE=/app/cache
EXPOSE 43124
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "43124"]
