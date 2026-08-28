FROM python:3.12-slim

WORKDIR /app

COPY shared/requirements.txt shared-requirements.txt
COPY services/extractor/requirements.txt service-requirements.txt
RUN pip install --no-cache-dir -r shared-requirements.txt -r service-requirements.txt

COPY shared ./shared
COPY services/extractor/main.py ./main.py

CMD ["python", "main.py"]
