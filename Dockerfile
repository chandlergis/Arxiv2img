# Dockerfile

# 1. 选择一个基础镜像 (使用官方 Python 镜像的 slim 版本以减小体积)
FROM python:3.10-slim

# 2. 设置工作目录
# 后续的 COPY, RUN, CMD 指令都会在这个目录下执行
WORKDIR /app

# 3. 复制依赖文件
# 先复制 requirements.txt 可以利用 Docker 的层缓存机制
# 只有当 requirements.txt 变化时，下面的 RUN 才会重新执行
COPY requirements.txt .

# 4. 安装依赖
# --no-cache-dir 减少镜像大小
# --upgrade pip 确保 pip 是最新版本
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 5. 复制应用程序代码
# 将当前目录下的所有文件（包括 main.py）复制到容器的 /app 目录下
COPY . .

# 6. 声明容器将监听的端口
# 这主要是文档作用，实际端口映射在 docker run 时指定
EXPOSE 18001

# 7. 容器启动时运行的命令
# 使用 uvicorn 启动 FastAPI 应用
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "18001"]