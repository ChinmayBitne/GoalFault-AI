FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY goalfault ./goalfault
COPY web ./web
RUN mkdir -p /app/data
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn goalfault.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
