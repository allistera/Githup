FROM python:3.13-slim-trixie

# git + gh for cloning and PRs; curl only to fetch the installers below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI - the Agent SDK drives it as a subprocess. The platform runs
# agent containers as a non-root UID that cannot read /root, so install to a
# world-readable prefix and give the runtime user a writable HOME (/tmp is the
# platform's only writable path).
RUN HOME=/opt/claude bash -c 'curl -fsSL https://claude.ai/install.sh | bash' \
    && chmod -R a+rX /opt/claude
ENV PATH="/opt/claude/.local/bin:${PATH}"
ENV HOME=/tmp

WORKDIR /workspace
COPY pyproject.toml README.md ./
COPY github_update/ ./github_update/
RUN pip install --no-cache-dir .

# The platform supplies `command` and `workingDirectory` from agent.yaml at
# container-create time; no CMD/ENTRYPOINT is needed here.
