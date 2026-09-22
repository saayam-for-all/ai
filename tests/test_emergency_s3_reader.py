import io
import json
import sys
from unittest import mock
import pytest

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
