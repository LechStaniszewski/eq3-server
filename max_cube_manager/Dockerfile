FROM ghcr.io/home-assistant/base-python:3.14-alpine3.24

WORKDIR /opt
COPY . /opt/eq3_server

CMD ["/command/with-contenv", "python3", "-m", "eq3_server.home_assistant"]
