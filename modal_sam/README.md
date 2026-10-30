# SAM on Modal

With `SAM_PROVIDER=modal`, the backend sends each scan's photo here: one photo and a text prompt in, note boxes out. The default provider is Roboflow's hosted SAM 3, and `off` skips SAM.

## Models

Pick one with `SAM_MODEL` when you deploy:

| `SAM_MODEL` | Weights | How it runs |
|---|---|---|
| `sam3.1` (default) | `facebook/sam3.1` | The SAM 3.1 predictor. The photo is a one-frame video, and the prompt goes on frame 0. |
| `sam3` | `facebook/sam3` | The SAM 3 image model (`Sam3Processor`). |

Both Hugging Face repos are gated. Request access with the account whose token you use. SAM 3.1's own examples are video only, so our one-frame route is not an official recipe. Before choosing, run both on the dev set and compare.

## Deploy

1. Install the client and log in: `pip install modal`, then `modal setup`.
2. GPUs need a payment method on the Modal account. The Starter plan includes $30 a month of credit.
3. Store the Hugging Face token as a Modal secret. Type it in your own terminal, never in chat or Slack:
   ```bash
   modal secret create birr-hf HF_TOKEN=<your token>
   ```
4. Deploy from the repo root. Modal prints the URL of `Sam.segment`:
   ```bash
   modal deploy -m modal_sam.app
   ```
   Options, set in the same command: `SAM_MODEL=sam3`, `SAM_GPU=A10` (default `L4`), and `SAM_MIN_CONTAINERS=1`. The last one keeps a GPU warm, and you pay for it while idle, so use it only during a demo.
5. Make a token pair for the backend. Modal shows the secret only once:
   ```bash
   modal workspace proxy-tokens create --name birr-backend
   ```
6. In the backend's `.env`, set `SAM_PROVIDER=modal`, `SAM_MODAL_URL` (from step 4), `SAM_MODAL_KEY` (`wk-…`) and `SAM_MODAL_SECRET` (`ws-…`).

## Test

Use your own test photo. Pre-event photos never go in the repo.
```bash
curl -s -X POST "$SAM_MODAL_URL" \
  -H "Modal-Key: $SAM_MODAL_KEY" -H "Modal-Secret: $SAM_MODAL_SECRET" \
  -H "Content-Type: application/json" \
  -d "{\"image\": \"$(base64 -w0 photo.jpg)\", \"prompt\": \"banknote\"}"
```

## Request and response

Request: `{"image": "<base64 JPEG or PNG>", "prompt": "banknote", "threshold": 0.5}`. `prompt` and `threshold` are optional.

Response:
```json
{"model": "sam3.1", "prompt": "banknote", "width": 768, "height": 576,
 "detections": [{"box": [12.0, 40.5, 380.0, 300.2], "score": 0.91}], "ms": 640}
```
`box` is `[x0, y0, x1, y1]` in pixels of the photo sent, best score first. A request without the token pair gets `401`. A bad image or field gets `400`.

## Cost and cold starts

- An L4 lists at $0.000222 a second (about $0.80 an hour) while a container runs. A container stops 5 minutes after its last request, and at most one runs.
- The first start downloads the weights (about 3.5 GB) into the `birr-sam-hf-cache` volume. Later cold starts load them from there.
- A cold start takes longer than the backend's `SAM_MODAL_TIMEOUT_S` (25 s). That scan goes on without SAM, which only advises. Send one warm-up request before a demo.

## Status

- Checked here: the app definition loads with the Modal client (1.6.3), and the request and box helpers have tests (`tests/test_modal_sam.py`).
- Not checked: no GPU deploy has run yet. The SAM calls follow the `facebookresearch/sam3` source at commit `f1647e8`. Confirm the first deploy with the curl test above.

SAM code and weights are under the SAM License. See `docs/licenses.md`.
