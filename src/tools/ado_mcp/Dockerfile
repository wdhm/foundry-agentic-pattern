FROM mcr.microsoft.com/azurelinux/base/python:3.12

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ado_mcp ./ado_mcp

USER 10001
EXPOSE 8000
CMD ["python3", "-m", "uvicorn", "ado_mcp.server:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
