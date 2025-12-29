FROM public.ecr.aws/lambda/python:3.12

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
