# syntax=docker/dockerfile:1

#checkov:skip=CKV_DOCKER_2: HEALTHCHECK is not applicable

# ==============================================================================
# intermediate images
# ==============================================================================

FROM library/alpine:3.22 AS builder

ENV LANG=C

# install Python
ENV PIP_ROOT_USER_ACTION=ignore
RUN apk add python3 py3-pip git && \
    pip install --break-system-packages uv==0.6.12

RUN mkdir /cmd/
COPY pyproject.toml uv.lock /cmd/
WORKDIR /cmd/
ENV NO_COLOR=1
RUN uv sync --locked --no-dev
COPY update-release-branch.py /cmd/.venv/bin/update-release-branch

# ==============================================================================
# final image
# ==============================================================================

FROM library/alpine:3.22

RUN apk --no-cache add python3 py3-pip git yq

COPY --from=builder /cmd/ /cmd
ENV PATH="/cmd/.venv/bin:$PATH"
WORKDIR /cmd/

# Allow Git to operate in CI environments where the repository directory is
# owned by a different user (e.g. when GitLab Runner checks out the repo as
# root, but the container runs as a non-root user). Without this, Git may refuse
# operations like `git add` due to "dubious ownership" warnings.
RUN git config --system --add safe.directory '*'

RUN addgroup -S cmd && adduser -S cmd -G cmd
USER cmd
