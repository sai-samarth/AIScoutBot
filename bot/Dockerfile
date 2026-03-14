FROM python:3.12-slim

# /srv/bot/ is the package; /srv is on PYTHONPATH so "from bot.x import y" works
WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./bot/

# data/ is provided via a named volume
RUN mkdir -p bot/data

ENV PYTHONPATH=/srv

CMD ["uvicorn", "bot.main:app", "--host", "0.0.0.0", "--port", "8000"]
