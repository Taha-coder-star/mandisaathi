# One image, three roles (RFC D15). Pick the role with the command:
#   web:    default CMD
#   worker: python -m app.worker
#   batch:  python -m mandi.batch   (one run, exits)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
COPY mandi ./mandi
RUN pip install . && useradd --system --no-create-home mandi

USER mandi
EXPOSE 8000
CMD ["uvicorn", "app.web:app", "--host", "0.0.0.0", "--port", "8000"]
