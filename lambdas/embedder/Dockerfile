FROM public.ecr.aws/lambda/python:3.12

# Build arguments for version tracking
ARG GIT_SHA=unknown
ARG GIT_BRANCH=unknown
ARG BUILD_TIMESTAMP=unknown
ARG APP_VERSION=0.1.0

# Set as environment variables (available at runtime)
ENV GIT_SHA=${GIT_SHA}
ENV GIT_BRANCH=${GIT_BRANCH}
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}
ENV APP_VERSION=${APP_VERSION}

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY lambdas/embedder/handler.py ./handler.py
COPY embeddings.py .

# Copy database modules (aliased as database_orm for compatibility)
COPY database_orm/ ./database_orm/

# Copy utils for document builder
COPY utils/ ./utils/

# Copy retrieval for PGVectorStoreManager
COPY retrieval/ ./retrieval/

# Fix permissions for all files
RUN chmod -R 755 ${LAMBDA_TASK_ROOT}

# Set the CMD to your handler
CMD ["handler.handler"]
