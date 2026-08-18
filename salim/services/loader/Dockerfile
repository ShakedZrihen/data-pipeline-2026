FROM python:3.12-slim

WORKDIR /app

# Paths are relative to the compose build context, which is salim/ (not this
# directory), so the image can pick up shared/.
COPY services/loader/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY services/loader/*.py ./

CMD ["python", "main.py"]
