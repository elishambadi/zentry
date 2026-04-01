FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN chmod +x /app/entrypoint.sh

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["/app/entrypoint.sh"]