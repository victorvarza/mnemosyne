IMAGE ?= ghcr.io/hlesey/mnemo-tools
VERSION ?= 1.0
KALI_MIRRORS ?= http://ftp.halifax.rwth-aachen.de/kali http://mirror.init7.net/kali http://kali.download/kali http://http.kali.org/kali
PLATFORMS ?= linux/amd64,linux/arm64
BUILDER ?= mnemo-tools-builder

.PHONY: help build push buildx-builder buildx-build buildx-push buildx-inspect clean-builder

help:
	@echo "Targets:"
	@echo "  make build         Build image for the current Docker platform"
	@echo "  make push          Push $(IMAGE):$(VERSION) and $(IMAGE):latest"
	@echo "  make buildx-build  Optional: build multi-platform image into buildx cache"
	@echo "  make buildx-push   Optional: build and push multi-platform image"
	@echo "  make buildx-inspect Optional: inspect remote multi-platform manifest"
	@echo "  make clean-builder Optional: remove buildx builder $(BUILDER)"
	@echo ""
	@echo "Variables:"
	@echo "  IMAGE=$(IMAGE)"
	@echo "  VERSION=$(VERSION)"
	@echo "  KALI_MIRRORS=$(KALI_MIRRORS)"
	@echo "  PLATFORMS=$(PLATFORMS)"
	@echo "  BUILDER=$(BUILDER)"

build:
	docker build \
		--build-arg KALI_MIRRORS='$(KALI_MIRRORS)' \
		--tag $(IMAGE):$(VERSION) \
		--tag $(IMAGE):latest \
		.

push:
	docker push $(IMAGE):$(VERSION)
	docker push $(IMAGE):latest

buildx-builder:
	@docker buildx inspect $(BUILDER) >/dev/null 2>&1 || docker buildx create --name $(BUILDER) --use
	@docker buildx inspect --bootstrap $(BUILDER) >/dev/null

buildx-build: buildx-builder
	docker buildx build \
		--builder $(BUILDER) \
		--build-arg KALI_MIRRORS='$(KALI_MIRRORS)' \
		--platform $(PLATFORMS) \
		--tag $(IMAGE):$(VERSION) \
		--provenance=false \
		.

buildx-push: buildx-builder
	docker buildx build \
		--builder $(BUILDER) \
		--build-arg KALI_MIRRORS='$(KALI_MIRRORS)' \
		--platform $(PLATFORMS) \
		--tag $(IMAGE):$(VERSION) \
		--tag $(IMAGE):latest \
		--provenance=false \
		--push \
		.

buildx-inspect:
	docker buildx imagetools inspect $(IMAGE):$(VERSION)

clean-builder:
	docker buildx rm $(BUILDER)
