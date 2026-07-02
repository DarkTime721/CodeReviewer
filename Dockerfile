FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN apt-get update
RUN apt-get install -y gosu
COPY . .
RUN chmod +x /app/entrypoint.sh
RUN useradd --create-home appuser
ENTRYPOINT ["/app/entrypoint.sh"]
CMD [ "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000" ]
