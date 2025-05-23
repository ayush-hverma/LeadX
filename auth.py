import os
import streamlit as st
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
import json
from pathlib import Path
from googleapiclient.discovery import build
import requests
import logging
import pickle
from google.auth.exceptions import RefreshError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# OAuth2 Configuration via environment variables (no client_secrets.json)
TOKEN_PICKLE_FILE = "token.pickle"
GOOGLE_TOKEN_PICKLE_FILE = "google_token.pkl"
SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/gmail.send'
]

# Replace os.getenv calls with st.secrets for Google OAuth2 variables
# GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
# GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
# GOOGLE_REDIRECT_URIS = st.secrets["GOOGLE_REDIRECT_URIS"]  # Load from Streamlit secrets
# REDIRECT_URI = os.getenv('REDIRECT_URI')

GOOGLE_CLIENT_ID = st.secrets["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = st.secrets["GOOGLE_CLIENT_SECRET"]
GOOGLE_REDIRECT_URIS = st.secrets["GOOGLE_REDIRECT_URIS"]
REDIRECT_URI = st.secrets["REDIRECT_URI"]


def init_auth():
    logger.info("Initializing authentication state")
    if 'user_info' not in st.session_state:
        st.session_state.user_info = None
    if 'credentials' not in st.session_state:
        st.session_state.credentials = None
    if 'gmail_service' not in st.session_state:
        st.session_state.gmail_service = None


def load_credentials():
    try:
        # Try loading from the new Google token file first
        credentials = load_google_token()
        if credentials and credentials.valid:
            return credentials
        elif credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                save_google_token(credentials)
                return credentials
            except RefreshError as e:
                logger.error(f"Failed to refresh credentials: {str(e)}")
                return None
        # Fallback to the old token.pickle for backward compatibility
        if os.path.exists(TOKEN_PICKLE_FILE):
            with open(TOKEN_PICKLE_FILE, 'rb') as token:
                credentials = pickle.load(token)
            if credentials and credentials.valid:
                return credentials
            elif credentials and credentials.expired and credentials.refresh_token:
                try:
                    credentials.refresh(Request())
                    save_credentials(credentials)
                    return credentials
                except RefreshError as e:
                    logger.error(f"Failed to refresh credentials: {str(e)}")
                    return None
    except Exception as e:
        logger.error(f"Error loading credentials from token file: {str(e)}")
    return None


def save_credentials(credentials):
    try:
        with open(TOKEN_PICKLE_FILE, 'wb') as token:
            pickle.dump(credentials, token)
    except Exception as e:
        logger.error(f"Error saving credentials to token file: {str(e)}")


def save_google_token(credentials):
    """Save Google credentials to a dedicated pickle file."""
    try:
        with open(GOOGLE_TOKEN_PICKLE_FILE, 'wb') as token:
            pickle.dump(credentials, token)
        logger.info("Saved Google token to google_token.pkl")
    except Exception as e:
        logger.error(f"Error saving Google token: {str(e)}")


def load_google_token():
    """Load Google credentials from the dedicated pickle file."""
    try:
        if os.path.exists(GOOGLE_TOKEN_PICKLE_FILE):
            with open(GOOGLE_TOKEN_PICKLE_FILE, 'rb') as token:
                credentials = pickle.load(token)
            logger.info("Loaded Google token from google_token.pkl")
            return credentials
    except Exception as e:
        logger.error(f"Error loading Google token: {str(e)}")
    return None


def get_google_auth_url():
    logger.info("Generating Google OAuth2 authorization URL")
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URIS):
        st.error("Missing Google OAuth2 environment variables.")
        return None

    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uris": GOOGLE_REDIRECT_URIS.split(","),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    }

    try:
        flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI)
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent'
        )
        return auth_url
    except Exception as e:
        logger.error(f"Error generating auth URL: {str(e)}", exc_info=True)
        st.error(f"Authentication flow error: {str(e)}")
        return None


def handle_auth_callback(code):
    logger.info("Handling OAuth2 callback")
    try:
        client_config = {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uris": GOOGLE_REDIRECT_URIS.split(","),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        }

        flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI)
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Save credentials to both the old and new pickle files
        save_credentials(credentials)
        save_google_token(credentials)
        st.session_state.credentials = credentials

        # Get user info
        user_info = get_user_info(credentials)
        if not user_info:
            logger.error("Failed to get user information")
            st.error("Failed to get user information. Please try again.")
            return None

        st.session_state.user_info = user_info

        # Initialize Gmail service
        try:
            gmail_service = build('gmail', 'v1', credentials=credentials)
            st.session_state.gmail_service = gmail_service
            logger.info("Successfully initialized Gmail service")
        except Exception as e:
            logger.error(f"Failed to initialize Gmail service: {str(e)}", exc_info=True)
            st.error(f"Gmail service initialization failed: {str(e)}")
            return None

        return user_info
    except Exception as e:
        logger.error(f"Authentication failed: {str(e)}", exc_info=True)
        st.error(f"Authentication failed: {str(e)}")
        return None


def get_user_info(credentials):
    try:
        headers = {'Authorization': f'Bearer {credentials.token}'}
        response = requests.get('https://www.googleapis.com/oauth2/v2/userinfo', headers=headers)

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Failed to get user info. Status: {response.status_code}, Response: {response.text}")
            st.error("Failed to retrieve user info.")
            return None
    except Exception as e:
        logger.error(f"Error getting user info: {str(e)}", exc_info=True)
        st.error(f"User info retrieval error: {str(e)}")
        return None


def is_authenticated():
    """Check if user is authenticated with valid Gmail service."""
    try:
        if not st.session_state.user_info:
            return False
            
        # Check if we have valid credentials
        if not st.session_state.credentials:
            return False
            
        # Check if credentials need refresh
        if st.session_state.credentials.expired and st.session_state.credentials.refresh_token:
            try:
                st.session_state.credentials.refresh(Request())
                save_credentials(st.session_state.credentials)
            except RefreshError:
                return False
                
        # Check if Gmail service is initialized
        if not st.session_state.gmail_service:
            gmail_service = get_gmail_service()
            if not gmail_service:
                return False
                
        return True
    except Exception as e:
        logger.error(f"Error checking authentication: {str(e)}")
        return False


def get_user_email():
    if is_authenticated():
        return st.session_state.user_info.get('email')
    return None


def get_user_name():
    if is_authenticated():
        return st.session_state.user_info.get('name')
    return None


def get_gmail_service():
    """Get the Gmail service instance, refreshing credentials if needed."""
    try:
        if not st.session_state.gmail_service:
            # Try to load credentials from file
            credentials = load_credentials()
            if not credentials:
                logger.error("No valid credentials found")
                return None
            
            # Check if credentials need refresh
            if credentials.expired and credentials.refresh_token:
                try:
                    credentials.refresh(Request())
                    save_credentials(credentials)
                    st.session_state.credentials = credentials
                except RefreshError as e:
                    logger.error(f"Failed to refresh credentials: {str(e)}")
                    return None
            
            # Build Gmail service
            try:
                gmail_service = build('gmail', 'v1', credentials=credentials)
                st.session_state.gmail_service = gmail_service
            except Exception as e:
                logger.error(f"Failed to build Gmail service: {str(e)}")
                return None
        
        return st.session_state.gmail_service
    except Exception as e:
        logger.error(f"Error getting Gmail service: {str(e)}")
        return None


def logout():
    logger.info("Logging out user")
    try:
        if st.session_state.credentials and st.session_state.credentials.token:
            requests.post(
                'https://oauth2.googleapis.com/revoke',
                params={'token': st.session_state.credentials.token},
                headers={'content-type': 'application/x-www-form-urlencoded'}
            )
    except Exception as e:
        logger.error(f"Error revoking token: {str(e)}")

    st.session_state.user_info = None
    st.session_state.credentials = None
    st.session_state.gmail_service = None

    try:
        if os.path.exists(GOOGLE_TOKEN_PICKLE_FILE):
            os.remove(GOOGLE_TOKEN_PICKLE_FILE)
    except Exception as e:
        logger.error(f"Error removing Google token file: {str(e)}")
    try:
        if os.path.exists(TOKEN_PICKLE_FILE):
            os.remove(TOKEN_PICKLE_FILE)
    except Exception as e:
        logger.error(f"Error removing token file: {str(e)}")


def log_sign_in_attempt():
    logger.info("User initiated Google sign-in flow.")
