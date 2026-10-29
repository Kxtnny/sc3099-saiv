"""
SAIV Face Recognition & Risk Service - Module 3
"""

import logging
import os
import secrets
from typing import Any, Dict, List, Optional

import redis as redis_lib
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from opentelemetry import metrics as otel_metrics
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from pydantic import BaseModel

from app import __version__
from app.config import Config
from app.liveness.detector import LivenessDetector
from app.risk.engine import RiskEngine
from app.vision.imaging import decode_base64_image
from app.vision.recognizer import FaceRecognizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class FaceEnrollRequest(BaseModel):
    user_id: str
    image: str
    camera_consent: bool = False

class FaceEnrollResponse(BaseModel):
    enrollment_successful: bool
    face_template_hash: str
    quality_score: float
    details: Dict[str, Any]

class FaceVerifyRequest(BaseModel):
    image: str
    reference_template_hash: str

class FaceVerifyResponse(BaseModel):
    match_passed: bool
    match_score: float
    match_threshold: float
    face_detected: bool
    current_template_hash: str

class LivenessChallengeResponse(BaseModel):
    challenge_id: str
    challenge_type: str
    expires_in: int

class LivenessRequest(BaseModel):
    challenge_response: Optional[str] = None
    challenge_type: str = "blink"
    challenge_id: Optional[str] = None
    frames: Optional[List[str]] = None

class LivenessResponse(BaseModel):
    liveness_passed: bool
    liveness_score: float
    liveness_threshold: float
    challenge_type: str
    face_embedding_hash: str
    details: Dict[str, Any]

class GeolocationData(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None

class RiskAssessRequest(BaseModel):
    liveness_score: Optional[float] = None
    face_match_score: Optional[float] = None
    device_signature: Optional[str] = None
    device_public_key: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    geolocation: Optional[GeolocationData] = None

class RiskAssessResponse(BaseModel):
    risk_score: float
    risk_level: str
    pass_threshold: bool
    risk_threshold: float
    signal_breakdown: Dict[str, float]
    recommendations: List[str]


# =============================================================================
# INFRASTRUCTURE
# =============================================================================

def _connect_redis():
    try:
        client = redis_lib.from_url(os.getenv("REDIS_URL", "redis://redis:6379"), decode_responses=True, socket_connect_timeout=2)
        client.ping()
        return client
    except Exception as exc:
        logger.warning("Redis unavailable; challenge-response disabled: %s", exc)
        return None

_redis = _connect_redis()

def _init_observability(application: FastAPI) -> None:
    tracer_provider = TracerProvider()
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if endpoint:
        try:
            tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        except Exception as exc:
            logger.warning("OTLP exporter disabled: %s", exc)
    trace.set_tracer_provider(tracer_provider)
    otel_metrics.set_meter_provider(MeterProvider(metric_readers=[PrometheusMetricReader()]))
    FastAPIInstrumentor.instrument_app(application, tracer_provider=tracer_provider)


# =============================================================================
# APP
# =============================================================================

app = FastAPI(title=Config.SERVICE_NAME, version=__version__)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

recognizer = FaceRecognizer()
recognizer.warm_up()
liveness = LivenessDetector()
risk = RiskEngine()

_init_observability(app)

_meter = otel_metrics.get_meter("saiv.face_recognition")
_checkin_attempts = _meter.create_counter("checkin_attempts", description="Total liveness check-in attempts")
_checkin_success = _meter.create_counter("checkin_success", description="Successful liveness checks")


def _record_liveness_metrics(passed: bool) -> None:
    _checkin_attempts.add(1)
    if passed:
        _checkin_success.add(1)


def _resolve_challenge(request: LivenessRequest) -> str:
    if not request.challenge_id:
        return request.challenge_type
    if _redis is None:
        raise HTTPException(status_code=503, detail="Challenge-response unavailable: Redis not connected")
    try:
        stored = _redis.getdel(f"liveness:{request.challenge_id}")
    except redis_lib.RedisError as exc:
        logger.error("Redis error during challenge lookup: %s", exc)
        raise HTTPException(status_code=503, detail="Challenge-response temporarily unavailable")
    if not stored:
        raise HTTPException(status_code=400, detail="Challenge expired, already used, or invalid")
    return stored


def _first_face_hash(frames: List) -> str:
    # Limit to first 3 frames to protect the 1.5s backend timeout
    for frame in frames[:3]:
        detection = recognizer.locate_face(frame)
        if detection["detected"]:
            embedding = recognizer.encode_face(frame, detection["bbox"])
            return recognizer.to_simhash(embedding) if embedding is not None else ""
    return ""


def _to_liveness_response(result: dict, face_hash: str) -> LivenessResponse:
    return LivenessResponse(
        liveness_passed=result["liveness_passed"],
        liveness_score=result["liveness_score"],
        liveness_threshold=Config.LIVENESS_THRESHOLD,
        challenge_type=result["challenge_type"],
        face_embedding_hash=face_hash,
        details=result["details"],
    )


# =============================================================================
# ROUTES
# =============================================================================

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": Config.SERVICE_NAME}

@app.get("/")
def root():
    return {
        "service": Config.SERVICE_NAME,
        "version": __version__,
        "endpoints": [
            "/health", "/face/enroll", "/face/verify", "/face/match",
            "/liveness/challenge", "/liveness/check", "/risk/assess", "/metrics"
        ],
    }

@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.post("/face/enroll", response_model=FaceEnrollResponse, status_code=201)
def enroll_face(request: FaceEnrollRequest):
    if not request.camera_consent:
        raise HTTPException(status_code=400, detail="Camera consent required")
    try:
        image = decode_base64_image(request.image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    detection = recognizer.locate_face(image)
    if not detection["detected"]:
        raise HTTPException(status_code=400, detail="No face detected")

    embedding = recognizer.encode_face(image, detection["bbox"])
    if embedding is None:
        raise HTTPException(status_code=400, detail="Could not extract face features; use a clear, front-facing photo")
    
    template = recognizer.to_simhash(embedding)
    
    return FaceEnrollResponse(
        enrollment_successful=True,
        face_template_hash=template,
        quality_score=detection["confidence"],
        details={
            "face_detected": True,
            "face_detection_confidence": detection["confidence"],
            "image_quality": ("good" if detection["confidence"] >= Config.FACE_DETECTION_GOOD_CONFIDENCE else "moderate"),
        },
    )


@app.post("/face/verify", response_model=FaceVerifyResponse)
def verify_face(request: FaceVerifyRequest):
    try:
        image = decode_base64_image(request.image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    detection = recognizer.locate_face(image)
    if not detection["detected"]:
        return FaceVerifyResponse(match_passed=False, match_score=0.0, match_threshold=Config.FACE_MATCH_THRESHOLD, face_detected=False, current_template_hash="")

    embedding = recognizer.encode_face(image, detection["bbox"])
    if embedding is None:
        return FaceVerifyResponse(match_passed=False, match_score=0.0, match_threshold=Config.FACE_MATCH_THRESHOLD, face_detected=True, current_template_hash="")

    current = recognizer.to_simhash(embedding)
    score = recognizer.hamming_similarity(current, request.reference_template_hash)
    
    return FaceVerifyResponse(
        match_passed=(score >= Config.FACE_MATCH_THRESHOLD),
        match_score=score,
        match_threshold=Config.FACE_MATCH_THRESHOLD,
        face_detected=True,
        current_template_hash=current,
    )


@app.post("/face/match")
def match_face(request: FaceVerifyRequest):
    return verify_face(request)


@app.get("/liveness/challenge", response_model=LivenessChallengeResponse)
def issue_liveness_challenge():
    if _redis is None:
        raise HTTPException(status_code=503, detail="Challenge-response unavailable: Redis not connected")
    challenge_id = secrets.token_hex(16)
    challenge_type = secrets.choice(Config.CHALLENGE_TYPES)
    _redis.setex(f"liveness:{challenge_id}", Config.CHALLENGE_TTL_SECONDS, challenge_type)
    return LivenessChallengeResponse(challenge_id=challenge_id, challenge_type=challenge_type, expires_in=Config.CHALLENGE_TTL_SECONDS)


@app.post("/liveness/check", response_model=LivenessResponse)
def check_liveness(request: LivenessRequest):
    challenge = _resolve_challenge(request)

    if request.frames:
        if len(request.frames) < Config.SEQUENCE_MIN_FRAMES:
            raise HTTPException(status_code=400, detail=f"At least {Config.SEQUENCE_MIN_FRAMES} frames required")
        try:
            frames = [decode_base64_image(f) for f in request.frames[: Config.SEQUENCE_MAX_FRAMES]]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        result = liveness.score_sequence(frames, challenge)
        _record_liveness_metrics(result["liveness_passed"])
        return _to_liveness_response(result, _first_face_hash(frames))

    if not request.challenge_response:
        raise HTTPException(status_code=400, detail="challenge_response is required when frames is not provided")

    try:
        image = decode_base64_image(request.challenge_response)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    detection = recognizer.locate_face(image)
    if not detection["detected"]:
        _record_liveness_metrics(False)
        result = LivenessDetector._failed(challenge, reason="no_face")
        return _to_liveness_response(result, "")

    result = liveness.score_single_frame(image, challenge)
    embedding = recognizer.encode_face(image, detection["bbox"])
    face_hash = recognizer.to_simhash(embedding) if embedding is not None else ""
    _record_liveness_metrics(result["liveness_passed"])
    return _to_liveness_response(result, face_hash)


@app.post("/risk/assess", response_model=RiskAssessResponse)
def assess_risk(request: RiskAssessRequest):
    result = risk.evaluate(request.model_dump())
    return RiskAssessResponse(**result)