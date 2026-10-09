FROM kalilinux/kali-rolling

ARG KALI_MIRRORS="http://ftp.halifax.rwth-aachen.de/kali http://mirror.init7.net/kali http://kali.download/kali http://http.kali.org/kali"

LABEL org.opencontainers.image.title="mnemo-tools" \
      org.opencontainers.image.description="Kali-based security toolbox for Mnemo" \
      org.opencontainers.image.source="https://github.com/hlese/mnemosyne" \
      org.opencontainers.image.licenses="MIT"

ENV DEBIAN_FRONTEND=noninteractive \
    PIPX_HOME=/opt/pipx \
    PIPX_BIN_DIR=/usr/local/bin \
    PATH=/opt/pipx/bin:/usr/local/bin:$PATH

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Kali + Debian security tooling. Kali mirrors occasionally return transient
# 5xx responses, especially during multi-platform buildx runs. Retry apt index
# updates, install a small required base set, then best-effort install optional
# tools so one architecture-specific package does not kill the entire image.
RUN set -eux; \
    rm -f /etc/apt/sources.list.d/*; \
    printf '%s\n' \
      'Acquire::Retries "5";' \
      'Acquire::http::Timeout "30";' \
      'Acquire::https::Timeout "30";' \
      'APT::Update::Error-Mode "any";' \
      > /etc/apt/apt.conf.d/99mnemo-retries; \
    set_kali_mirror() { \
      mirror="$1"; \
      echo "Using Kali mirror: ${mirror}"; \
      echo "deb ${mirror} kali-rolling main contrib non-free non-free-firmware" > /etc/apt/sources.list; \
    }; \
    retry_apt_update() { \
      for mirror in ${KALI_MIRRORS}; do \
        set_kali_mirror "${mirror}"; \
        for attempt in 1 2 3; do \
          rm -rf /var/lib/apt/lists/*; \
          if apt-get -o APT::Update::Error-Mode=any update \
            && find /var/lib/apt/lists -type f -name '*_Packages*' | grep -q .; then \
            return 0; \
          fi; \
          echo "apt-get update failed for ${mirror}; retry ${attempt}/3"; \
          sleep $((attempt * 5)); \
        done; \
      done; \
      echo "ERROR: all Kali mirrors failed: ${KALI_MIRRORS}"; \
      return 1; \
    }; \
    install_required() { \
      retry_apt_update; \
      apt-get install -y --no-install-recommends "$@"; \
    }; \
    install_optional() { \
      retry_apt_update; \
      if apt-get install -y --no-install-recommends "$@"; then \
        return 0; \
      fi; \
      echo "Bulk optional apt install failed; retrying package-by-package"; \
      for package in "$@"; do \
        retry_apt_update; \
        apt-get install -y --no-install-recommends "${package}" \
          || echo "WARNING: skipped optional apt package: ${package}"; \
      done; \
    }; \
    install_required \
      ca-certificates \
      curl \
      wget \
      git \
      jq \
      python3 \
      python3-pip \
      python3-venv \
      pipx \
      ruby \
      ruby-dev \
      build-essential \
      nodejs \
      npm; \
    install_optional \
      nmap \
      masscan \
      dnsrecon \
      dnsenum \
      whois \
      whatweb \
      wafw00f \
      nikto \
      sqlmap \
      commix \
      gobuster \
      ffuf \
      dirb \
      wfuzz \
      hydra \
      medusa \
      ncrack \
      john \
      hashcat \
      hashid \
      hash-identifier \
      metasploit-framework \
      exploitdb \
      sslscan \
      testssl.sh \
      sslyze \
      enum4linux \
      smbclient \
      smbmap \
      ldap-utils \
      bettercap \
      ettercap-text-only \
      responder \
      yersinia \
      seclists \
      trivy \
      syft \
      grype \
      semgrep \
      bandit \
      gitleaks \
      trufflehog \
      checkov \
      prowler \
      zaproxy \
      chromium; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

# Python-based tools not always packaged consistently in Kali. Keep these
# best-effort because some projects disappear or publish wheels for one arch
# before another.
RUN set -eux; \
    pipx ensurepath; \
    pipx_install_optional() { \
      for package in "$@"; do \
        pipx install "${package}" || echo "WARNING: skipped optional pipx package: ${package}"; \
      done; \
    }; \
    pipx_install_optional \
      arjun \
      dirsearch \
      wapiti3 \
      shodan \
      detect-secrets \
      kube-hunter \
      kubesec \
      cloudsplaining \
      trufflehog3 \
      droopescan \
      xsser; \
    pipx inject wapiti3 requests beautifulsoup4 || true

# Node-based tools. These are best-effort for the same reason as pipx tools.
RUN set -eux; \
    npm_install_optional() { \
      for package in "$@"; do \
        npm install -g "${package}" || echo "WARNING: skipped optional npm package: ${package}"; \
      done; \
    }; \
    npm_install_optional \
      retire \
      jwt_tool \
      graphql-cop \
      @playwright/test; \
    npx playwright install chromium || true

# ProjectDiscovery and other Go tools are intentionally installed by package
# name/version where possible through Kali above. Users can extend this image for
# tools that require pinned upstream binaries.
WORKDIR /workspace

CMD ["bash"]
