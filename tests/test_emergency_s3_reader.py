"""Unit tests for issue #334 - S3 dataset loader with caching and zero-downtime fallback."""
import hashlib
import io
import json
import sys
from unittest import mock
import pytest

pytestmark = pytest.mark.unit

# Ensure boto3 and botocore are mockable in test environments where not pre-installed
if "boto3" not in sys.modules:
    mock_boto3 = mock.MagicMock()
    mock_botocore = mock.MagicMock()
    sys.modules["boto3"] = mock_boto3
    sys.modules["botocore"] = mock_botocore
    sys.modules["botocore.config"] = mock_botocore.config

try:
    from botocore.exceptions import ClientError
except (ImportError, AttributeError):
    class ClientError(Exception):
        def __init__(self, error_response=None, operation_name=None):
            super().__init__(str(error_response))
            self.response = error_response or {}

import services.emergency as em


@pytest.fixture(autouse=True)
def reset_cache():
    """Ensure cache is clean before and after each test."""
    em._emergency_numbers_cache = None
    yield
    em._emergency_numbers_cache = None


def test_load_emergency_numbers_from_s3_success():
    """Verify that when S3 returns a valid JSON, it is loaded into the cache."""
    mock_payload = {
        "IN": {
            "default": {
                "general_emergency": "112",
                "police": "112",
                "ambulance": "108",
                "fire": "101",
            },
            "states": {},
        }
    }
    mock_body = io.BytesIO(json.dumps(mock_payload).encode("utf-8"))

    mock_s3 = mock.MagicMock()
    mock_s3.get_object.return_value = {"Body": mock_body}

    with mock.patch("boto3.client", return_value=mock_s3):
        data = em._load_emergency_numbers()
        assert "IN" in data
        assert data["IN"]["default"]["police"] == "112"
        assert mock_s3.get_object.call_count == 1


def test_warm_container_caching_avoids_repeated_s3_calls():
    """Verify that once loaded, subsequent invocations read from the in-memory cache."""
    mock_payload = {"US": {"default": {"general_emergency": "911"}, "states": {}}}
    mock_body = io.BytesIO(json.dumps(mock_payload).encode("utf-8"))

    mock_s3 = mock.MagicMock()
    mock_s3.get_object.return_value = {"Body": mock_body}

    with mock.patch("boto3.client", return_value=mock_s3):
        # First call hits S3
        data1 = em._load_emergency_numbers()
        # Second call must hit cache
        data2 = em._load_emergency_numbers()

        assert data1 == data2
        assert mock_s3.get_object.call_count == 1


def test_fallback_to_local_file_on_s3_error():
    """When S3 returns an error (e.g. AccessDenied, timeout), fall back to local file."""
    mock_s3 = mock.MagicMock()
    mock_s3.get_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
        "GetObject",
    )

    with mock.patch("boto3.client", return_value=mock_s3):
        data = em._load_emergency_numbers()
        assert data is not None
        assert "US" in data
        assert "IN" in data
        # Check that warning was printed and local fallback was used
        assert mock_s3.get_object.call_count == 1


def test_custom_environment_variables_for_bucket_and_key(monkeypatch):
    """Verify that environment variables control S3 bucket and key."""
    monkeypatch.setenv("EMERGENCY_CONTACTS_S3_BUCKET", "custom-bucket")
    monkeypatch.setenv("EMERGENCY_CONTACTS_S3_KEY", "custom/path.json")

    # Re-evaluate module-level defaults
    monkeypatch.setattr(em, "S3_BUCKET", "custom-bucket")
    monkeypatch.setattr(em, "S3_KEY", "custom/path.json")

    mock_payload = {"AU": {"default": {"general_emergency": "000"}, "states": {}}}
    mock_body = io.BytesIO(json.dumps(mock_payload).encode("utf-8"))

    mock_s3 = mock.MagicMock()
    mock_s3.get_object.return_value = {"Body": mock_body}

    with mock.patch("boto3.client", return_value=mock_s3):
        em._load_emergency_numbers()
        mock_s3.get_object.assert_called_once_with(
            Bucket="custom-bucket", Key="custom/path.json"
        )


def test_runtime_error_when_both_s3_and_local_file_unavailable(monkeypatch):
    """When both S3 and local file are absent, raise RuntimeError."""
    mock_s3 = mock.MagicMock()
    mock_s3.get_object.side_effect = Exception("S3 down")
    monkeypatch.setattr(em, "DATA_FILE", "/nonexistent/path/emergency_numbers.json")
    with mock.patch("boto3.client", return_value=mock_s3):
        with pytest.raises(RuntimeError):
            em._load_emergency_numbers()


def test_location_resolution_with_mocked_reverse_geocode():
    """Verify reverse geocoding path when lat and lng are provided."""
    resolver = em.LocationResolver(client_ip=None)
    with mock.patch.object(resolver, "_reverse_geocode", return_value={"country": "FR", "city": "Paris"}):
        loc = resolver.resolve({"lat": "48.8566", "lng": "2.3522"}, {})
        assert loc.get("country") == "FR"
        assert loc.get("city") == "Paris"


def test_location_resolution_with_mocked_geocode_place():
    """Verify geocode place path when city/state/zip is provided without lat/lng."""
    resolver = em.LocationResolver(client_ip=None)
    with mock.patch.object(resolver, "_geocode_place", return_value={"country": "DE", "city": "Berlin"}):
        loc = resolver.resolve({"city": "Berlin"}, {})
        assert loc.get("country") == "DE"


def test_location_resolution_with_mocked_ip_lookup():
    """Verify fallback to client IP location when coordinate/place fields are absent."""
    resolver = em.LocationResolver(client_ip="8.8.8.8")
    with mock.patch.object(resolver, "_get_location_from_ip", return_value={"country": "JP", "city": "Tokyo"}):
        loc = resolver.resolve({}, {})
        assert loc.get("country") == "JP"
        assert loc.get("city") == "Tokyo"


def test_location_resolution_inferred_city():
    """Verify city inference when city exists and no country was resolved."""
    resolver = em.LocationResolver(client_ip=None)
    with mock.patch.object(resolver, "_infer_state_country_from_city", return_value={"country": "IT", "state": "Lazio"}):
        loc = resolver.resolve({"city": "Rome"}, {})
        assert loc.get("country") == "IT"


def _local_dataset():
    with open(em.DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def test_s3_client_makes_one_attempt_that_fits_the_lambda_timeout():
    """An unreachable S3 must fail over well inside the 3 s function timeout.

    botocore's legacy `max_attempts` counts retries, not attempts, so
    `max_attempts: 1` made two attempts; two 1.5 s connect timeouts outlasted
    the function and the fallback never ran. `total_max_attempts` counts the
    first call too.
    """
    mock_s3 = mock.MagicMock()
    mock_s3.get_object.side_effect = Exception("unreachable")

    with mock.patch("boto3.client", return_value=mock_s3) as make_client:
        em._load_emergency_numbers()

    config = make_client.call_args.kwargs["config"]
    assert config.retries["total_max_attempts"] == 1
    assert config.connect_timeout + config.read_timeout <= 2


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        "a bare string",
        {"us": {"default": {"police": "911"}, "states": {}}},
        {"US": "911"},
        {"US": {"default": ["911"], "states": {}}},
    ],
    ids=["list", "empty-object", "string", "lowercase-code", "record-not-object", "default-not-object"],
)
def test_misshapen_s3_object_falls_back_to_the_bundled_file(payload):
    """Valid JSON of the wrong shape is treated like an unreadable object.

    Caching it would answer every request in the container with a 500 (`[]`)
    or a 404 (`{}`) until the container recycled.
    """
    mock_s3 = mock.MagicMock()
    mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(payload).encode("utf-8"))}

    with mock.patch("boto3.client", return_value=mock_s3):
        data = em._load_emergency_numbers()

    assert data == _local_dataset()


def test_s3_load_logs_its_source_and_checksum(capsys):
    """CloudWatch must show that S3 answered, and which upload it served.

    The bundled file is a byte-identical copy of the S3 object, so the numbers
    alone cannot tell the two apart.
    """
    raw = json.dumps({"IN": {"default": {"police": "112"}, "states": {}}}).encode("utf-8")
    mock_s3 = mock.MagicMock()
    mock_s3.get_object.return_value = {"Body": io.BytesIO(raw)}

    with mock.patch("boto3.client", return_value=mock_s3):
        em._load_emergency_numbers()

    logged = capsys.readouterr().out
    assert f"INFO: Loaded emergency numbers from s3://{em.S3_BUCKET}/{em.S3_KEY}" in logged
    assert f"sha256={hashlib.sha256(raw).hexdigest()}" in logged


def test_fallback_logs_that_the_bundled_file_answered(capsys):
    mock_s3 = mock.MagicMock()
    mock_s3.get_object.side_effect = Exception("S3 down")

    with mock.patch("boto3.client", return_value=mock_s3):
        em._load_emergency_numbers()

    logged = capsys.readouterr().out
    with open(em.DATA_FILE, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    assert "WARN: Could not fetch emergency numbers" in logged
    assert "INFO: Loaded emergency numbers from the bundled file (" in logged
    assert f"sha256={digest}" in logged
