RUN_NAME="sampling_liconn_axons_cluster_$(openssl rand -hex 2)"

CV_PATH="precomputed://gs://liconn-public/ExPID82_1/segmentation/231030_agg_240123"
MIP=0
OUTPUT_DIR="/groups/troidl/troidllab/shape_reasoning/liconn_axons_cluster_v4"

NUM_WORKERS=8
FRACTION=0.01

nps --cv-path "${CV_PATH}" \
    --mip "${MIP}" \
    --fill-missing \
    --output-dir "${OUTPUT_DIR}" \
    --worker-type LocalWorker \
    --num-workers "${NUM_WORKERS}" \
    --fraction "${FRACTION}"