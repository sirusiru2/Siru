#! /usr/bin/env bash

RUN="sequential" # "gnu_parallel" or "sequential" or "slurm"

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
INPUT_DIR="${SCRIPT_DIR}/../../../vcm_testdata" # needed for NN_PART2
BITSTREAM_DIR="${SCRIPT_DIR}/../../../"


#################################################################
# CODEC_PARAMS="++pipeline.codec.encode_only=True" -> Only Encode
# CODEC_PARAMS="++pipeline.codec.decode_only=True" -> Only Decode
# CODEC_PARAMS="" -> Encode + Decode
CODEC_PARAMS="++pipeline.codec.decode_only=True" 
EXPERIMENT=""
DEVICE="cpu"
#################################################################

# total number of jobs = 18
if [[ ${RUN} == "gnu_parallel" ]]; then
    MAX_PARALLEL=18 
    run_scripts () {
        sem -j $MAX_PARALLEL bash $1
    }
    export -f run_scripts
elif [[ ${RUN} == "slurm" ]]; then
    run_scripts () {
        sbatch --mem=64G -c 2 --reservation=deepvideo --job-name=tvd_decode $1
    }
    export -f run_scripts
else
    run_scripts () {
        bash $1
    }
    export -f run_scripts
fi

for SEQ in \
            'TVD-01' \
            'TVD-02' \
            'TVD-03'
do
    for BITSTREAM in $( find ${BITSTREAM_DIR} -type f -name "mpeg-tracking-${SEQ}*.bin" );
    do
        # Get QP from bitstream name
        QP=$(echo "$BITSTREAM" | grep -oP '(?<=qp)[^_]*(?=_qpdensity)' | tail -n 1)
        echo RUN: ${RUN}, Input Dir: ${INPUT_DIR}, Bitstream Dir: ${BITSTREAM_DIR}, Exp Name: ${EXPERIMENT}, Device: ${DEVICE}, QP: ${QP}, SEQ: ${SEQ}, CODEC_PARAMS: ${CODEC_PARAMS}
        run_scripts "../mpeg_cfp_tvd.sh ${INPUT_DIR} ${BITSTREAM_DIR} '${EXPERIMENT}' ${DEVICE} ${QP} ${SEQ} ${CODEC_PARAMS}"
    done
done

# GENERATE CSV
if [[ ${RUN} == "gnu_parallel" ]]; then
    sem --wait
    bash gen_csv.sh TVD ${BITSTREAM_DIR}/split-inference-video/cfp_codec${EXPERIMENT}/MPEGTVDTRACKING/
elif [[ ${RUN} == "slurm" ]]; then
    sbatch --dependency=singleton --job-name=tvd_decode  gen_csv.sh TVD ${BITSTREAM_DIR}/split-inference-video/cfp_codec${EXPERIMENT}/MPEGTVDTRACKING/
else
    bash gen_csv.sh TVD ${BITSTREAM_DIR}/split-inference-video/cfp_codec${EXPERIMENT}/MPEGTVDTRACKING/
fi


