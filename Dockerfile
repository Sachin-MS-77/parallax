FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY pyproject.toml README.md ./
COPY chimera ./chimera
COPY tests ./tests
RUN python -m pip install 'torch>=2.5,<3' --index-url https://download.pytorch.org/whl/cpu && python -m pip install '.[test]'
CMD ["python", "-m", "pytest", "-q"]
