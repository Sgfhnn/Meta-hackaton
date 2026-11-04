uv venv -p 3.12 /data/home/asr-venv
uv pip install --python /data/home/asr-venv/bin/python omnilingual-asr 'torchaudio==2.8.0+cpu' --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match
uv pip install --python /data/home/asr-venv/bin/python --reinstall-package fairseq2n 'fairseq2n==0.6' --extra-index-url https://fair.pkg.atmeta.com/fairseq2/whl/pt2.8.0/cpu --index-strategy unsafe-best-match
uv pip install --python /data/home/asr-venv/bin/python 'pyarrow<18' av fastapi 'uvicorn[standard]' soundfile
