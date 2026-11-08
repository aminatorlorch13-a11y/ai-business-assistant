FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates coreutils findutils grep sed gawk \
    git make cmake pkg-config \
    python3 python3-pip python3-venv \
    nodejs npm \
    default-jdk \
    gcc g++ clang \
    golang-go rustc cargo \
    php-cli composer \
    ruby-full \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 forge \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/sh forge \
    && mkdir -p /workspace \
    && chown -R forge:forge /workspace /home/forge

WORKDIR /workspace
USER 1000:1000
CMD ["/bin/sh"]
