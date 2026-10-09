# Mnemo Tools Image

Kali-based Docker toolbox for Mnemo's registered security tools.

Default image/tag:

```text
ghcr.io/hlesey/mnemo-tools:1.0
```

## Prerequisites

- Docker
- GHCR login before pushing:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u hlese --password-stdin
```

The token needs package write permissions.

## Build

```bash
cd mnemo-tools
make build
```

`make build` uses normal `docker build` for your current platform and tags both
`ghcr.io/hlesey/mnemo-tools:1.0` and `ghcr.io/hlesey/mnemo-tools:latest` locally.

Kali mirrors occasionally return transient 5xx responses. The Dockerfile retries
apt index updates; if a package is unavailable for one architecture, optional
packages are retried one-by-one and skipped with a warning rather than failing
the full image.

The Dockerfile defaults to trying these Kali apt mirrors:

```text
KALI_MIRRORS="http://ftp.halifax.rwth-aachen.de/kali http://mirror.init7.net/kali http://kali.download/kali http://http.kali.org/kali"
```

It also removes the base image's existing `/etc/apt/sources.list.d/*` files so
only the selected mirror is active during each retry. Override mirrors if needed:

```bash
make build KALI_MIRRORS="http://mirror.example.org/kali http://http.kali.org/kali"
```

If a bad apt layer was cached, force a clean rebuild:

```bash
docker build --no-cache \
  --build-arg KALI_MIRRORS="http://ftp.halifax.rwth-aachen.de/kali http://mirror.init7.net/kali http://kali.download/kali http://http.kali.org/kali" \
  -t ghcr.io/hlesey/mnemo-tools:1.0 \
  -t ghcr.io/hlesey/mnemo-tools:latest \
  .
```

## Push image

```bash
cd mnemo-tools
make push
```

This pushes:

```text
ghcr.io/hlesey/mnemo-tools:1.0
ghcr.io/hlesey/mnemo-tools:latest
```

Override values if needed:

```bash
make push IMAGE=ghcr.io/hlesey/mnemo-tools VERSION=1.0
```

## Optional multi-platform Buildx flow

If you later want a multi-platform manifest, use the optional Buildx targets:

```bash
make buildx-build
make buildx-push
make buildx-inspect
```

Defaults:

```text
PLATFORMS=linux/amd64,linux/arm64
```

## Use with Mnemo

```bash
export MNEMO_SECURITY_DOCKER_IMAGE=ghcr.io/hlesey/mnemo-tools:1.0

uv run mnemo tools run nmap \
  --authorized "Approved under ticket SEC-123" \
  -- -sV app.example.com
```

Or pass the image explicitly:

```bash
uv run mnemo tools run nuclei \
  --docker-image ghcr.io/hlesey/mnemo-tools:1.0 \
  --authorized "Approved under ticket SEC-123" \
  -- -u https://app.example.com
```

## Notes

The image intentionally favors package-manager-installed tools. If you need
tools with upstream-only binaries, extend this image and pin versions per
architecture. Multi-platform builds remain available through the optional Buildx
targets.
