FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py .
COPY templates/ templates/
RUN mkdir uploads
EXPOSE 8000
HEALTHCHECK CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/dashboard/stats')" --timeout=5s --interval=30s
CMD ["python3", "main.py"]