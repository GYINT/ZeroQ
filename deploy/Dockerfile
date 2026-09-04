# QCM MCP Server — 生产镜像（E1-02 · Docker Compose 全栈编排）
FROM python:3.13-slim

WORKDIR /app

# 基础编译链（jieba 等纯 Python 包仅需标准工具链，slim 已含）
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖清单并安装
#  - 项目自有：requirements.txt（必需）+ requirements-optional.txt（可选能力）
#  - 运行时补充：urllib3（E1-03 连接池）/ requests（出站调用）/ jieba（语料加载）
COPY requirements.txt requirements-optional.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt -r /app/requirements-optional.txt \
    && pip install --no-cache-dir "urllib3>=2.0" "requests>=2.28" "jieba>=0.42"

# 复制运行时所需代码与语料（HTTP 模式只需 scripts/ + references/）
COPY scripts/ /app/scripts/
COPY references/ /app/references/

ENV QCM_REQUIRE_TOKEN=0 \
    QCM_ACCESS_LOG_DIR=/var/log/qcm-access \
    QCM_AUDIT_DIR=/var/log/qcm-audit \
    PYTHONUNBUFFERED=1

RUN mkdir -p /var/log/qcm-access /var/log/qcm-audit

EXPOSE 8080

# HTTP 传输，监听所有网卡（容器化环境由 compose 端口映射暴露）
CMD ["python", "scripts/mcp_server.py", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]
