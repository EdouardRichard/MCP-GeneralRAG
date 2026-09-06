import pytest
from rag_mcp.parsers.credential_redactor import redact_credentials

class TestOpenAPICredentialRedaction:
    def test_api_key_redacted(self):
        text = 'api_key: sk-abc123def456ghi789jkl012mno345'
        result = redact_credentials(text)
        assert 'sk-abc123def456ghi789jkl012mno345' not in result
        assert '<api-key>' in result

    def test_authorization_token_redacted(self):
        text = 'authorization_token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c'
        result = redact_credentials(text)
        assert 'eyJhbGciOi' not in result
        assert '<token>' in result

    def test_field_name_preserved(self):
        text = 'api_key: sk-abc123def456ghi789jkl012mno345'
        result = redact_credentials(text)
        assert 'api_key' in result

class TestDDLCredentialRedaction:
    def test_password_redacted(self):
        text = "CREATE USER admin WITH PASSWORD = 'SuperSecret456';"
        result = redact_credentials(text)
        assert 'SuperSecret456' not in result
        assert '<password>' in result

    def test_field_name_preserved(self):
        text = 'password = MySecret123'
        result = redact_credentials(text)
        assert 'password' in result
        assert 'MySecret123' not in result

class TestPythonCredentialRedaction:
    def test_env_token_redacted(self):
        text = 'token = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N'
        result = redact_credentials(text)
        assert 'eyJhbGciOi' not in result
        assert '<token>' in result

    def test_secret_redacted(self):
        text = 'client_secret = abc123456789xyz'
        result = redact_credentials(text)
        assert 'abc123456789xyz' not in result
        assert '<secret>' in result

    def test_field_name_preserved(self):
        text = 'client_secret = abc123456789xyz'
        result = redact_credentials(text)
        assert 'client_secret' in result

# ---------------------------------------------------------------------------
# 008 (T014, FR-017): conversion-layer credential shapes — JSON/YAML values,
# CSV cells, EML header fields. Values are type-typed placeholders while the
# field name and surrounding structure (quotes/braces/header names) survive.
# ---------------------------------------------------------------------------

class TestJsonCredentialRedaction:
    def test_json_api_key_redacted(self):
        text = '{"api_key": "sk-abc123def456ghi789jkl012mno345"}'
        result = redact_credentials(text)
        assert 'sk-abc123def456ghi789jkl012mno345' not in result
        assert '<api-key>' in result

    def test_json_password_redacted(self):
        text = '{"password": "SuperSecret456"}'
        result = redact_credentials(text)
        assert 'SuperSecret456' not in result
        assert '<password>' in result

    def test_json_token_redacted(self):
        text = '{"token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop"}'
        result = redact_credentials(text)
        assert 'eyJhbGciOi' not in result
        assert '<token>' in result

    def test_json_field_name_and_structure_preserved(self):
        text = '{"api_key": "sk-abc123def456ghi789jkl012mno345", "host": "x"}'
        result = redact_credentials(text)
        assert '"api_key"' in result
        assert '"host": "x"' in result


class TestYamlCredentialRedaction:
    def test_yaml_api_key_redacted(self):
        text = 'api_key: sk-abc123def456ghi789jkl012mno345'
        result = redact_credentials(text)
        assert 'sk-abc123def456ghi789jkl012mno345' not in result
        assert '<api-key>' in result

    def test_yaml_password_redacted(self):
        text = 'password: SuperSecret456'
        result = redact_credentials(text)
        assert 'SuperSecret456' not in result
        assert '<password>' in result


class TestCsvCredentialRedaction:
    def test_csv_cell_value_redacted(self):
        text = 'name,note\nalpha,api_key=sk-abc123def456ghi789jkl012mno345'
        result = redact_credentials(text)
        assert 'sk-abc123def456ghi789jkl012mno345' not in result
        assert '<api-key>' in result


class TestEmlHeaderCredentialRedaction:
    def test_eml_subject_credential_redacted(self):
        text = 'Subject: password=SuperSecret456 review'
        result = redact_credentials(text)
        assert 'SuperSecret456' not in result
        assert '<password>' in result

    def test_eml_header_names_preserved(self):
        text = 'From: alice@example.com\nTo: bob@example.com\nSubject: Re: Review'
        result = redact_credentials(text)
        assert 'From: alice@example.com' in result
        assert 'To: bob@example.com' in result
        assert 'Subject: Re: Review' in result
