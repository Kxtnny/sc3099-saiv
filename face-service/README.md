# Module 3 — Face Recognition & Risk Service

Privacy-preserving face recognition and multi-signal risk scoring for the
SAIV attendance system.

## Package layout

| Package | Contents |
|---|---|
| `app.vision`   | Face detection, dlib embedding, SimHash templates, MediaPipe landmarks, image decode |
| `app.liveness` | 4-component liveness scoring + active challenge detection |
| `app.risk`     | Weighted multi-signal risk fusion |
| `app.support`  | VPN / proxy heuristics |
| `app.config`   | All thresholds and weights |
| `app.main`     | FastAPI application, schemas, and routes |

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET  | `/health`             | Liveness probe |
| GET  | `/metrics`            | Prometheus scrape |
| POST | `/face/enroll`        | Enrol a face → 64-char template |
| POST | `/face/verify`        | Verify against a stored template |
| POST | `/face/match`         | Legacy alias for verify |
| GET  | `/liveness/challenge` | Issue a one-time challenge nonce |
| POST | `/liveness/check`     | Score a single or multi-frame submission |
| POST | `/risk/assess`        | Weighted multi-signal risk fusion |

## Quick start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001