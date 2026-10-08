"""
SAIV Face Recognition & Risk Service - Module 3

Face enrollment, verification, liveness detection, and risk scoring.

Privacy Requirements:
- NO raw face images should be stored
- Process images in-memory only
- Store only non-reversible hashes of face embeddings

Libraries:
- MediaPipe: Face detection and 468-landmark face mesh
- OpenCV: Image processing
- Pillow: Image loading from base64
- NumPy: Numerical operations
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class FaceEnrollRequest(BaseModel):
    """Request model for face enrollment."""
    user_id: str
    image: str  # Base64 encoded image
    camera_consent: bool = False


class FaceEnrollResponse(BaseModel):
    """Response model for face enrollment."""
    enrollment_successful: bool
    face_template_hash: str  # 64-char hex, non-reversible
    quality_score: float  # 0.0 to 1.0
    details: Dict[str, Any]


class FaceVerifyRequest(BaseModel):
    """Request model for face verification."""
    image: str  # Base64 encoded image
    reference_template_hash: str  # Hash from enrollment


class FaceVerifyResponse(BaseModel):
    """Response model for face verification."""
    match_passed: bool
    match_score: float  # 0.0 to 1.0
    match_threshold: float  # Default: 0.88
    face_detected: bool
    current_template_hash: str


class LivenessChallengeResponse(BaseModel):
    """Response model for liveness challenge issuance."""
    challenge_id: str
    challenge_type: str
    expires_in: int


class LivenessRequest(BaseModel):
    """Request model for liveness check."""
    challenge_response: Optional[str] = None  # Single-frame path
    challenge_type: str = "blink"              # blink, head_turn, mouth_open, passive
    challenge_id: Optional[str] = None         # When provided, server validates via Redis
    frames: Optional[List[str]] = None         # Multi-frame sequence for temporal liveness


class LivenessResponse(BaseModel):
    """Response model for liveness check."""
    liveness_passed: bool
    liveness_score: float  # 0.0 to 1.0
    liveness_threshold: float  # Default: 0.60
    challenge_type: str
    face_embedding_hash: str
    details: Dict[str, Any]


class GeolocationData(BaseModel):
    """Geolocation data for risk assessment."""
    latitude: float
    longitude: float
    accuracy: Optional[float] = None


class RiskAssessRequest(BaseModel):
    """Request model for risk assessment."""
    liveness_score: Optional[float] = None
    face_match_score: Optional[float] = None
    device_signature: Optional[str] = None
    device_public_key: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    geolocation: Optional[GeolocationData] = None


class RiskAssessResponse(BaseModel):
    """Response model for risk assessment."""
    risk_score: float  # 0.0 to 1.0
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL
    pass_threshold: bool
    risk_threshold: float  # Default: 0.50
    signal_breakdown: Dict[str, float]
    recommendations: List[str]


# =============================================================================
# INFRASTRUCTURE: REDIS AND OBSERVABILITY
# =============================================================================

def _connect_redis():
    """Probe Redis at startup. Without it the service runs in degraded mode."""
    try:
        client = redis_lib.from_url(
            os.getenv("REDIS_URL", "redis://redis:6379"),
            decode_responses=True,
            socket_connect_timeout=2,
        )
        client.ping()
        return client
    except Exception as exc:
        logger.warning("Redis unavailable; challenge-response disabled: %s", exc)
        return None


_redis = _connect_redis()


def _init_observability(application: FastAPI) -> None:
    """
    Wire up OTLP tracing (if an endpoint is configured) and expose metrics
    in Prometheus format at /metrics.
    """
    tracer_provider = TracerProvider()
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if endpoint:
        try:
            tracer_provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
            )
        except Exception as exc:
            logger.warning("OTLP exporter disabled: %s", exc)
    trace.set_tracer_provider(tracer_provider)

    otel_metrics.set_meter_provider(
        MeterProvider(metric_readers=[PrometheusMetricReader()])
    )
    FastAPIInstrumentor.instrument_app(application, tracer_provider=tracer_provider)


# =============================================================================
# APP
# =============================================================================

app = FastAPI(
    title=Config.SERVICE_NAME,
    description="Face enrollment, verification, liveness detection, and risk scoring service",
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

recognizer = FaceRecognizer()
liveness = LivenessDetector()
risk = RiskEngine()

_init_observability(app)

_meter = otel_metrics.get_meter("saiv.face_recognition")
_checkin_attempts = _meter.create_counter(
    "checkin_attempts", description="Total liveness check-in attempts"
)
_checkin_success = _meter.create_counter(
    "checkin_success", description="Successful liveness checks"
)


def _record_liveness_metrics(passed: bool) -> None:
    _checkin_attempts.add(1)
    if passed:
        _checkin_success.add(1)


def _resolve_challenge(request: LivenessRequest) -> str:
    """
    Resolve the challenge type to score.

    When challenge_id is supplied, the server looks it up in Redis and
    consumes it via GETDEL so the client cannot swap in a different action.
    Without a challenge_id we fall back to the request's challenge_type.
    """
    if not request.challenge_id:
        return request.challenge_type

    if _redis is None:
        raise HTTPException(
            status_code=503,
            detail="Challenge-response unavailable: Redis not connected",
        )

    try:
        stored = _redis.getdel(f"liveness:{request.challenge_id}")
    except redis_lib.RedisError as exc:
        logger.error("Redis error during challenge lookup: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Challenge-response temporarily unavailable",
        )

    if not stored:
        raise HTTPException(
            status_code=400,
            detail="Challenge expired, already used, or invalid",
        )
    return stored


def _first_face_hash(frames: List) -> str:
    """Template of the first frame containing a detectable face."""
    for frame in frames:
        detection = recognizer.locate_face(frame)
        if detection["detected"]:
            return recognizer.to_simhash(
                recognizer.encode_face(frame, detection["bbox"])
            )
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
# HEALTH & ROOT ENDPOINTS
# =============================================================================

@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "service": Config.SERVICE_NAME}


@app.get("/")
async def root():
    """List available endpoints."""
    return {
        "service": Config.SERVICE_NAME,
        "version": __version__,
        "endpoints": [
            "GET /health - Health check",
            "POST /face/enroll - Enroll a face for verification",
            "POST /face/verify - Verify a face against enrolled template",
            "POST /face/match - Legacy face matching (use /face/verify)",
            "GET /liveness/challenge - Issue a one-time challenge nonce",
            "POST /liveness/check - Perform liveness detection",
            "POST /risk/assess - Multi-signal risk assessment",
            "GET /metrics - Prometheus metrics",
        ],
    }


@app.get("/metrics", include_in_schema=False)
async def metrics():
    """Prometheus scrape endpoint."""
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


# =============================================================================
# FACE ENROLLMENT ENDPOINT (REQUIRED - 4 points in public tests)
# =============================================================================

@app.post("/face/enroll", response_model=FaceEnrollResponse, status_code=201)
async def enroll_face(request: FaceEnrollRequest):
    """
    Enroll a user's face for future verification.

    1. Validate camera_consent is True (return 400 if False)
    2. Decode base64 image to numpy array
    3. Detect face using MediaPipe FaceDetection
    4. If no face detected, return 400 with "No face detected"
    5. Extract face features/embedding
    6. Generate non-reversible hash of embedding (64 hex chars)
    7. Calculate quality score based on face detection confidence
    8. Return enrollment response

    Success Criteria:
    - Face detected with confidence >= 0.7
    - Returns 64-char hex hash
    """
    if not request.camera_consent:
        raise HTTPException(status_code=400, detail="Camera consent required")

    try:
        image = decode_base64_image(request.image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    detection = recognizer.locate_face(image)
    if not detection["detected"]:
        raise HTTPException(status_code=400, detail="No face detected")

    template = recognizer.to_simhash(
        recognizer.encode_face(image, detection["bbox"])
    )
    logger.info(
        "enrolled user_id=%s confidence=%.2f",
        request.user_id,
        detection["confidence"],
    )

    return FaceEnrollResponse(
        enrollment_successful=True,
        face_template_hash=template,
        quality_score=detection["confidence"],
        details={
            "face_detected": True,
            "face_detection_confidence": detection["confidence"],
            "image_quality": (
                "good"
                if detection["confidence"] >= Config.FACE_DETECTION_GOOD_CONFIDENCE
                else "moderate"
            ),
        },
    )


# =============================================================================
# FACE VERIFICATION ENDPOINT (REQUIRED - 4 points in public tests)
# =============================================================================

@app.post("/face/verify", response_model=FaceVerifyResponse)
async def verify_face(request: FaceVerifyRequest):
    """
    Verify a face against an enrolled template.

    1. Decode base64 image to numpy array
    2. Detect face using MediaPipe FaceDetection
    3. If no face detected, return with face_detected=False
    4. Extract face features/embedding
    5. Generate a non-reversible hash of the current face
    6. Compare using SimHash Hamming similarity
    7. match_passed = (match_score >= threshold)

    Note: The similarity metric is Hamming similarity over a 256-bit
    SimHash template, so the score is continuous rather than binary.
    """
    try:
        image = decode_base64_image(request.image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    detection = recognizer.locate_face(image)
    if not detection["detected"]:
        return FaceVerifyResponse(
            match_passed=False,
            match_score=0.0,
            match_threshold=Config.FACE_MATCH_THRESHOLD,
            face_detected=False,
            current_template_hash="",
        )

    current = recognizer.to_simhash(
        recognizer.encode_face(image, detection["bbox"])
    )
    score = recognizer.hamming_similarity(current, request.reference_template_hash)
    passed = score >= Config.FACE_MATCH_THRESHOLD

    logger.info("verify match=%s score=%.4f", passed, score)

    return FaceVerifyResponse(
        match_passed=passed,
        match_score=score,
        match_threshold=Config.FACE_MATCH_THRESHOLD,
        face_detected=True,
        current_template_hash=current,
    )


@app.post("/face/match")
async def match_face(request: FaceVerifyRequest):
    """
    Legacy face matching endpoint. Redirects to /face/verify.
    Kept for backwards compatibility.
    """
    return await verify_face(request)


# =============================================================================
# LIVENESS DETECTION ENDPOINT (REQUIRED - partial; BONUS for advanced)
# =============================================================================

@app.get("/liveness/challenge", response_model=LivenessChallengeResponse)
async def issue_liveness_challenge():
    """
    Issue a one-time challenge nonce stored in Redis with a TTL.

    The server picks the challenge type so the client cannot pre-prepare
    a matching pose. Redis is required here; without it the subsequent
    /liveness/check could never validate the nonce, so we fail loudly.
    """
    if _redis is None:
        raise HTTPException(
            status_code=503,
            detail="Challenge-response unavailable: Redis not connected",
        )

    challenge_id = secrets.token_hex(16)
    challenge_type = secrets.choice(Config.CHALLENGE_TYPES)
    _redis.setex(
        f"liveness:{challenge_id}", Config.CHALLENGE_TTL_SECONDS, challenge_type
    )

    return LivenessChallengeResponse(
        challenge_id=challenge_id,
        challenge_type=challenge_type,
        expires_in=Config.CHALLENGE_TTL_SECONDS,
    )


@app.post("/liveness/check", response_model=LivenessResponse)
async def check_liveness(request: LivenessRequest):
    """
    Perform liveness detection on submitted image(s).

    Challenge Types:
    - "passive": No user action required (depth/texture analysis)
    - "blink": Detect eye blink (compare eye aspect ratios)
    - "head_turn": Detect head rotation (face mesh landmarks)
    - "mouth_open": Detect mouth opening (mouth aspect ratio)

    Multi-frame submissions (5-45 frames) use temporal analysis so the
    requested action must actually occur across the sequence.

    Depth Analysis:
    - MediaPipe FaceMesh gives 3D landmarks
    - nose_tip_z (landmark 1, z-coordinate) indicates depth
    - Real faces: |nose_tip_z| > 0.03 (significant depth)
    - Flat images: |nose_tip_z| < 0.01 (minimal depth)
    """
    challenge = _resolve_challenge(request)

    if request.frames:
        if len(request.frames) < Config.SEQUENCE_MIN_FRAMES:
            raise HTTPException(
                status_code=400,
                detail=f"At least {Config.SEQUENCE_MIN_FRAMES} frames required",
            )
        try:
            frames = [
                decode_base64_image(f)
                for f in request.frames[: Config.SEQUENCE_MAX_FRAMES]
            ]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        result = liveness.score_sequence(frames, challenge)
        _record_liveness_metrics(result["liveness_passed"])
        return _to_liveness_response(result, _first_face_hash(frames))

    if not request.challenge_response:
        raise HTTPException(
            status_code=400,
            detail="challenge_response is required when frames is not provided",
        )

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
    face_hash = recognizer.to_simhash(
        recognizer.encode_face(image, detection["bbox"])
    )
    _record_liveness_metrics(result["liveness_passed"])
    return _to_liveness_response(result, face_hash)


# =============================================================================
# RISK ASSESSMENT ENDPOINT (REQUIRED - 3 points in public tests)
# =============================================================================

@app.post("/risk/assess", response_model=RiskAssessResponse)
async def assess_risk(request: RiskAssessRequest):
    """
    Perform multi-signal risk assessment.

    Weighted fusion:
    - Liveness: 25%
    - Face match: 25%
    - Device attestation: 20%
    - Network/VPN: 15%
    - Geolocation: 15%

    Risk levels:
    - LOW: risk_score < 0.3
    - MEDIUM: 0.3 <= risk_score < 0.5
    - HIGH: 0.5 <= risk_score < 0.7
    - CRITICAL: risk_score >= 0.7

    VPN/Proxy Detection:
    - Private IP ranges: 10.x.x.x, 172.16-31.x.x, 192.168.x.x
    - Check user_agent for VPN indicators
    - High geolocation accuracy (< 10m) might be spoofed
    - Very low accuracy (> 5000m) indicates issues
    """
    result = risk.evaluate(request.model_dump())
    return RiskAssessResponse(**result)


# =============================================================================
# PRIVACY REQUIREMENTS (IMPORTANT!)
# =============================================================================
"""
This implementation MUST follow these privacy requirements:

1. NO RAW IMAGES STORED
   - Process images in-memory only
   - Do not write images to disk
   - Do not send images to external APIs

2. HASH-ONLY STORAGE
   - Store only non-reversible hashes (64 hex characters)
   - Hashes are one-way - cannot reconstruct the face
   - Different faces must produce different hashes

3. EPHEMERAL PROCESSING
   - Clear image data after processing
   - No caching of raw biometric data
   - Use Python's memory management (del, gc.collect)

4. CONSENT TRACKING
   - Require camera_consent=True for enrollment
   - Log consent in audit trail (backend responsibility)

5. RESPONSE HYGIENE
   - Never include base64 image data in responses
   - Only return hashes, scores, and metadata
"""