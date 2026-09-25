FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_DEFAULT_TIMEOUT=180
COPY pyproject.toml README.md ./
COPY parallax ./parallax
COPY tests ./tests
RUN python -m pip install 'torch>=2.5,<3' --index-url https://download.pytorch.org/whl/cpu && python -m pip install '.[test]'
COPY scripts ./scripts
CMD ["python", "-m", "pytest", "-q"]
