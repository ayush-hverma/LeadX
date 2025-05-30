import os
import streamlit as st
import msal
import json
import logging
from datetime import datetime, timedelta
import requests
from O365 import Account
import base64
import hashlib
import secrets
import urllib.parse
import pickle
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Microsoft Graph API scopes
OUTLOOK_SCOPES = [
    'openid',
    'profile',
    'offline_access',
    'https://graph.microsoft.com/Mail.Send',
    'https://graph.microsoft.com/User.Read'
]

def generate_code_verifier():
    """Generate a code verifier for PKCE"""
    code_verifier = secrets.token_urlsafe(32)
    return code_verifier

def generate_code_challenge(code_verifier):
    """Generate a code challenge from the verifier"""
    sha256_hash = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(sha256_hash).decode('utf-8').rstrip('=')
    return code_challenge

def init_outlook_auth():
    """Initialize Outlook authentication state"""
    if 'outlook_token' not in st.session_state:
        st.session_state.outlook_token = None
    if 'outlook_user_info' not in st.session_state:
        st.session_state.outlook_user_info = None
    if 'outlook_account' not in st.session_state:
        st.session_state.outlook_account = None
    if 'outlook_email' not in st.session_state:
        st.session_state.outlook_email = None
    if 'outlook_auth_complete' not in st.session_state:
        st.session_state.outlook_auth_complete = False
    if 'outlook_code_verifier' not in st.session_state:
        st.session_state.outlook_code_verifier = None


def get_outlook_auth_url():
    """Generate Microsoft OAuth2 authorization URL with unique state and code verifier file."""
    try:
        client_id = st.secrets["OUTLOOK_CLIENT_ID"]["value"]
        redirect_uri = st.secrets["OUTLOOK_REDIRECT_URI"]["value"]

        # Ensure redirect URI is properly formatted
        if not redirect_uri.endswith('/'):
            redirect_uri = redirect_uri + '/'

        # Generate unique state and PKCE values
        state = f"outlook_auth_{uuid.uuid4().hex}"
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        # Store code verifier in a unique file (per state)
        save_code_verifier(code_verifier, state)
        logger.info(f"Generated and saved code verifier to file for state {state}")

        # Construct the authorization URL manually
        auth_params = {
            'client_id': client_id,
            'response_type': 'code',
            'redirect_uri': redirect_uri,
            'scope': ' '.join(OUTLOOK_SCOPES),
            'response_mode': 'query',
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
            'state': state,
            'prompt': 'consent',  # Force consent to get refresh token
            'access_type': 'offline',  # Request refresh token
            'domain_hint': 'organizations'  # Add domain hint for work accounts
        }
        auth_url = f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?{urllib.parse.urlencode(auth_params)}"
        logger.info(f"Generated auth URL with PKCE: {auth_url}")
        return auth_url
    except Exception as e:
        logger.error(f"Error generating Outlook auth URL: {str(e)}")
        st.error("Failed to initialize Outlook authentication")
        return None

def get_outlook_account():
    """Get the Outlook account instance"""
    try:
        # Get client credentials
        client_id = st.secrets["OUTLOOK_CLIENT_ID"]["value"]
        client_secret = st.secrets["OUTLOOK_CLIENT_SECRET"]["value"]
        
        # Initialize account
        account = Account((client_id, client_secret))
        
        # Get token from file
        from outlook_auth import load_outlook_token
        token = load_outlook_token()
        if not token:
            logger.error("No token found in local file")
            return None
        
        # Set token in account
        account.connection.token_backend.token = token
        
        # Verify token is valid by making a test request
        try:
            account.connection.get('https://graph.microsoft.com/v1.0/me')
            logger.info("Token is valid")
            return account
        except Exception as e:
            logger.error(f"Token validation failed: {str(e)}")
            # If token is invalid, try to refresh
            if 'refresh_token' in token:
                new_token = refresh_outlook_token(token['refresh_token'])
                if new_token:
                    from outlook_auth import save_outlook_token
                    save_outlook_token(new_token)
                    account.connection.token_backend.token = new_token
                    logger.info("Successfully refreshed token")
                    return account
            # If refresh failed or no refresh token, return None
            return None
    except Exception as e:
        logger.error(f"Error getting Outlook account: {str(e)}")
        return None

def refresh_outlook_token(refresh_token):
    """Refresh the Outlook access token using the refresh token"""
    try:
        client_id = st.secrets["OUTLOOK_CLIENT_ID"]["value"]
        client_secret = st.secrets["OUTLOOK_CLIENT_SECRET"]["value"]
        
        token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        token_data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token',
            'scope': ' '.join(OUTLOOK_SCOPES)
        }
        
        response = requests.post(token_url, data=token_data)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Token refresh failed: {response.text}")
            return None
    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}")
        return None

def handle_outlook_callback(code):
    """Handle Microsoft OAuth2 callback using state-specific code verifier file."""
    # Guard: Only run if 'code' and 'state' are present in st.query_params
    if not (
        hasattr(st, 'query_params') and
        'code' in st.query_params and
        'state' in st.query_params
    ):
        logger.info("[Outlook Auth] handle_outlook_callback called outside of valid OAuth context; skipping.")
        return None
    try:
        state = st.query_params['state']
        client_id = st.secrets["OUTLOOK_CLIENT_ID"]["value"]
        client_secret = st.secrets["OUTLOOK_CLIENT_SECRET"]["value"]
        redirect_uri = st.secrets["OUTLOOK_REDIRECT_URI"]["value"]
        if not redirect_uri.endswith('/'):
            redirect_uri = redirect_uri + '/'
        # Load code verifier from the file
        code_verifier = load_code_verifier()
        if not code_verifier:
            logger.error("[Outlook Auth] Code verifier not found. Please restart the sign-in flow.")
            st.error("Your Outlook authentication session expired. Please sign in again from the beginning.")
            if os.path.exists('outlook_token.pkl'):
                os.remove('outlook_token.pkl')
            for k in ["outlook_token", "outlook_user_info", "outlook_account", "outlook_email", "outlook_auth_complete"]:
                if k in st.session_state:
                    st.session_state[k] = None
            return None
        logger.info("[Outlook Auth] Retrieved code verifier successfully")
        token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        token_data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
            'code_verifier': code_verifier,
            'scope': ' '.join(OUTLOOK_SCOPES)
        }
        logger.info(f"[Outlook Auth] Making token request to {token_url}")
        response = requests.post(token_url, data=token_data)
        logger.info(f"[Outlook Auth] Token response status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            if "access_token" in result:
                if "refresh_token" not in result:
                    st.error("Microsoft did not return a refresh token. Please remove the app from https://myapps.microsoft.com, clear your browser cache, and try again. If the problem persists, check your Azure app registration for offline_access scope and redirect URI.")
                    return None
                save_outlook_token(result)
                user_info = get_outlook_user_info(result["access_token"])
                if user_info:
                    logger.info("[Outlook Auth] Successfully authenticated with Outlook")
                    st.session_state.outlook_auth_complete = True
                    # Keep the code verifier file for future use
                    return user_info
                else:
                    logger.error("[Outlook Auth] Failed to get user information")
                    st.error("Failed to get user information")
                    return None
            else:
                logger.error(f"[Outlook Auth] Failed to acquire token - missing access_token in response: {result}")
                st.error(f"Failed to acquire token - missing required tokens. Response: {result}")
                return None
        else:
            logger.error(f"[Outlook Auth] Token request failed: {response.text}")
            try:
                error_json = response.json()
                if (
                    error_json.get("error") == "invalid_grant" and
                    "AADSTS54005" in error_json.get("error_description", "")
                ):
                    logger.info("[Outlook Auth] Code was already redeemed. Prompting user to retry sign-in.")
                    st.error("Your authentication session expired or was already used. Please try signing in again.")
                    return None
            except Exception as parse_err:
                logger.error(f"[Outlook Auth] Error parsing token error response: {parse_err}")
            st.error(f"Failed to acquire token. Response: {response.text}")
            return None
    except Exception as e:
        logger.error(f"[Outlook Auth] Outlook authentication failed: {str(e)}")
        st.error(f"Authentication failed: {str(e)}")
        return None

def get_outlook_user_info(access_token):
    """Get user information from Microsoft Graph API, with session caching."""
    if 'outlook_user_info' in st.session_state and st.session_state.outlook_user_info:
        return st.session_state.outlook_user_info
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        response = requests.get('https://graph.microsoft.com/v1.0/me', headers=headers)
        logger.info(f"User info response status: {response.status_code}")
        logger.info(f"User info response: {response.text}")

        if response.status_code == 200:
            user_info = response.json()
            st.session_state.outlook_user_info = user_info
            return user_info
        elif response.status_code == 401 and "Lifetime validation failed, the token is expired" in response.text:
            logger.error("Outlook token expired. Removing token file and forcing re-authentication.")
            if os.path.exists('outlook_token.pkl'):
                os.remove('outlook_token.pkl')
            st.session_state.outlook_token = None
            st.session_state.outlook_user_info = None
            st.session_state.outlook_account = None
            st.session_state.outlook_email = None
            st.session_state.outlook_auth_complete = False
            st.session_state["force_sign_in"] = True
            st.warning("Your Outlook session expired. Please sign in again.")
            st.rerun()
            return None
        else:
            logger.error(f"Failed to get user info. Status: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error getting Outlook user info: {str(e)}")
        return None

def is_outlook_authenticated():
    """Check if user is authenticated with Outlook"""
    try:
        from outlook_auth import load_outlook_token
        token = load_outlook_token()
        if not token or 'access_token' not in token:
            logger.info("No valid token found in local file")
            return False
        # Optionally, check token validity by making a test request
        return True
    except Exception as e:
        logger.error(f"Error checking Outlook authentication: {str(e)}")
        return False

def get_outlook_email():
    """Get authenticated user's Outlook email (cached)."""
    if 'outlook_user_info' in st.session_state and st.session_state.outlook_user_info:
        user_info = st.session_state.outlook_user_info
    else:
        from outlook_auth import load_outlook_token
        token = load_outlook_token()
        if not token or 'access_token' not in token:
            return None
        user_info = get_outlook_user_info(token['access_token'])
    if user_info and 'mail' in user_info:
        return user_info['mail']
    return None

def get_outlook_name():
    """Get authenticated user's name (cached)."""
    if 'outlook_user_info' in st.session_state and st.session_state.outlook_user_info:
        user_info = st.session_state.outlook_user_info
    else:
        from outlook_auth import load_outlook_token
        token = load_outlook_token()
        if not token or 'access_token' not in token:
            return None
        user_info = get_outlook_user_info(token['access_token'])
    if user_info and 'displayName' in user_info:
        return user_info['displayName']
    return None

def outlook_logout():
    """Logout from Outlook"""
    st.session_state.outlook_token = None
    st.session_state.outlook_user_info = None
    st.session_state.outlook_account = None
    st.session_state.outlook_email = None
    st.session_state.outlook_auth_complete = False

def save_outlook_token(token):
    """Save the Outlook token to a local file."""
    try:
        filename = 'outlook_token.pkl'
        with open(filename, 'wb') as f:
            pickle.dump(token, f)
        logger.info(f"[Outlook Auth] Successfully saved Outlook token to {filename}")
    except Exception as e:
        logger.error(f"[Outlook Auth] Error saving Outlook token: {str(e)}")

def load_outlook_token():
    """Load the Outlook token from a local file."""
    try:
        filename = 'outlook_token.pkl'
        if os.path.exists(filename):
            with open(filename, 'rb') as f:
                token = pickle.load(f)
            logger.info(f"[Outlook Auth] Successfully loaded Outlook token from {filename}")
            return token
        logger.warning("[Outlook Auth] No Outlook token file found")
    except Exception as e:
        logger.error(f"[Outlook Auth] Error loading Outlook token: {str(e)}")
    return None

def save_code_verifier(code_verifier, state=None):
    """Save the PKCE code verifier to a local file."""
    try:
        # Save the code verifier directly in the current directory
        filename = 'outlook_code_verifier.pkl'
        with open(filename, 'wb') as f:
            pickle.dump(code_verifier, f)
        logger.info(f"[Outlook Auth] Successfully saved code verifier to {filename}")
        
        # Ensure file has proper permissions
        os.chmod(filename, 0o644)
        
        return True
    except Exception as e:
        logger.error(f"[Outlook Auth] Error saving code verifier: {str(e)}")
        st.error(f"Failed to save authentication data: {str(e)}")
        return False

def load_code_verifier(state=None):
    """Load the PKCE code verifier from a local file."""
    try:
        filename = 'outlook_code_verifier.pkl'
        
        if os.path.exists(filename):
            with open(filename, 'rb') as f:
                code_verifier = pickle.load(f)
            logger.info(f"[Outlook Auth] Successfully loaded code verifier from {filename}")
            return code_verifier
            
        logger.warning("[Outlook Auth] No code verifier file found")
        return None
    except Exception as e:
        logger.error(f"[Outlook Auth] Error loading code verifier: {str(e)}")
        return None

def clear_code_verifier(state=None):
    """Remove code verifier from local file."""
    try:
        filename = 'outlook_code_verifier.pkl'
        
        # Only clear the code verifier if authentication was successful
        if os.path.exists(filename) and st.session_state.get('outlook_auth_complete', False):
            os.remove(filename)
            logger.info(f"[Outlook Auth] Removed code verifier file {filename}")
    except Exception as e:
        logger.error(f"[Outlook Auth] Error clearing code verifier: {str(e)}")
