"""SAM on Modal for the birr backend (SAM_PROVIDER=modal): one photo and a text prompt in,
note boxes out. Deploy and test steps: modal_sam/README.md.

SAM_MODEL picks the model when you deploy:
- sam3.1 (default): facebook/sam3.1 through the SAM 3.1 predictor. The photo runs as a one-frame
  video and the text prompt goes on frame 0; add_prompt returns that frame's objects.
- sam3: facebook/sam3 through the SAM 3 image model (Sam3Processor).

Deploy from the repo root:  modal deploy -m modal_sam.app
"""

from __future__ import annotations

import io
import os
import tempfile
import time

import modal

SAM_MODEL = os.environ.get("SAM_MODEL", "sam3.1")
GPU = os.environ.get("SAM_GPU", "L4")
# facebookresearch/sam3 main on 2026-10-23. The SAM 3.1 checkpoint needs recent code.
SAM3_COMMIT = "f1647e8d0c1d280991f4d1b7d974c2704537fe66"
HF_CACHE = "/root/.cache/huggingface"

if SAM_MODEL not in ("sam3.1", "sam3"):
    raise SystemExit(f"SAM_MODEL must be sam3.1 or sam3, not {SAM_MODEL!r}")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .pip_install("torch==2.10.0", "torchvision", index_url="https://download.pytorch.org/whl/cu128")
    .pip_install(
        "fastapi[standard]",
        "pillow",
        "psutil",
        "scipy",
        "scikit-image",
        "opencv-python-headless",
        "setuptools<81",  # sam3's model_builder imports pkg_resources
    )
    .run_commands(
        "git clone https://github.com/facebookresearch/sam3.git /opt/sam3"
        f" && cd /opt/sam3 && git checkout {SAM3_COMMIT} && pip install -e ."
    )
    .add_local_python_source("modal_sam")
)

app = modal.App("birr-sam", image=image)
hf_cache = modal.Volume.from_name("birr-sam-hf-cache", create_if_missing=True, version=2)


def _open(data: bytes):
    from PIL import Image, UnidentifiedImageError

    from modal_sam import detect

    try:
        picture = Image.open(io.BytesIO(data))
        picture.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise detect.BadRequest("image is not a readable picture") from exc
    return picture.convert("RGB")


@app.cls(
    gpu=GPU,
    env={"SAM_MODEL": SAM_MODEL},
    secrets=[modal.Secret.from_name("birr-hf")],  # HF_TOKEN with access to the model repo
    volumes={HF_CACHE: hf_cache},
    min_containers=int(os.environ.get("SAM_MIN_CONTAINERS", "0")),  # 1 keeps a GPU warm (billed)
    max_containers=1,
    scaledown_window=300,
    startup_timeout=900,  # the first start downloads the weights
    timeout=120,
)
class Sam:
    @modal.enter()
    def load(self):
        started = time.perf_counter()
        if SAM_MODEL == "sam3":
            from sam3.model.sam3_image_processor import Sam3Processor
            from sam3.model_builder import build_sam3_image_model

            self.processor = Sam3Processor(build_sam3_image_model())
        else:
            from sam3.model_builder import build_sam3_predictor

            # FlashAttention 3 only runs on Hopper GPUs; L4 and A10 run without it.
            self.predictor = build_sam3_predictor(
                version="sam3.1", use_fa3=False, async_loading_frames=False
            )
        hf_cache.commit()
        print(f"{SAM_MODEL} loaded in {time.perf_counter() - started:.1f} s")

    def _sam3(self, picture, prompt: str, threshold: float) -> list[dict]:
        import torch

        from modal_sam import detect

        with torch.inference_mode():
            self.processor.set_confidence_threshold(threshold)
            state = self.processor.set_image(picture)
            out = self.processor.set_text_prompt(prompt=prompt, state=state)
        boxes = out["boxes"].float().cpu().tolist()
        scores = out["scores"].float().cpu().tolist()
        return detect.from_xyxy(boxes, scores, picture.width, picture.height, threshold)

    def _sam31(self, picture, prompt: str, threshold: float) -> list[dict]:
        import torch

        from modal_sam import detect

        # The predictor turns bf16 autocast on in the thread that built it. FastAPI runs this
        # handler in a worker thread, so turn it on here too.
        with tempfile.TemporaryDirectory() as tmp, torch.autocast("cuda", dtype=torch.bfloat16):
            path = os.path.join(tmp, "photo.jpg")
            picture.save(path, quality=95)
            start = {"type": "start_session", "resource_path": path}
            session = self.predictor.handle_request(request=start)["session_id"]
            try:
                prompt_request = {
                    "type": "add_prompt",
                    "session_id": session,
                    "frame_index": 0,
                    "text": prompt,
                    "output_prob_thresh": threshold,
                }
                out = self.predictor.handle_request(request=prompt_request)["outputs"]
            finally:
                close = {"type": "close_session", "session_id": session}
                self.predictor.handle_request(request=close)
        boxes = out["out_boxes_xywh"].tolist()
        scores = out["out_probs"].tolist()
        return detect.from_xywh_normalized(boxes, scores, picture.width, picture.height, threshold)

    @modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
    def segment(self, body: dict):
        """{"image": base64 JPEG, "prompt": "banknote", "threshold": 0.5} -> pixel boxes."""
        from fastapi import HTTPException

        from modal_sam import detect

        started = time.perf_counter()
        try:
            data, prompt, threshold = detect.parse_request(body)
            picture = _open(data)
        except detect.BadRequest as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        run = self._sam3 if SAM_MODEL == "sam3" else self._sam31
        found = run(picture, prompt, threshold)
        return {
            "model": SAM_MODEL,
            "prompt": prompt,
            "width": picture.width,
            "height": picture.height,
            "detections": found,
            "ms": int((time.perf_counter() - started) * 1000),
        }
