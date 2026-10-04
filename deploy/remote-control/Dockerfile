FROM python:3.11.13-slim-bookworm
WORKDIR /app
COPY remote_control/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /app/requirements.lock
COPY remote_control /app/remote_control
RUN useradd --uid 10001 --create-home relay
USER 10001
CMD ["python", "-m", "remote_control.server", "--config", "/config/server.yaml"]
