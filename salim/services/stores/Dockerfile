FROM python:3.12-slim

WORKDIR /app

COPY services/stores/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY services/stores ./

CMD ["python", "main.py"]
