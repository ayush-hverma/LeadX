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
import time

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
    # Create auth directory if it doesn't exist
    os.makedirs('.auth', exist_ok=True)
    
    # Clear any existing session state
    for k in ["outlook_token", "outlook_user_info", "outlook_account", "outlook_email", "outlook_auth_complete"]:
        if k in st.session_state:
            del st.session_state[k]

def get_outlook_auth_url():
    """Generate Microsoft OAuth2 authorization URL with unique state and code verifier file."""
    try:
        client_id = st.secrets["OUTLOOK_CLIENT_ID"]["value"]
        redirect_uri = st.secrets["OUTLOOK_REDIRECT_URI"]["value"]

        # Ensure redirect URI is properly formatted
        if not redirect_uri.endswith('/'):
            redirect_uri = redirect_uri + '/'

        # Clear any existing code verifier and token
        clear_code_verifier()
        if os.path.exists('.auth/outlook_token.pkl'):
            os.remove('.auth/outlook_token.pkl')
            
        # Clear session state
        init_outlook_auth()

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
            
        # Load code verifier from the state-specific file
        code_verifier = load_code_verifier(state)
        if not code_verifier:
            logger.error(f"[Outlook Auth] Code verifier not found for state {state}. Please restart the sign-in flow.")
            st.error("Your Outlook authentication session expired. Please sign in again from the beginning.")
            clear_auth_state()
            return None
            
        logger.info(f"[Outlook Auth] Retrieved code verifier successfully for state {state}")
        
        # First try to use the refresh token if available
        token = load_outlook_token()
        if token and 'refresh_token' in token:
            try:
                new_token = refresh_outlook_token(token['refresh_token'])
                if new_token:
                    save_outlook_token(new_token)
                    user_info = get_outlook_user_info(new_token["access_token"])
                    if user_info:
                        logger.info("[Outlook Auth] Successfully refreshed token")
                        update_session_state(new_token, user_info)
                        return user_info
            except Exception as refresh_error:
                logger.warning(f"[Outlook Auth] Token refresh failed: {str(refresh_error)}")
                # Continue with code exchange if refresh fails
        
        # If refresh failed or no refresh token, try code exchange
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
                    st.error("Microsoft did not return a refresh token. Please remove the app from https://myapps.microsoft.com, clear your browser cache, and try again.")
                    clear_auth_state()
                    return None
                save_outlook_token(result)
                user_info = get_outlook_user_info(result["access_token"])
                if user_info:
                    logger.info("[Outlook Auth] Successfully authenticated with Outlook")
                    update_session_state(result, user_info)
                    # Clear the state-specific code verifier after successful authentication
                    clear_code_verifier(state)
                    return user_info
                else:
                    logger.error("[Outlook Auth] Failed to get user information")
                    st.error("Failed to get user information")
                    clear_auth_state()
                    return None
            else:
                logger.error(f"[Outlook Auth] Failed to acquire token - missing access_token in response: {result}")
                st.error(f"Failed to acquire token - missing required tokens.")
                clear_auth_state()
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
                    clear_auth_state()
                    st.error("Your authentication session expired or was already used. Please try signing in again.")
                    return None
            except Exception as parse_err:
                logger.error(f"[Outlook Auth] Error parsing token error response: {parse_err}")
            st.error(f"Failed to acquire token.")
            clear_auth_state()
            return None
    except Exception as e:
        logger.error(f"[Outlook Auth] Outlook authentication failed: {str(e)}")
        st.error(f"Authentication failed: {str(e)}")
        clear_auth_state()
        return None

def get_outlook_user_info(access_token):
    """Get user information from Microsoft Graph API."""
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        response = requests.get('https://graph.microsoft.com/v1.0/me', headers=headers)
        logger.info(f"User info response status: {response.status_code}")
        logger.info(f"User info response: {response.text}")

        if response.status_code == 200:
            user_info = response.json()
            # Save user info to local file
            save_user_info(user_info)
            return user_info
        elif response.status_code == 401 and "Lifetime validation failed, the token is expired" in response.text:
            logger.error("Outlook token expired. Removing token file and forcing re-authentication.")
            clear_auth_state()
            st.warning("Your Outlook session expired. Please sign in again.")
            st.rerun()
            return None
        else:
            logger.error(f"Failed to get user info. Status: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error getting Outlook user info: {str(e)}")
        return None

def save_user_info(user_info):
    """Save user information to a local file."""
    try:
        os.makedirs('.auth', exist_ok=True)
        with open('.auth/outlook_user_info.pkl', 'wb') as f:
            pickle.dump(user_info, f)
        logger.info("Successfully saved user info")
    except Exception as e:
        logger.error(f"Failed to save user info: {str(e)}")

def load_user_info():
    """Load user information from a local file."""
    try:
        if os.path.exists('.auth/outlook_user_info.pkl'):
            with open('.auth/outlook_user_info.pkl', 'rb') as f:
                user_info = pickle.load(f)
            logger.info("Successfully loaded user info")
            return user_info
        return None
    except Exception as e:
        logger.error(f"Failed to load user info: {str(e)}")
        return None

def get_outlook_email():
    """Get authenticated user's Outlook email."""
    user_info = load_user_info()
    if user_info and 'mail' in user_info:
        return user_info['mail']
    return None

def get_outlook_name():
    """Get authenticated user's name."""
    user_info = load_user_info()
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
        os.makedirs('.auth', exist_ok=True)
        with open('.auth/outlook_token.pkl', 'wb') as f:
            pickle.dump(token, f)
        logger.info("Successfully saved Outlook token")
    except Exception as e:
        logger.error(f"Failed to save Outlook token: {str(e)}")

def load_outlook_token():
    """Load the Outlook token from a local file."""
    try:
        if os.path.exists('.auth/outlook_token.pkl'):
            with open('.auth/outlook_token.pkl', 'rb') as f:
                token = pickle.load(f)
            logger.info("Successfully loaded Outlook token")
            return token
        return None
    except Exception as e:
        logger.error(f"Failed to load Outlook token: {str(e)}")
        return None

def save_code_verifier(code_verifier, state=None):
    """Save the PKCE code verifier to a local file."""
    try:
        os.makedirs('.auth', exist_ok=True)
        filename = f'.auth/code_verifier_{state}.pkl' if state else '.auth/code_verifier.pkl'
        with open(filename, 'wb') as f:
            pickle.dump(code_verifier, f)
        logger.info(f"Successfully saved code verifier to {filename}")
        
        # Ensure file has proper permissions
        os.chmod(filename, 0o644)
        
        return True
    except Exception as e:
        logger.error(f"Failed to save code verifier: {str(e)}")
        st.error(f"Failed to save authentication data: {str(e)}")
        return False

def load_code_verifier(state=None):
    """Load the PKCE code verifier from a local file."""
    try:
        filename = f'.auth/code_verifier_{state}.pkl' if state else '.auth/code_verifier.pkl'
        
        if os.path.exists(filename):
            with open(filename, 'rb') as f:
                code_verifier = pickle.load(f)
            logger.info(f"Successfully loaded code verifier from {filename}")
            return code_verifier
            
        logger.warning("[Outlook Auth] No code verifier file found")
        return None
    except Exception as e:
        logger.error(f"Failed to load code verifier: {str(e)}")
        return None

def clear_code_verifier(state=None):
    """Remove code verifier from local file."""
    try:
        filename = f'.auth/code_verifier_{state}.pkl' if state else '.auth/code_verifier.pkl'
        
        if os.path.exists(filename):
            os.remove(filename)
            logger.info(f"[Outlook Auth] Removed code verifier file {filename}")
    except Exception as e:
        logger.error(f"[Outlook Auth] Error clearing code verifier: {str(e)}")

def clear_auth_state():
    """Clear all authentication related state and files."""
    try:
        # Clear token file
        if os.path.exists('.auth/outlook_token.pkl'):
            os.remove('.auth/outlook_token.pkl')
            
        # Clear user info file
        if os.path.exists('.auth/outlook_user_info.pkl'):
            os.remove('.auth/outlook_user_info.pkl')
            
        # Clear code verifier files
        for file in os.listdir('.auth'):
            if file.startswith('code_verifier'):
                os.remove(os.path.join('.auth', file))
                
        logger.info("Successfully cleared all authentication state")
    except Exception as e:
        logger.error(f"Failed to clear authentication state: {str(e)}")

def update_session_state(token, user_info):
    """Update session state with token and user info."""
    # Save user info to local file
    save_user_info(user_info)
    # Save token to local file
    save_outlook_token(token)

def is_outlook_authenticated():
    """Check if user is authenticated with Outlook."""
    try:
        token = load_outlook_token()
        if not token:
            return False
            
        # Check if token is expired
        if token.get('expires_at', 0) < time.time():
            # Try to refresh token
            new_token = refresh_token(token)
            if new_token:
                save_outlook_token(new_token)
                return True
            return False
            
        # Verify token is still valid by making a test request
        try:
            headers = {'Authorization': f'Bearer {token["access_token"]}'}
            response = requests.get('https://graph.microsoft.com/v1.0/me', headers=headers)
            if response.status_code == 200:
                # Update user info if needed
                user_info = response.json()
                save_user_info(user_info)
                return True
            else:
                logger.error(f"Token validation failed: {response.text}")
                clear_auth_state()
                return False
        except Exception as e:
            logger.error(f"Error validating token: {str(e)}")
            return False
    except Exception as e:
        logger.error(f"Error checking Outlook authentication: {str(e)}")
        return False

def refresh_token(token):
    """Refresh the Outlook access token."""
    try:
        if not token or 'refresh_token' not in token:
            logger.error("No refresh token available")
            return None
            
        # Get client credentials from secrets
        client_id = st.secrets["OUTLOOK_CLIENT_ID"]["value"]
        client_secret = st.secrets["OUTLOOK_CLIENT_SECRET"]["value"]
        token_endpoint = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
            
        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'grant_type': 'refresh_token',
            'refresh_token': token['refresh_token'],
            'scope': ' '.join(OUTLOOK_SCOPES)
        }
        
        response = requests.post(token_endpoint, data=data)
        if response.status_code == 200:
            new_token = response.json()
            # Add expires_at field
            new_token['expires_at'] = time.time() + new_token.get('expires_in', 3600)
            return new_token
        else:
            logger.error(f"Failed to refresh token: {response.text}")
            return None
    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}")
        return None
