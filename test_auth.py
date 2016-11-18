from oauth2client import client
from apiclient import discovery
import secrets.admin_secrets  # Per-machine secrets
SCOPES = 'https://www.googleapis.com/auth/calendar.readonly'
CLIENT_SECRET_FILE = secrets.admin_secrets.google_key_file  ## You'll need this
APPLICATION_NAME = 'CIS 322 project on ix:7680'

def valid_credentials():
    credentials = client.OAuth2Credentials.from_json(
        flask.session['credentials'])

    if (credentials.invalid or
        credentials.access_token_expired):
      return None
    return credentials
def test_credentials():
    assert  valid_credentials()
