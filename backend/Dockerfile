FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Seed explicitly: restarting must not replace signed activity history.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
