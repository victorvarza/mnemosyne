#!/usr/bin/env bash
# Mount the p4de local NVMe instance store (8 x 1 TB) as one RAID-0 XFS volume.
# - No-op if the mount point is already mounted (AWS Deep Learning AMIs do this).
# - Only uses instance-store disks with no filesystem/partitions (never EBS).
# - Instance store is EPHEMERAL: data is lost on stop/terminate.
# Usage: mount-nvme.sh [mount_point]
set -euo pipefail

MOUNT_POINT="${1:-/opt/dlami/nvme}"
OWNER="$(id -un)"
RAID_DEV=/dev/md/mnemo-nvme

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

pkg_install() {
  if command -v apt-get &>/dev/null; then
    $SUDO apt-get update -qq
    $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@"
  else
    $SUDO dnf install -y -q "$@"
  fi
}

if mountpoint -q "$MOUNT_POINT" 2>/dev/null; then
  echo ">>> $MOUNT_POINT already mounted ($(df -h --output=size "$MOUNT_POINT" | tail -1 | tr -d ' '))"
  exit 0
fi

# Never touch block devices from inside a container: with SYS_ADMIN they may be
# the node's own disks. Container platforms (e.g. /mnt/localssd) provide storage.
if [ ! -d /run/systemd/system ] || [ -f /.dockerenv ] || [ -n "${KUBERNETES_SERVICE_HOST:-}" ]; then
  echo ">>> Running in a container; not mounting disks. Set HF_HOME to a large local volume."
  exit 0
fi

mapfile -t devices < <(lsblk -dpno NAME,MODEL | awk '/Instance Storage/ {print $1}')
if [ "${#devices[@]}" -eq 0 ]; then
  echo ">>> No NVMe instance-store devices found; model will be stored under \$HOME/.cache"
  exit 0
fi

free=()
for dev in "${devices[@]}"; do
  in_use="$(lsblk -no FSTYPE,MOUNTPOINT "$dev" | tr -d '[:space:]')"
  children=$(( $(lsblk -no NAME "$dev" | wc -l) - 1 ))
  if [ -z "$in_use" ] && [ "$children" -eq 0 ]; then
    free+=("$dev")
  else
    echo ">>> Skipping $dev (already has a filesystem, partitions or RAID membership)"
  fi
done

if [ "${#free[@]}" -eq 0 ]; then
  echo ">>> No unused instance-store devices; model will be stored under \$HOME/.cache"
  exit 0
fi

command -v mkfs.xfs &>/dev/null || pkg_install xfsprogs

if [ "${#free[@]}" -eq 1 ]; then
  target="${free[0]}"
else
  command -v mdadm &>/dev/null || pkg_install mdadm
  echo ">>> Creating RAID-0 over ${#free[@]} devices: ${free[*]}"
  $SUDO mdadm --create "$RAID_DEV" --level=0 --raid-devices="${#free[@]}" --run "${free[@]}"
  target="$RAID_DEV"
fi

echo ">>> Formatting $target (XFS) and mounting at $MOUNT_POINT"
$SUDO mkfs.xfs -f -q "$target"
$SUDO mkdir -p "$MOUNT_POINT"
$SUDO mount -o noatime "$target" "$MOUNT_POINT"
$SUDO chown "$OWNER": "$MOUNT_POINT"
echo ">>> Mounted $(df -h --output=size "$MOUNT_POINT" | tail -1 | tr -d ' ') at $MOUNT_POINT"
