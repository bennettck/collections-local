FROM public.ecr.aws/lambda/python:3.12

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY handler.py .
COPY embeddings.py .
COPY database/ ./database/

# Fix permissions for all files
RUN chmod -R 755 ${LAMBDA_TASK_ROOT}

# Set the CMD to your handler
CMD ["handler.handler"]
