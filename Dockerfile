# TripSight / tripcore：命令行和 MCP 服务（stdio）的镜像。
# 网页工作台刻意只监听本机 127.0.0.1（带一次性令牌），所以不放进容器；请在本机直接运行 `python -m tripcore web`。
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY tripcore ./tripcore
COPY examples ./examples
COPY skills ./skills
COPY scripts ./scripts

# 不用 root 运行；行程数据放在挂载的 /data 里
RUN useradd --create-home app && mkdir /data && chown app /data
USER app
ENV TRIPCORE_FILE=/data/trip.json

# 默认启动 MCP 服务（stdio）。其他用法：docker run --rm IMAGE python -m tripcore demo
CMD ["python", "-m", "tripcore.mcp_server"]
