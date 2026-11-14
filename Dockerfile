FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY release ./release
RUN python - <<'FETCH_IPA'
import hashlib,httpx
from pathlib import Path
url='https://ajg-shop-production.up.railway.app/downloads/AJG.ipa?v=50015'
expected='9a446af37098b8e7de5f933a77c56f21f59267462512817bf6494a81e4ac5b56'
with httpx.Client(timeout=120,follow_redirects=True)as client:
 response=client.get(url);response.raise_for_status();data=response.content
 assert len(data)==43611324 and hashlib.sha256(data).hexdigest()==expected
 Path('release/AJG.ipa').write_bytes(data)
FETCH_IPA
ENV DATABASE_PATH=/data/ajg.sqlite3
CMD ["sh","-c","uvicorn app.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
