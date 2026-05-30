FROM python:3.10-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose port
EXPOSE 9898

# Run with uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9898"]
