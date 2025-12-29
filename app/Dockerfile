# Lambda container image for Collections API
# Based on AWS Lambda Python 3.12 base image

FROM public.ecr.aws/lambda/python:3.12

# Build arguments for version tracking
ARG GIT_SHA=unknown
ARG GIT_TAG=
ARG GIT_BRANCH=unknown
ARG BUILD_TIMESTAMP=unknown

# Set as environment variables (available at runtime)
ENV GIT_SHA=${GIT_SHA}
ENV GIT_TAG=${GIT_TAG}
ENV GIT_BRANCH=${GIT_BRANCH}
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

# Set working directory
WORKDIR ${LAMBDA_TASK_ROOT}

# Copy requirements file from project root
COPY requirements.txt .

# Install Python dependencies
# Use --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (must build from project root)
COPY main.py .
COPY models.py .
COPY version.py .
COPY database_sqlalchemy.py .
COPY llm.py .
COPY embeddings.py .
COPY app/ ./app/
COPY config/ ./config/
COPY retrieval/ ./retrieval/
COPY chat/ ./chat/
COPY database_orm/ ./database_orm/
COPY utils/ ./utils/

# Fix permissions for all files
RUN chmod -R 755 ${LAMBDA_TASK_ROOT}

# Create necessary directories
RUN mkdir -p /tmp/images /tmp/data

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Lambda handler
# This will call the Mangum handler from main.py
CMD ["main.handler"]
