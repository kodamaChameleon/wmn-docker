# Dockerfile
FROM python:3.9-slim

# Create a new user named "kodama"
RUN useradd -m kodama

# Create the log directory and set permissions
RUN mkdir -p /var/log/wmn-docker && chown -R kodama:kodama /var/log/wmn-docker

# Set the working directory
WORKDIR /app
COPY --chown=kodama:kodama ./app /app

# Copy the requirements file
COPY requirements.txt .

# Switch to the new user
USER kodama

# Install dependencies as the non-root user
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
ENV PATH="/home/kodama/.local/bin:$PATH"

# Set environment variables
ENV CELERY_BROKER_URL=redis://redis:6379/0
ENV CELERY_RESULT_BACKEND=redis://redis:6379/0

# Start the FastAPI server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
