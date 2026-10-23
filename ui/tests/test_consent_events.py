"""A consent request has to reach the person, and carry nothing else."""

import pytest

from server.models import clean_event


def _clean(data):
    return clean_event("consent_required", data, lambda value: value)


def test_a_consent_request_survives_intact():
    """Redacting the URL would break the only thing the person has to click."""
    url = "https://accounts.google.com/o/oauth2/v2/auth?client_id=abc&state=xyz"
    assert _clean({"provider": "google_drive", "label": "Google Drive", "auth_url": url}) == {
        "provider": "google_drive", "label": "Google Drive", "auth_url": url,
    }


def test_a_non_https_destination_is_refused():
    with pytest.raises(ValueError):
        _clean({"provider": "slack", "label": "Slack", "auth_url": "http://accounts.google.com/x"})


def test_a_javascript_url_is_refused():
    with pytest.raises(ValueError):
        _clean({"provider": "slack", "label": "Slack", "auth_url": "javascript:alert(1)"})


def test_extra_fields_are_refused():
    """Nothing rides along with a consent link; the vault holds the secrets."""
    with pytest.raises(ValueError):
        _clean({
            "provider": "slack",
            "label": "Slack",
            "auth_url": "https://slack.com/oauth",
            "access_token": "xoxb-leaked",
        })


def test_a_missing_url_is_refused():
    with pytest.raises(ValueError):
        _clean({"provider": "slack", "label": "Slack"})


def test_a_missing_provider_is_refused():
    with pytest.raises(ValueError):
        _clean({"label": "Slack", "auth_url": "https://slack.com/oauth"})
