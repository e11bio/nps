#!/usr/bin/env bash
# Optimize the point clouds of one nps run for fast per-label reads, following
# https://github.com/JaneliaSciComp/pocaduck#running-the-optimization-pipeline:
#   1. shard the labels, 2. rewrite each shard in parallel, 3. consolidate.
#
# The result lands in <output-dir>/points/optimized/; pocaduck's Query picks it
# up automatically (get_blocks_for_label() then returns []).
#
# Usage: ./optimize_points.sh OUTPUT_DIR   (the --output-dir of the nps run)
set -euo pipefail

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
# nps run to optimize: its --output-dir, passed as the only argument
OUTPUT_DIR="${1:-}"
# Number of optimization workers; all of them run in parallel
NUM_SHARDS=8
# DuckDB threads per worker (NUM_SHARDS * THREADS cores in total)
THREADS=4
# Conda env with pocaduck installed
NPS_ENV="/groups/troidl/home/troidlj/miniconda3/envs/nps"
# pocaduck's optimizer script (not part of the pip package)
OPTIMIZE="/groups/troidl/home/troidlj/pocaduck/optimize_point_cloud.py"
# ----------------------------------------------------------------------------

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 OUTPUT_DIR   (the --output-dir of the nps run)" >&2
    exit 1
fi
export PATH="${NPS_ENV}/bin:${PATH}"
OUTPUT_DIR="${OUTPUT_DIR%/}"
BASE_PATH="${OUTPUT_DIR}/points"  # holds unified_index.db
SHARD_DIR="${BASE_PATH}/optimize_shards"

if [[ ! -f "${BASE_PATH}/unified_index.db" ]]; then
    echo "ERROR: ${BASE_PATH}/unified_index.db not found; did the nps run finish?" >&2
    exit 1
fi
# Interrupted workers cannot resume, so always start from a clean slate.
if [[ -e "${BASE_PATH}/optimized" ]]; then
    echo "ERROR: ${BASE_PATH}/optimized already exists; delete it to re-optimize." >&2
    exit 1
fi

echo "Sharding labels into ${NUM_SHARDS} shards..."
mkdir -p "${SHARD_DIR}"
python "${OPTIMIZE}" --action shard --base-path "${BASE_PATH}" \
    --num-shards "${NUM_SHARDS}" --shard-output-dir "${SHARD_DIR}"

echo "Optimizing shards in parallel..."
pids=()
for i in $(seq 1 "${NUM_SHARDS}"); do
    python "${OPTIMIZE}" --action optimize --base-path "${BASE_PATH}" \
        --labels-file "${SHARD_DIR}/labels_shard_${i}.txt" \
        --worker-id "worker${i}" --threads "${THREADS}" --quiet &
    pids+=($!)
done
failed=0
for pid in "${pids[@]}"; do
    wait "${pid}" || failed=$((failed + 1))
done
if (( failed > 0 )); then
    echo "ERROR: ${failed} of ${NUM_SHARDS} workers failed; delete ${BASE_PATH}/optimized and re-run." >&2
    exit 1
fi

echo "Consolidating..."
python "${OPTIMIZE}" --action consolidate --base-path "${BASE_PATH}"
echo "Done: ${BASE_PATH}/optimized/optimized_index.db"
