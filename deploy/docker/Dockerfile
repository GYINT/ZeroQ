FROM python:3.12-slim

# 元信息
LABEL maintainer="QCM MCP Team"
LABEL version="1.0.1"
LABEL description="QCM MCP Server - Quality Control Methodology MCP"

# 环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 工作目录
WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖清单
COPY requirements.txt .

# 安装依赖
RUN pip install -r requirements.txt

# 复制代码
COPY scripts/ ./scripts/
COPY references/ ./references/
COPY outputs/ ./outputs/
COPY ../qcm_config.yaml qcm_config.yaml

# QCM 环境变量
ENV QCM_ROOT=/app
ENV QCM_AUDIT_DIR=/var/log/qcm-mcp
ENV PYTHONPATH=/app/scripts

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8080/health/live || exit 1

# 暴露端口
EXPOSE 8080

# 默认启动（HTTP 模式）
ENTRYPOINT ["python", "scripts/qcm_mcp_server.py"]
CMD ["--transport", "http", "--host", "0.0.0.0", "--port", "8080"]

# 卷（持久化）
VOLUME ["/var/log/qcm-mcp"]

# 元数据
LABEL org.opencontainers.image.title="QCM MCP Server"
LABEL org.opencontainers.image.version="1.0.1"
LABEL org.opencontainers.image.description="Quality Control Methodology MCP Server"