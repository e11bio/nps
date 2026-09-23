#!/usr/bin/env bash
# Optimize the point clouds of one nps run for fast per-label reads on LSF,
# following https://github.com/JaneliaSciComp/pocaduck#running-the-optimization-pipeline.
# Submits three chained jobs and returns immediately:
#   1. shard        split the labels into NUM_WORKERS shard files
#   2. optimize     job array, one worker per shard (starts when 1 is done)
#   3. consolidate  build optimized_index.db (starts when all of 2 are done)
#
# The result lands in <output-dir>/points/optimized/; pocaduck's Query picks it
# up automatically (get_blocks_for_label() then returns []).
#
# Run from an LSF submit host (e.g. a cluster login node).
# Usage: ./optimize_points_cluster.sh OUTPUT_DIR   (the --output-dir of the nps run)
set -euo pipefail

# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
# nps run to optimize: its --output-dir, passed as the only argument
OUTPUT_DIR="${1:-}"
# Number of optimization workers (one LSF job each, one label shard each)
NUM_WORKERS=128
# Maximum number of workers running at the same time (limits file system load)
MAX_RUNNING=128
# DuckDB threads per worker; also the number of slots requested per worker
THREADS=2
# Slots for the shard and consolidate jobs, which load all labels at once
# (~15 GB per slot; sharding 169M FlyWire labels needs more than 16 GB)
BIG_JOB_SLOTS=4
# LSF project to charge and queue to submit to
CHARGE_CODE="miaai"
QUEUE="local"
# Conda env with pocaduck installed
NPS_ENV="/groups/troidl/home/troidlj/miniconda3/envs/nps"
# pocaduck's optimizer script (not part of the pip package)
OPTIMIZE="/groups/troidl/home/troidlj/pocaduck/optimize_point_cloud.py"
# ----------------------------------------------------------------------------

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 OUTPUT_DIR   (the --output-dir of the nps run)" >&2
    exit 1
fi
if ! command -v bsub > /dev/null; then
    echo "ERROR: bsub not found; run this from an LSF submit host." >&2
    exit 1
fi
OUTPUT_DIR="$(realpath "${OUTPUT_DIR}")"
BASE_PATH="${OUTPUT_DIR}/points"  # holds unified_index.db
SHARD_DIR="${BASE_PATH}/optimize_shards"
PYTHON="${NPS_ENV}/bin/python"
RUN_NAME="optimize_$(basename "${OUTPUT_DIR}")_$(openssl rand -hex 2)"
LOG_DIR="$(pwd)/logs/${RUN_NAME}"

if [[ ! -f "${BASE_PATH}/unified_index.db" ]]; then
    echo "ERROR: ${BASE_PATH}/unified_index.db not found; did the nps run finish?" >&2
    exit 1
fi
# Interrupted workers cannot resume, so always start from a clean slate.
if [[ -e "${BASE_PATH}/optimized" ]]; then
    echo "ERROR: ${BASE_PATH}/optimized already exists; delete it to re-optimize." >&2
    exit 1
fi
mkdir -p "${LOG_DIR}" "${SHARD_DIR}"

# 1. Shard. Old shard files are removed first so none from an earlier run with
# a different NUM_WORKERS are left behind.
bsub -J "${RUN_NAME}_shard" -P "${CHARGE_CODE}" -q "${QUEUE}" -n "${BIG_JOB_SLOTS}" \
    -o "${LOG_DIR}/shard.log" \
    "rm -f ${SHARD_DIR}/labels_shard_*.txt && \
     ${PYTHON} ${OPTIMIZE} --action shard --base-path ${BASE_PATH} \
         --num-shards ${NUM_WORKERS} --shard-output-dir ${SHARD_DIR}"

# 2. Optimize, one array element per shard. \$LSB_JOBINDEX is expanded on the
# worker. pocaduck can create fewer shards than requested (it rounds the shard
# size up), so workers without a shard file have nothing to do.
bsub -J "${RUN_NAME}_optimize[1-${NUM_WORKERS}]%${MAX_RUNNING}" \
    -P "${CHARGE_CODE}" -q "${QUEUE}" -n "${THREADS}" \
    -w "done(${RUN_NAME}_shard)" \
    -o "${LOG_DIR}/worker_%I.log" \
    "f=${SHARD_DIR}/labels_shard_\${LSB_JOBINDEX}.txt; \
     if [ ! -f \$f ]; then echo \"no shard file \$f, nothing to do\"; exit 0; fi; \
     ${PYTHON} ${OPTIMIZE} --action optimize --base-path ${BASE_PATH} \
         --labels-file \$f --worker-id worker\${LSB_JOBINDEX} --threads ${THREADS}"

# 3. Consolidate. pocaduck skips a batch that fails and the worker still exits
# 0, so refuse to consolidate if any worker log reports a failed batch.
bsub -J "${RUN_NAME}_consolidate" -P "${CHARGE_CODE}" -q "${QUEUE}" -n "${BIG_JOB_SLOTS}" \
    -w "done(${RUN_NAME}_optimize)" \
    -o "${LOG_DIR}/consolidate.log" \
    "if grep -l 'Error processing batch' ${LOG_DIR}/worker_*.log; then \
         echo 'ERROR: the workers above skipped failed batches; not consolidating.'; exit 1; \
     fi; \
     ${PYTHON} ${OPTIMIZE} --action consolidate --base-path ${BASE_PATH} --threads ${BIG_JOB_SLOTS}"

echo "Submitted ${RUN_NAME} (${NUM_WORKERS} workers). Follow it with: bjobs -w | grep ${RUN_NAME}"
echo "Logs: ${LOG_DIR}"
echo "Result: ${BASE_PATH}/optimized/optimized_index.db"
