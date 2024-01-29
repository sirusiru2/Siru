# Copyright (c) 2022-2024, InterDigital Communications, Inc
# All rights reserved.

# Redistribution and use in source and binary forms, with or without
# modification, are permitted (subject to the limitations in the disclaimer
# below) provided that the following conditions are met:

# * Redistributions of source code must retain the above copyright notice,
#   this list of conditions and the following disclaimer.
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
# * Neither the name of InterDigital Communications, Inc nor the names of its
#   contributors may be used to endorse or promote products derived from this
#   software without specific prior written permission.

# NO EXPRESS OR IMPLIED LICENSES TO ANY PARTY'S PATENT RIGHTS ARE GRANTED BY
# THIS LICENSE. THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND
# CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT
# NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
# PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
# WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
# OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import os
from pathlib import Path
from typing import Callable, Dict
from uuid import uuid4 as uuid

import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from tqdm import tqdm

from compressai_vision.evaluators import BaseEvaluator
from compressai_vision.model_wrappers import BaseWrapper
from compressai_vision.registry import register_pipeline
from compressai_vision.utils.external_exec import run_cmdline

from ..base import BasePipeline

from PIL import Image
from torchvision import transforms

def read_image(filepath: Path) -> torch.Tensor:
    assert filepath.is_file()
    img = Image.open(filepath).convert("RGB")
    return transforms.ToTensor()(img)


""" A schematic for the remote-inference pipline

.. code-block:: none

                                           ┌─────────────────┐
     ┌───────────┐       ┌───────────┐     │                 │
     │           │       │           │     │      NN Task    │
────►│  Encoder  ├──────►│  Decoder  ├────►│                 ├────►
     │           │       │           │     │                 │
     └───────────┘       └───────────┘     │                 │
                                           └─────────────────┘
                         <---------------- Remote Server ------------->
──►──────►──────►────────►──────►──────►──────►──────►──────►──────►──────►
"""


@register_pipeline("image-remote-inference")
class ImageRemoteInference(BasePipeline):
    def __init__(
        self,
        configs: Dict,
        device: str,
    ):
        super().__init__(configs, device)

    def __call__(
        self,
        vision_model: BaseWrapper,
        codec,
        dataloader: DataLoader,
        evaluator: BaseEvaluator,
    ) -> Dict:
        """Push image(s) through the encoder+decoder, returns number of bits for each image and encoded+decoded images

        Returns (nbitslist, x_hat), where nbitslist is a list of number of bits and x_hat is the image that has gone throught the encoder/decoder process
        """
        self._update_codec_configs_at_pipeline_level(len(dataloader))
        org_map_func = dataloader.dataset.get_org_mapper_func()
        output_list = []
        timing = {"encode": 0, "decode": 0, "nn_task": 0}

        for e, d in enumerate(tqdm(dataloader)):
            org_img_size = {"height": d[0]["height"], "width": d[0]["width"]}
            file_prefix = f'img_id_{d[0]["image_id"]}'

            if not self.configs["codec"]["decode_only"]:
                if e < self._codec_skip_n_frames:
                    continue
                if e >= self._codec_end_frame_idx:
                    break

                start = self.time_measure()

                padded_png = self.codec_output_dir / f"{file_prefix}.png"
                # pad frame when uneven size for yuv420 encoding
                par_cmd = [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-i",
                    d,
                    "-vf",
                    "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                    padded_png,
                ]

                run_cmdline(par_cmd, logpath=f"{padded_png}.log")

                frame = {
                    "data": {"frame": read_image(padded_png)},
                    "org_input_size": org_img_size,
                }

                # RGB to YUV conversion can happen in side of the compression code..?
                ## End function

                res = self._compress(
                    codec,
                    frame,
                    self.codec_output_dir,
                    self.bitstream_name,
                    file_prefix,
                    img_input=True,
                )
                end = self.time_measure()
                timing["encode"] = timing["encode"] + (end - start)
            else:
                res = {}
                bin_files = [
                    file_path
                    for file_path in self.codec_output_dir.glob(
                        f"{self.bitstream_name}-{file_prefix}*"
                    )
                    if file_path.suffix in [".bin", ".mp4"]
                ]
                assert (
                    len(bin_files) > 0
                ), f"no bitstream file matching {self.bitstream_name}-{file_prefix}*"
                assert (
                    len(bin_files) == 1
                ), f"Error, multiple bitstream files matching {self.bitstream_name}*"

                res["bitstream"] = bin_files[0]
                print(f"reading bitstream... {res['bitstream']}")

            if self.configs["codec"]["encode_only"] is True:
                continue

            start = self.time_measure()
            dec_out = self._decompress(
                codec, res["bitstream"], self.codec_output_dir, file_prefix
            )
            end = self.time_measure()
            timing["decode"] = timing["decode"] + (end - start)

            # Fabien
            # YUV to PNG(or JPG) conversion can happen in side of the compression code..?
            # undo the padding that happend on the input to the Encoder.
            # Plesae provide a file name of PNG (or JPG)

            # dec_d = d.copy()
            # dec_d["filename"] =
            ## End function

            # Temporary solution
            dec_d = d[0].copy()
            dec_d["org_input_size"] = dec_out["org_input_size"]
            dec_d["input_size"] = self._get_model_input_size(vision_model, d)

            start = self.time_measure()
            pred = vision_model.forward(dec_d, org_map_func)
            end = self.time_measure()
            timing["nn_task"] = timing["nn_task"] + (end - start)

            evaluator.digest(d, pred)

            out_res = d[0].copy()
            del (
                out_res["image"],
                out_res["width"],
                out_res["height"],
                out_res["image_id"],
            )
            out_res["qp"] = (
                "uncmp" if codec.qp_value is None else codec.qp_value
            )  # Assuming one qp will be used
            if self.configs["codec"]["decode_only"]:
                out_res["bytes"] = os.stat(res["bitstream"]).st_size
            else:
                out_res["bytes"] = res["bytes"][0]
            out_res["coded_order"] = e
            out_res["org_input_size"] = f'{d[0]["height"]}x{d[0]["width"]}'
            out_res["input_size"] = dec_d["input_size"][0]
            output_list.append(out_res)

        if self.configs["codec"]["encode_only"] is True:
            print(f"bitstreams generated, exiting")
            raise SystemExit(0)

        eval_performance = self._evaluation(evaluator)

        return timing, codec.eval_encode_type, output_list, eval_performance
