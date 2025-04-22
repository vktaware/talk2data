# Use the official Python 3.11 image as the base image
FROM python:3.11

# Set the working directory in the container
WORKDIR /app

# Install system dependencies for ODBC and SQL Server
RUN apt-get update && apt-get install -y \
    unixodbc \
    unixodbc-dev \
    libodbc1 \
    curl \
    gnupg2 \
    # Installing additional dependencies for various databases (Optional)
    # Uncomment if you're using PostgreSQL
    # postgresql-client \
    # Uncomment if you're using MySQL
    # libmysqlclient-dev \
    # Uncomment if you're using Redis
    # redis-tools \
    && apt-get clean

# Install Microsoft ODBC Driver for SQL Server
RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/ubuntu/20.04/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql17 \
    && apt-get clean

# Upgrade pip and setuptools to ensure the latest versions
RUN pip install --upgrade pip setuptools

# Copy the requirements.txt into the container
COPY requirements.txt .

# Install Python dependencies from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Expose port 80 to the outside world (Azure uses this by default)
EXPOSE 80

# Command to run the application using Gunicorn with Uvicorn workers
CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "main:app", "--bind", "0.0.0.0:80"]
