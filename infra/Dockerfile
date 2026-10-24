FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70

# 受限网络（如国内云主机）到 pypi.org 会读超时，构建直接失败。
# 两个参数默认走官方源，仅在需要时用 --build-arg 指向镜像：
#   PYPI_INDEX        包索引地址，例如 https://pypi.tuna.tsinghua.edu.cn/simple
#   PYPI_FILES_HOST   文件下载主机，例如 https://pypi.tuna.tsinghua.edu.cn
# 镜像与官方逐字节一致，所以 uv.lock 里记录的 sha256 校验不会失效。
ARG PYPI_INDEX=https://pypi.org/simple
ARG PYPI_FILES_HOST=

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --index-url "${PYPI_INDEX}" uv==0.13.1

WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
# uv.lock 把 290 个下载地址写死成 files.pythonhosted.org；这里只在构建期替换下载主机，
# 仓库里的锁文件保持原样，哈希校验照旧生效。
RUN if [ -n "${PYPI_FILES_HOST}" ]; then \
        sed -i "s|https://files.pythonhosted.org|${PYPI_FILES_HOST}|g" uv.lock; \
    fi \
    && uv sync --frozen --no-dev

COPY backend/ ./
RUN DJANGO_SETTINGS_MODULE=config.settings.static_build python manage.py collectstatic --noinput
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app \
    && mkdir -p /app/private && chown app:app /app/private
USER app
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "15", "--error-logfile", "-"]
