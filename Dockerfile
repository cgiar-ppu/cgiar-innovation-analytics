# ===========================================================================
# Synapsis Analytics Agent – Sandboxed AI Agent Container
# ===========================================================================
# Full-featured Ubuntu environment with Python, Node.js, and common data
# science / office-document tooling pre-installed so the agent can handle
# analytics and automation tasks without waiting for package installs.
# ===========================================================================

# ---- Frontend build stage ----
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# ---- Application stage ----
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    SYNAPSIS_WORKSPACE=/workspace \
    DISPLAY=:1 \
    SCREEN_WIDTH=1920 \
    SCREEN_HEIGHT=1080

# ---- Firefox (PPA — Ubuntu 22.04 snap stub is broken in Docker) ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common gnupg gpg-agent && \
    add-apt-repository -y ppa:mozillateam/ppa && \
    printf 'Package: *\nPin: release o=LP-PPA-mozillateam\nPin-Priority: 1001\n' \
      > /etc/apt/preferences.d/mozilla-firefox && \
    apt-get update && apt-get install -y --no-install-recommends firefox-esr && \
    ln -sf /usr/bin/firefox-esr /usr/local/bin/firefox && \
    rm -rf /var/lib/apt/lists/*

# ---- System packages ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-dev \
    nodejs npm \
    curl wget git jq unzip zip \
    build-essential \
    # For document generation
    pandoc \
    # For image processing
    imagemagick \
    # Networking tools
    iputils-ping dnsutils net-tools \
    # Useful CLI tools
    vim nano less tree htop \
    # For headless browser / scraping (optional)
    chromium-browser \
    # GUI / Computer Use (virtual display + VNC)
    xvfb xfce4 xfce4-terminal dbus-x11 x11vnc xdotool x11-utils \
    websockify \
    # XFCE theme extras
    adwaita-icon-theme-full papirus-icon-theme \
    # GUI applications
    mousepad atril ristretto \
    libreoffice-calc libreoffice-writer libreoffice-gtk3 \
    # Fonts (for matplotlib / docx / PDF / browser / LibreOffice rendering)
    fonts-liberation fonts-dejavu-core fonts-noto-core fonts-ubuntu \
    fonts-freefont-ttf fonts-crosextra-carlito fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/*

# ---- noVNC (Ubuntu 22.04 ships 1.0.0 which has ES module bugs in modern browsers) ----
RUN curl -sSL https://github.com/novnc/noVNC/archive/refs/tags/v1.5.0.tar.gz | \
    tar -xz -C /usr/share/ && \
    mv /usr/share/noVNC-1.5.0 /usr/share/novnc && \
    ln -sf /usr/share/novnc/vnc.html /usr/share/novnc/index.html

# ---- Claude Code CLI (needed by the SDK) ----
RUN npm install -g @anthropic-ai/claude-code@latest

# ---- Python packages: core ----
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

# ---- Python packages: data science & document toolkit ----
RUN pip3 install --no-cache-dir \
    # Data analysis
    pandas numpy scipy \
    openpyxl xlrd xlsxwriter \
    # Visualization
    matplotlib seaborn plotly \
    # Document generation
    python-docx python-pptx reportlab \
    # PDF handling
    pypdf2 pdfplumber \
    # Web / API
    requests httpx beautifulsoup4 lxml \
    # Utilities
    tabulate rich tqdm pyyaml toml \
    # Jupyter support
    jupyter nbformat \
    # Markdown
    markdown \
    # Computer Use (screenshot capture)
    Pillow

# ---- Non-root user (required: Claude Code CLI refuses --dangerously-skip-permissions as root) ----
RUN apt-get update && apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/*
RUN useradd -m -s /bin/bash synapsis

# ---- Workspace ----
RUN mkdir -p /workspace/uploads /workspace/analysis /workspace/outputs /workspace/scripts && chown -R synapsis:synapsis /workspace
WORKDIR /workspace

# ---- Application code & entrypoint ----
COPY --chown=synapsis:synapsis app.py /app/app.py
COPY --chown=synapsis:synapsis synapsis/ /app/synapsis/
COPY --from=frontend --chown=synapsis:synapsis /static /app/static
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

WORKDIR /app

EXPOSE 7777 6080

# ---- Health check ----
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:7777/api/health || exit 1

# ---- Entrypoint copies .claude config with correct ownership, then drops to synapsis ----
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python3", "app.py"]
