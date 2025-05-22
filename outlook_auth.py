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

def save_code_verifier(code_verifier):
    """Save code verifier to a file"""
    try:
        with open('outlook_code_verifier.pkl', 'wb') as f:
            pickle.dump(code_verifier, f)
        logger.info("Saved code verifier to file")
    except Exception as e:
        logger.error(f"Error saving code verifier: {str(e)}")

def load_code_verifier():
    """Load code verifier from file"""
    try:
        if os.path.exists('outlook_code_verifier.pkl'):
            with open('outlook_code_verifier.pkl', 'rb') as f:
                code_verifier = pickle.load(f)
            logger.info("Loaded code verifier from file")
            return code_verifier
    except Exception as e:
        logger.error(f"Error loading code verifier: {str(e)}")
    return None

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

def get_outlook_auth_url():
    """Generate Microsoft OAuth2 authorization URL"""
    try:
        client_id = st.secrets["OUTLOOK_CLIENT_ID"]["value"]
        redirect_uri = st.secrets["OUTLOOK_REDIRECT_URI"]["value"]

        # Ensure redirect URI is properly formatted
        if not redirect_uri.endswith('/'):
            redirect_uri = redirect_uri + '/'

        # Generate PKCE values
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        
        # Save code verifier to file
        save_code_verifier(code_verifier)
        logger.info("Generated and saved code verifier")

        # Construct the authorization URL manually
        auth_params = {
            'client_id': client_id,
            'response_type': 'code',
            'redirect_uri': redirect_uri,
            'scope': ' '.join(OUTLOOK_SCOPES),
            'response_mode': 'query',
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
            'state': 'outlook_auth',
            'prompt': 'select_account',  # Force account selection
            'domain_hint': 'organizations',  # Add domain hint for work accounts
            'login_hint': st.session_state.get('outlook_email', '')  # Add login hint if available
        }

        auth_url = f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?{urllib.parse.urlencode(auth_params)}"
        logger.info(f"Generated auth URL with PKCE: {auth_url}")
        return auth_url

    except Exception as e:
        logger.error(f"Error generating Outlook auth URL: {str(e)}")
        st.error("Failed to initialize Outlook authentication")
        return None

def handle_outlook_callback(code):
    """Handle Microsoft OAuth2 callback"""
    try:
        # Check if this is an Outlook auth callback
        if 'state' in st.query_params and st.query_params['state'] != 'outlook_auth':
            logger.info("Not an Outlook auth callback")
            return None

        client_id = st.secrets["OUTLOOK_CLIENT_ID"]["value"]
        client_secret = st.secrets["OUTLOOK_CLIENT_SECRET"]["value"]
        redirect_uri = st.secrets["OUTLOOK_REDIRECT_URI"]["value"]

        # Ensure redirect URI is properly formatted
        if not redirect_uri.endswith('/'):
            redirect_uri = redirect_uri + '/'

        # Load code verifier from file
        code_verifier = load_code_verifier()
        if not code_verifier:
            logger.error("Code verifier not found")
            st.error("Authentication session expired. Please try signing in again.")
            return None

        logger.info("Retrieved code verifier")

        # Prepare token request for web application
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

        logger.info(f"Making token request to {token_url}")
        logger.info(f"Token request data: {token_data}")

        # Make token request
        response = requests.post(token_url, data=token_data)
        logger.info(f"Token response status: {response.status_code}")
        logger.info(f"Token response: {response.text}")

        if response.status_code == 200:
            result = response.json()
            if "access_token" in result:
                # Store token in session state
                st.session_state.outlook_token = result
                
                # Get user info first
                user_info = get_outlook_user_info(result["access_token"])
                if user_info:
                    # Store user info in session
                    st.session_state.outlook_user_info = user_info
                    st.session_state.outlook_email = user_info.get('mail', '')
                    
                    # Initialize account with token
                    account = Account((client_id, client_secret))
                    account.connection.token_backend.token = result
                    st.session_state.outlook_account = account
                    
                    # Mark authentication as complete
                    st.session_state.outlook_auth_complete = True
                    
                    # Clean up the code verifier file
                    try:
                        os.remove('outlook_code_verifier.pkl')
                    except:
                        pass
                    
                    logger.info("Successfully authenticated with Outlook")
                    return user_info
                else:
                    logger.error("Failed to get user information")
                    st.error("Failed to get user information")
                    return None
            else:
                logger.error("Failed to acquire token - no access_token in response")
                st.error("Failed to acquire token")
                return None
        else:
            logger.error(f"Token request failed: {response.text}")
            st.error("Failed to acquire token")
            return None

    except Exception as e:
        logger.error(f"Outlook authentication failed: {str(e)}")
        st.error(f"Authentication failed: {str(e)}")
        return None

def get_outlook_user_info(access_token):
    """Get user information from Microsoft Graph API"""
    try:
        headers = {'Authorization': f'Bearer {access_token}'}
        response = requests.get('https://graph.microsoft.com/v1.0/me', headers=headers)
        
        logger.info(f"User info response status: {response.status_code}")
        logger.info(f"User info response: {response.text}")

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Failed to get user info. Status: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error getting Outlook user info: {str(e)}")
        return None

def is_outlook_authenticated():
    """Check if user is authenticated with Outlook"""
    try:
        # Check if we have all required session state variables
        if not all(key in st.session_state for key in ['outlook_user_info', 'outlook_token', 'outlook_account', 'outlook_auth_complete']):
            logger.info("Missing required session state variables")
            return False
            
        # Check if authentication is complete
        if not st.session_state.outlook_auth_complete:
            logger.info("Authentication not complete")
            return False
            
        # Check if we have valid token
        if not st.session_state.outlook_token or 'access_token' not in st.session_state.outlook_token:
            logger.info("No valid token found")
            return False
            
        # Check if we have user info
        if not st.session_state.outlook_user_info:
            logger.info("No user info found")
            return False
            
        # Check if we have account
        if not st.session_state.outlook_account:
            logger.info("No account found")
            return False
            
        logger.info("Outlook authentication check passed")
        return True
    except Exception as e:
        logger.error(f"Error checking Outlook authentication: {str(e)}")
        return False

def get_outlook_email():
    """Get authenticated user's Outlook email"""
    return st.session_state.outlook_user_info.get('mail') if is_outlook_authenticated() else None

def get_outlook_name():
    """Get authenticated user's name"""
    return st.session_state.outlook_user_info.get('displayName') if is_outlook_authenticated() else None

def get_outlook_account():
    """Get authenticated Outlook account"""
    return st.session_state.outlook_account if is_outlook_authenticated() else None

def outlook_logout():
    """Logout from Outlook"""
    st.session_state.outlook_token = None
    st.session_state.outlook_user_info = None
    st.session_state.outlook_account = None
    st.session_state.outlook_email = None
    st.session_state.outlook_auth_complete = False 