FROM docker.io/cloudflare/sandbox:0.12.4-python

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl jq ripgrep \
    && curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh \
    && rm -rf /var/lib/apt/lists/*

USER root
