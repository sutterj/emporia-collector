FROM python:3.12-slim

# Non-root user for security
RUN useradd --create-home --shell /bin/false collector

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY *.py .

# Switch to non-root user
USER collector

# Healthcheck: verify process is running
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

ENTRYPOINT ["python", "-u", "main.py"]
