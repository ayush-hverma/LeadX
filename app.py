import streamlit as st
import pandas as pd
from people_search import get_people_search_results
from people_enrich import get_people_data
from mail_generation import EmailGenerationPipeline
from email_sender import EmailSender, prepare_email_payloads
import time
import asyncio
import json
import PyPDF2
import io
import dotenv
import logging
from personalised_email import product_database, generate_email_for_single_lead, generate_email_for_multiple_leads, get_product_details
from auth import init_auth, is_authenticated, get_google_auth_url, handle_auth_callback, get_user_name, logout, log_sign_in_attempt
from outlook_auth import init_outlook_auth, get_outlook_auth_url, handle_outlook_callback, is_outlook_authenticated, get_outlook_email
from urllib.parse import parse_qs, urlparse
from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import google.generativeai as genai
import msal
import requests
from outlook_sender import prepare_outlook_email_payloads, OutlookSender
from outlook_auth import get_outlook_name
from mongodb_client import save_enriched_data, save_generated_emails, collection, generated_emails_collection, lead_exists, delete_lead_by_id, delete_email_by_id, get_signature, save_signature
import bson
from datetime import datetime
from bson import ObjectId

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
dotenv.load_dotenv()

# Initialize authentication
init_auth()
init_outlook_auth()

# Set page config
st.set_page_config(page_title="Apollo.io People Pipeline", layout="wide")

# Example: Accessing secrets from .streamlit/secrets.toml
apollo_api_key = st.secrets["APOLLO_API_KEY"]
gemini_api_key = st.secrets["GEMINI_API_KEY"]
google_client_id = st.secrets["GOOGLE_CLIENT_ID"]
redirect_uri = st.secrets["REDIRECT_URI"]
google_client_secret = st.secrets["GOOGLE_CLIENT_SECRET"]
google_project_id = st.secrets["GOOGLE_PROJECT_ID"]
# google_redirect_uris = st.secrets["GOOGLE_REDIRECT_URIS"]

# Azure AD configuration
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TENANT_ID = os.getenv("TENANT_ID")
REDIRECT_URI = os.getenv("REDIRECT_URI")

# Microsoft Graph API endpoints
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPE = ["User.Read"]

def init_msal_app():
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET
    )

def get_auth_url():
    return f"{AUTHORITY}/oauth2/v2.0/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri={REDIRECT_URI}&scope={' '.join(SCOPE)}"

def get_token_from_code(code):
    app = init_msal_app()
    result = app.acquire_token_by_authorization_code(
        code,
        scopes=SCOPE,
        redirect_uri=REDIRECT_URI
    )
    return result

def get_user_info(access_token):
    headers = {'Authorization': f'Bearer {access_token}'}
    response = requests.get('https://graph.microsoft.com/v1.0/me', headers=headers)
    return response.json()

def get_user_email():
    """Get the email of the currently authenticated user."""
    if is_outlook_authenticated():
        return get_outlook_email()
    elif is_authenticated():
        return st.session_state.get('user_email')
    return None

def handle_auth_flow():
    """Handle the authentication flow."""
    # Check if we're handling the OAuth callback
    query_params = st.query_params
    if 'code' in query_params:
        code = query_params['code']
        #logger.info(f"Received auth code: {code}")
        # Check if this is an Outlook auth callback (state startswith outlook_auth)
        if 'state' in query_params and str(query_params['state']).startswith('outlook_auth'):
            user_info = handle_outlook_callback(code)
        else:
            user_info = handle_auth_callback(code)
        if user_info:
            # Clear query parameters and rerun
            st.query_params.clear()
            st.rerun()
        else:
            st.error("Authentication failed. Please try again.")
            st.stop()
    else:
        # Show login page
        st.title("Welcome to LeadX")
        st.write("Please sign in with your account to continue.")
        
        # Create a container for the login buttons
        login_container = st.container()
        
        with login_container:
            col1, col2 = st.columns(2)
            
            with col1:
                try:
                    # Create Google login button
                    auth_url = get_google_auth_url()
                    if auth_url:
                        logger.info("Successfully generated Google auth URL")
                        log_sign_in_attempt()
                        st.markdown(f'<a href="{auth_url}" target="_blank"><button style="background-color: #4285F4; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; width: 100%;">Sign in with Google</button></a>', unsafe_allow_html=True)
                    else:
                        logger.error("Failed to generate Google auth URL - URL is None")
                        st.error("Failed to generate Google authentication URL.")
                except Exception as e:
                    logger.error(f"Error generating Google auth URL: {str(e)}", exc_info=True)
                    st.error(f"Google authentication error: {str(e)}")
            
            with col2:
                try:
                    # Create Outlook login button
                    outlook_auth_url = get_outlook_auth_url()
                    if outlook_auth_url:
                        logger.info("Successfully generated Outlook auth URL")
                        # Extract state from the URL
                        from urllib.parse import urlparse, parse_qs
                        parsed = urlparse(outlook_auth_url)
                        qs = parse_qs(parsed.query)
                        state = qs.get('state', [None])[0]
                        if state:
                            st.session_state['outlook_auth_state'] = state
                            # Try to load and store the code verifier for this state
                            from outlook_auth import load_code_verifier
                            code_verifier = load_code_verifier(state)
                            st.session_state['outlook_code_verifier'] = code_verifier
                        st.markdown(f'<a href="{outlook_auth_url}" target="_blank"><button style="background-color: #0078D4; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; width: 100%;">Sign in with Outlook</button></a>', unsafe_allow_html=True)
                    else:
                        logger.error("Failed to generate Outlook auth URL - URL is None")
                        st.error("Failed to generate Outlook authentication URL.")
                except Exception as e:
                    logger.error(f"Error generating Outlook auth URL: {str(e)}", exc_info=True)
                    st.error(f"Outlook authentication error: {str(e)}")
        
        st.stop()

@app.route('/api/generate-email', methods=['POST'])
def generate_email():
    try:
        data = request.get_json()
        leads = data.get('leads', [])
        product = data.get('product', '')
        
        logging.info(f"Received email generation request for {len(leads)} leads and product: {product}")
        
        if not leads or not product:
            logging.error("Missing required fields in request")
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Get product details from the database
        product_details = product_database.get(product.lower())
        if not product_details:
            logging.error(f"Invalid product requested: {product}")
            return jsonify({'error': 'Invalid product'}), 400
        
        # Convert product details to string format
        product_details_str = json.dumps(product_details)
        
        # Generate emails for all leads
        logging.info("Starting email generation process")
        generated_emails = generate_email_for_multiple_leads(leads, product_details_str)
        
        # Log success/failure statistics
        success_count = sum(1 for email in generated_emails if email.get('subject') != '[No subject generated]' and email.get('body') != '[No body generated]')
        failure_count = len(generated_emails) - success_count
        logging.info(f"Email generation completed. Success: {success_count}, Failed: {failure_count}, Total: {len(generated_emails)}")
        
        return jsonify({
            'emails': generated_emails,
            'stats': {
                'total': len(generated_emails),
                'successful': success_count,
                'failed': failure_count
            }
        })
        
    except Exception as e:
        logging.error(f"Error in generate-email endpoint: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/delete_lead', methods=['POST'])
def delete_lead():
    try:
        data = request.get_json()
        lead_id = data.get('lead_id')
        user_email = get_user_email()
        
        if not lead_id or not user_email:
            return jsonify({'error': 'Missing lead_id or user_email'}), 400
            
        from mongodb_client import delete_lead_by_id
        success = delete_lead_by_id(lead_id, user_email)
        
        if success:
            return jsonify({'message': 'Lead deleted successfully'}), 200
        else:
            return jsonify({'error': 'Failed to delete lead'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/delete_email', methods=['POST'])
def delete_email():
    try:
        data = request.get_json()
        email_id = data.get('email_id')
        user_email = get_user_email()
        
        if not email_id or not user_email:
            return jsonify({'error': 'Missing email_id or user_email'}), 400
            
        from mongodb_client import delete_email_by_id
        success = delete_email_by_id(email_id, user_email)
        
        if success:
            return jsonify({'message': 'Email deleted successfully'}), 200
        else:
            return jsonify({'error': 'Failed to delete email'}), 404
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

class MongoJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        return super().default(obj)

def prepare_email_payloads(generated_emails, enriched_data):
    """Prepare email payloads for sending emails."""
    payloads = []
    
    # Check authentication
    if not is_outlook_authenticated() and not is_authenticated():
        print("[DEBUG] No authentication found")
        return payloads
        
    # Get sender information based on authentication method
    if is_outlook_authenticated():
        sender_email = get_outlook_email()
        sender_name = get_outlook_name()
    else:
        sender_email = get_user_email()
        sender_name = get_user_name()
    
    if not sender_email:
        print("[DEBUG] No sender email found")
        return payloads
    
    if not generated_emails:
        print("[DEBUG] No generated emails provided")
        return payloads
        
    if enriched_data is None:
        print("[DEBUG] No enriched data provided")
        return payloads
    
    for lead_block in generated_emails:
        try:
            # Get lead data from enriched data
            lead_id = lead_block.get("lead_id")
            if not lead_id:
                print("[DEBUG] No lead_id found in email data")
                continue
                
            lead_data = enriched_data[enriched_data['lead_id'] == lead_id]
            if lead_data.empty:
                print(f"[DEBUG] No matching lead data found for lead_id {lead_id}")
                continue
                
            recipient_email = lead_data['email'].iloc[0]
            
            # Process each email in the lead_block
            emails = lead_block.get("emails", [])
            for email in emails:
                try:
                    # Get email content
                    subject = email.get("subject", "")
                    body = email.get("body", "")
                    
                    if not all([recipient_email, subject, body]):
                        print(f"[DEBUG] Skipping: missing required fields for lead_id {lead_id}")
                        continue
                    
                    # Format the email body with proper closing
                    if sender_name:
                        # Remove any existing closings
                        body = body.replace("Best regards,\n[Your Name]", "")
                        body = body.replace("Best Regards,\n[Your Name]", "")
                        body = body.replace("Best regards,", "")
                        body = body.replace("Best Regards,", "")
                        body = body.strip()
                        
                        # Add the properly formatted closing
                        body = f"{body}\n\nBest Regards,\n{sender_name}"
                    
                    # Create payload for Outlook
                    payload = {
                        "email": [recipient_email],
                        "subject": subject,
                        "body": body
                    }
                    
                    payloads.append(payload)
                    print(f"[DEBUG] Successfully added payload for {recipient_email}")
                    
                except Exception as e:
                    print(f"[DEBUG] Error processing email in lead_block: {str(e)}")
                    continue
                    
        except Exception as e:
            print(f"[DEBUG] Error processing lead_block: {str(e)}")
            continue
    
    print(f"[DEBUG] Total payloads prepared: {len(payloads)}")
    return payloads

def save_generated_emails_locally(emails, user_email):
    """Save generated emails to a local JSON file."""
    try:
        # Create emails directory if it doesn't exist
        if not os.path.exists('emails'):
            os.makedirs('emails')
            
        # Create a filename based on user email and timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"emails/{user_email.replace('@', '_at_')}_{timestamp}.json"
        
        # Save emails to file
        with open(filename, 'w') as f:
            json.dump(emails, f, indent=2)
            
        return filename
    except Exception as e:
        print(f"Error saving emails locally: {str(e)}")
        return None

def load_latest_generated_emails(user_email):
    """Load the most recent generated emails for a user."""
    try:
        # Get all email files for this user
        email_files = [f for f in os.listdir('emails') if f.startswith(user_email.replace('@', '_at_'))]
        
        if not email_files:
            return None
            
        # Sort by timestamp (newest first) and get the most recent
        latest_file = sorted(email_files)[-1]
        
        # Load the emails
        with open(f'emails/{latest_file}', 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading emails: {str(e)}")
        return None

def main():
    # Initialize session state for authentication
    if 'user_info' not in st.session_state:
        st.session_state['user_info'] = None
    if 'auth_checked' not in st.session_state:
        st.session_state.auth_checked = False
    if 'show_signature_form' not in st.session_state:
        st.session_state.show_signature_form = False

    # Check if we're in the callback
    if 'code' in st.query_params:
        code = st.query_params['code']
        # Check if this is an Outlook auth callback (state param)
        if 'state' in st.query_params and str(st.query_params['state']).startswith('outlook_auth'):
            from outlook_auth import handle_outlook_callback, load_code_verifier, load_outlook_token
            state = st.query_params['state']
            code_verifier = load_code_verifier(state)
            if not code_verifier:
                st.error("Outlook authentication failed: code verifier missing or expired. Please try signing in again.")
                st.query_params.clear()
                st.stop()
            
            outlook_token = load_outlook_token()
            if not outlook_token:
                st.warning("No Outlook token found. You may need to sign in again after authentication.")
            
            user_info = handle_outlook_callback(code)
            if user_info:
                st.query_params.clear()
                st.success("Outlook authentication successful!")
                st.rerun()
            else:
                st.error("Failed to authenticate with Outlook. Please try again.")
                st.stop()
        else:
            # Assume Google auth
            from auth import handle_auth_callback, load_google_token
            user_info = handle_auth_callback(code)
            # Always fetch the Google token file after callback
            credentials = load_google_token()
            if not credentials:
                st.error("Google authentication failed: token file missing or expired. Please try signing in again.")
                st.query_params.clear()
                st.stop()
            if user_info:
                st.session_state.user_info = user_info
                st.query_params.clear()
                st.success("Google authentication successful!")
                st.rerun()
            else:
                st.error("Failed to authenticate with Google. Please try again.")
                st.stop()

    # Check authentication status before showing any content
    from outlook_auth import load_outlook_token, is_outlook_authenticated
    from auth import load_google_token, is_authenticated
    outlook_token = load_outlook_token()
    google_token = load_google_token()
    outlook_ok = is_outlook_authenticated() and outlook_token is not None and 'access_token' in outlook_token
    google_ok = is_authenticated() and google_token is not None and st.session_state.get('user_info') is not None

    if not (google_ok or outlook_ok) or st.session_state.get("force_sign_in", False):
        st.session_state["force_sign_in"] = False
        handle_auth_flow()
        st.session_state['auth_checked'] = True
        st.stop()

    st.session_state['auth_checked'] = True

    # User is authenticated, show the main app
    st.title("LeadX- Discover, Enrich, Engage")
    from outlook_auth import get_outlook_name
    from auth import get_user_name, is_authenticated
    if is_authenticated() and st.session_state.get('user_info'):
        name = get_user_name()
        st.write(f"Welcome, {name if name else 'Google User'}")
    elif is_outlook_authenticated():
        name = get_outlook_name()
        st.write(f"Welcome, {name if name else 'Outlook User'}")
    else:
        st.error("Authentication error. Please sign in again.")
        st.session_state["force_sign_in"] = True
        st.rerun()

    # Sidebar: Show user info, my account, and logout button
    with st.sidebar:
        if is_authenticated():
            name = get_user_name()
            st.write(f"Signed in as: {name if name else 'Google User'}")
            st.write(f"Email: {get_user_email()}")
            if st.button("My account", key="user_panel_btn_google"):
                st.session_state['show_user_panel'] = True
            if st.button("Logout", key="sidebar_logout_btn_google"):
                st.session_state.user_info = None
                if 'credentials' in st.session_state:
                    st.session_state.credentials = None
                if 'gmail_service' in st.session_state:
                    st.session_state.gmail_service = None
                import os
                if os.path.exists('token.pickle'):
                    os.remove('token.pickle')
                if os.path.exists('google_token.pkl'):
                    os.remove('google_token.pkl')
                st.session_state['auth_checked'] = False
                st.rerun()
        elif is_outlook_authenticated():
            from outlook_auth import get_outlook_name, outlook_logout
            name = get_outlook_name()
            st.write(f"Signed in as: {name if name else 'Outlook User'}")
            st.write(f"Email: {get_outlook_email()}")
            if st.button("My account", key="user_panel_btn_outlook"):
                st.session_state['show_user_panel'] = True
            if st.button("Logout", key="sidebar_logout_btn_outlook"):
                outlook_logout()
                import os
                if os.path.exists('outlook_token.pkl'):
                    os.remove('outlook_token.pkl')
                st.session_state['auth_checked'] = False
                st.rerun()

    # Initialize session state for storing search results and enrichment data
    if 'search_results' not in st.session_state:
        st.session_state.search_results = None
    if 'enriched_data' not in st.session_state:
        st.session_state.enriched_data = None
    if 'search_completed' not in st.session_state:
        st.session_state.search_completed = False
    if 'enrichment_completed' not in st.session_state:
        st.session_state.enrichment_completed = False
    if 'product_details' not in st.session_state:
        st.session_state.product_details = None
    if 'mail_generation_completed' not in st.session_state:
        st.session_state.mail_generation_completed = False
    if 'generated_emails' not in st.session_state:
        st.session_state.generated_emails = []
    if 'email_sending_completed' not in st.session_state:
        st.session_state.email_sending_completed = False
    if 'email_sending_results' not in st.session_state:
        st.session_state.email_sending_results = None
    if 'selected_leads' not in st.session_state:
        st.session_state.selected_leads = set()

    # Product list
    PRODUCTS = [
        "Parchaa",
        "PredCo",
        "InvestorBase",
        "Sankalpam",
        "Opticall",
        "IndikaAI",
        "Flexibench",
        "InspireAI",
        "Insituate",
        "ChoiceAI"
    ]

    # Remove User Panel from sidebar options
    sidebar_options = [
        "People Search",
        "People Enrichment",
        "Mail Generation",
        "Send Emails",
        "Add Signature"
    ]
    selected_tab = st.sidebar.radio("Navigation", sidebar_options)

    # Show User Panel page if requested
    if st.session_state.get('show_user_panel', False):
        st.title("User Panel: Database Viewer")
        from mongodb_client import fetch_enriched_leads, fetch_generated_emails
        user_email = get_user_email()
        st.header("Your Enriched Leads")
        enriched_df = fetch_enriched_leads(user_email)
        if enriched_df is not None and not enriched_df.empty:
            st.dataframe(enriched_df)
        else:
            st.info("No enriched leads found for your account.")
        st.header("Your Generated Emails")
        emails_df = fetch_generated_emails(user_email)
        if emails_df is not None and not emails_df.empty:
            st.dataframe(emails_df)
        else:
            st.info("No generated emails found for your account.")
        if st.button("Back to Main App", key="back_to_main"):
            st.session_state['show_user_panel'] = False
            # Check if Outlook session is still valid after returning
            if is_outlook_authenticated() is False and get_outlook_email() is None:
                st.session_state["force_sign_in"] = True
            st.rerun()
        st.stop()

    # --- People Search Tab ---
    elif selected_tab == "People Search":
        st.title("People Search")
        tab1, tab2 = st.tabs(["People Search by Job Title", "People Search by Organization"])

        with tab1:
            with st.form("search_form_people_search"):
                with st.expander("Job Titles", expanded=True):
                    titles_input = st.text_input(
                        "Job Titles ",
                        help="Enter job titles separated by commas"
                    )
                    include_similar_titles = st.checkbox(
                        "Include Similar Titles",
                        value=False,
                        help="Include people with similar job titles in the search results"
                    )
                with st.expander("Location"):
                    locations_input = st.text_input(
                        "Locations (comma-separated)",
                        value="India",
                        help="Enter locations separated by commas"
                    )
                with st.expander("Industry"):
                    industries_input = st.text_input(
                        "Industries (comma-separated)",
                        help="Enter industries separated by commas"
                    )
                results_count = st.number_input(
                    "Results (number of people to fetch)",
                    min_value=1,
                    max_value=250,
                    value=5,
                    help="Number of people search results to return"
                )
                per_page = st.number_input(
                    "Results per page",
                    min_value=1,
                    max_value=100,
                    value=1,
                    help="Number of results to fetch per page from the API (pagination)"
                )
                submitted = st.form_submit_button("Search")
            if submitted:
                titles = [title.strip() for title in titles_input.split(",")]
                locations = [location.strip() for location in locations_input.split(",")]
                industries = [industry.strip() for industry in industries_input.split(",")]
                with st.spinner("Searching..."):
                    results = get_people_search_results(
                        person_titles=titles,
                        include_similar_titles=include_similar_titles,
                        person_locations=locations,
                        company_names=[],  # Organization name removed from search criteria
                        company_locations=locations,
                        company_industries=industries,
                        per_page=per_page,
                        page=results_count // per_page + (1 if results_count % per_page > 0 else 0)  # Calculate required pages
                    )
                    if results and isinstance(results, list) and len(results) > 0:
                        print("\n[DEBUG] Search Results Structure:")
                        print(f"Number of results: {len(results)}")
                        print(f"First result structure: {json.dumps(results[0], indent=2)}")
                        
                        st.session_state.search_results = results
                        st.session_state.search_completed = True
                        try:
                            # Convert the results to a more structured format
                            structured_results = []
                            for result in results:
                                # Handle both direct fields and nested fields
                                structured_result = {
                                    'ID': result.get('id', 'N/A'),
                                    'Name': f"{result.get('first_name', '')} {result.get('last_name', '')}".strip() or 'N/A',
                                    'Title': result.get('title', 'N/A'),
                                    'Email': result.get('email', 'N/A'),
                                    'Email Status': result.get('email_status', 'N/A'),
                                    'LinkedIn URL': result.get('linkedin_url', 'N/A'),
                                    'Organization': result.get('organization_name', 'N/A'),
                                    'Location': result.get('present_raw_address', 'N/A'),
                                    'City': result.get('city', 'N/A'),
                                    'State': result.get('state', 'N/A'),
                                    'Country': result.get('country', 'N/A')
                                }
                                structured_results.append(structured_result)
                            
                            df = pd.DataFrame(structured_results)
                            if not df.empty:
                                st.subheader("Search Results")
                                st.dataframe(df, use_container_width=True)
                                csv = df.to_csv(index=False)
                                st.download_button(
                                    label="Download Search Results as CSV",
                                    data=csv,
                                    file_name="apollo_search_results.csv",
                                    mime="text/csv"
                                )
                                st.write(f"Total results: {len(results)}")
                                st.success("Search completed! Proceed to the Enrichment tab to enrich these profiles.")
                            else:
                                st.info("No tabular data to display. Raw results:")
                                st.write(results)
                        except Exception as e:
                            st.error(f"Error displaying results as table: {e}")
                            st.info("Raw results:")
                            st.write(results)
                    else:
                        st.warning("No results found. Try adjusting your search criteria.")

        with tab2:
            
            # Step 1: Organization Search
            with st.form("org_search_form"):
                st.subheader("Search Organization")
                org_domain = st.text_input("Organization Domain", help="e.g. panscience.xyz")
                org_name = st.text_input("Organization Name", help="e.g. PanScience Innovations")
                org_submitted = st.form_submit_button("Search Organization")
            if org_submitted:
                org_payload = {
                    "q_organization_domains_list": [org_domain] if org_domain else [],
                    "q_organization_names_list": [org_name] if org_name else [],
                    "page": 1,
                    "per_page": 1
                }
                apollo_org_url = "https://api.apollo.io/api/v1/mixed_companies/search"
                headers = {
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                    "X-Api-Key": st.secrets["APOLLO_API_KEY"]
                }
                with st.spinner("Searching organizations..."):
                    try:
                        import requests
                        print(f"[ORG SEARCH] POST {apollo_org_url}\nHeaders: {headers}\nPayload: {org_payload}")
                        org_resp = requests.post(apollo_org_url, headers=headers, json=org_payload)
                        print(f"[ORG SEARCH] Status Code: {org_resp.status_code}")
                        print(f"[ORG SEARCH] Response: {org_resp.text}")
                        org_resp.raise_for_status()
                        org_data = org_resp.json()
                        # Use 'accounts' if 'organizations' is empty
                        orgs = org_data.get("organizations", [])
                        if not orgs and "accounts" in org_data:
                            orgs = org_data["accounts"]
                        if orgs:
                            org_df = pd.DataFrame([
                                {
                                    "organization_id": o.get("organization_id") or o.get("id"),
                                    "name": o.get("name"),
                                    "domain": o.get("domain") or o.get("primary_domain"),
                                    "industry": o.get("industry"),
                                    "website_url": o.get("website_url"),
                                    "linkedin_url": o.get("linkedin_url"),
                                    "city": o.get("city"),
                                    "state": o.get("state"),
                                    "country": o.get("country"),
                                    "founded_year": o.get("founded_year"),
                                    "num_contacts": o.get("num_contacts"),
                                } for o in orgs
                            ])
                            st.session_state["org_search_results"] = org_df
                            st.session_state["org_search_raw"] = orgs
                            st.subheader("Organization Search Results")
                            st.dataframe(org_df, use_container_width=True)
                            csv = org_df.to_csv(index=False)
                            st.download_button(
                                label="Download Organization Results as CSV",
                                data=csv,
                                file_name="apollo_organization_search.csv",
                                mime="text/csv"
                            )
                            org_options = org_df[["organization_id", "name"]].apply(lambda x: f"{x['name']} ({x['organization_id']})", axis=1).tolist()
                            selected_org = st.selectbox("Select Organization for People Search", org_options, key="org_selectbox")
                            selected_org_id = org_df.iloc[org_options.index(selected_org)]["organization_id"]
                            st.session_state["selected_org_id"] = selected_org_id
                        else:
                            st.warning("No organizations found for the given criteria.")
                    except Exception as e:
                        st.error(f"Error searching organizations: {e}")
            # Step 2: People Search by Organization
            if st.session_state.get("selected_org_id"):
                with st.form("people_search_by_org_form"):
                    st.subheader("Step 2: Search People in Organization")
                    job_titles = st.text_input("Job Titles (comma-separated)", help="e.g. CEO, CTO")
                    org_id = st.text_input("Organization ID", value=st.session_state["selected_org_id"], disabled=True)
                    results = st.number_input("Results (number of people to fetch)", min_value=1, max_value=100, value=10)
                    per_page = st.number_input("Results per page", min_value=1, max_value=100, value=10)
                    people_submitted = st.form_submit_button("Search People in Organization")
                if people_submitted:
                    apollo_people_url = "https://api.apollo.io/api/v1/mixed_people/search"
                    headers = {
                        "Content-Type": "application/json",
                        "Cache-Control": "no-cache",
                        "X-Api-Key": st.secrets["APOLLO_API_KEY"]
                    }
                    # Remove 'results' from payload, use only per_page and page
                    requested_results = int(results)
                    per_page_val = int(per_page)
                    all_people = []
                    page_num = 1
                    while len(all_people) < requested_results:
                        payload = {
                            "organization_ids": [st.session_state["selected_org_id"]],
                            "person_titles": [t.strip() for t in job_titles.split(",") if t.strip()],
                            "include_similar_titles": True,
                            "page": page_num,
                            "per_page": per_page_val
                        }
                        import requests
                        print(f"[PEOPLE SEARCH] POST {apollo_people_url}\nHeaders: {headers}\nPayload: {payload}")
                        people_resp = requests.post(apollo_people_url, headers=headers, json=payload)
                        print(f"[PEOPLE SEARCH] Status Code: {people_resp.status_code}")
                        print(f"[PEOPLE SEARCH] Response: {people_resp.text}")
                        people_resp.raise_for_status()
                        people_data = people_resp.json()
                        # Handle both 'contacts' and 'people' arrays
                        people = people_data.get('people', []) or people_data.get('contacts', [])
                        if not people:
                            break
                        all_people.extend(people)
                        if len(people) < per_page_val:
                            break
                        page_num += 1
                    # Truncate to requested_results
                    all_people = all_people[:requested_results]
                    if all_people:
                        people_df = pd.DataFrame([
                            {
                                "id": p.get("id"),
                                "name": f"{p.get('first_name', '')} {p.get('last_name', '')}",
                                "title": p.get("title"),
                                "email": p.get("email"),
                                "linkedin_url": p.get("linkedin_url"),
                                "organization_id": p.get("organization_id"),
                                "organization_name": p.get("organization", {}).get("name"),
                            } for p in all_people
                        ])
                        st.session_state["search_results"] = people_df.to_dict(orient="records")
                        st.session_state["search_completed"] = True
                        st.subheader("People Search Results")
                        st.dataframe(people_df, use_container_width=True)
                        csv = people_df.to_csv(index=False)
                        st.download_button(
                            label="Download People Results as CSV",
                            data=csv,
                            file_name="apollo_people_by_org_search.csv",
                            mime="text/csv"
                        )
                    else:
                        st.warning("No people found for the selected organization.")

    elif selected_tab == "People Enrichment":
        st.title("People Enrichment")
        st.write("Enrich your people search results with additional data.")
        # Only allow enrichment if search results exist
        if st.session_state.get("search_results"):
            # Create a DataFrame from search results for selection
            search_df = pd.DataFrame(st.session_state["search_results"])
            
            # Extract lead IDs correctly from search results
            lead_ids = []
            for lead in st.session_state["search_results"]:
                # Handle both direct ID and nested ID in organization
                lead_id = None
                
                # Try to get ID from different possible locations
                if isinstance(lead, dict):
                    # Direct ID
                    lead_id = lead.get('id')
                    
                    # If no direct ID, try organization ID
                    if not lead_id and 'organization' in lead:
                        lead_id = lead.get('organization', {}).get('id')
                    
                    # If still no ID, try organization_id field
                    if not lead_id:
                        lead_id = lead.get('organization_id')
                    
                    # If still no ID, try ID field
                    if not lead_id:
                        lead_id = lead.get('ID')
                
                if lead_id:
                    lead_ids.append(str(lead_id))
                    print(f"Found lead ID: {lead_id} from lead data: {lead}")
                else:
                    print(f"No valid ID found in lead data: {lead}")
            
            if not lead_ids:
                st.warning("No valid lead IDs found in search results.")
                return
                
            if st.button("Enrich People Data", key="enrich_btn"):
                with st.spinner("Enriching data, please wait..."):
                    print(f"Attempting to enrich {len(lead_ids)} leads with IDs: {lead_ids}")
                    enriched_df = get_people_data(lead_ids)
                    if not enriched_df.empty:
                        # Save enriched data to MongoDB for the current user
                        user_email = get_user_email()
                        from mongodb_client import save_enriched_data
                        save_enriched_data(enriched_df.to_dict('records'), user_email)
                        st.session_state["enriched_data"] = enriched_df
                        st.session_state["enrichment_completed"] = True
                        st.success("Enrichment complete!")
                        
                        # Display enriched data
                        st.subheader("Enriched Data")
                        st.dataframe(enriched_df, use_container_width=True)
                        
                        # Add download button
                        csv = enriched_df.to_csv(index=False)
                        st.download_button("Download Enriched Data as CSV", csv, "enriched_people.csv", "text/csv")
                    else:
                        st.warning("No enrichment data found.")
            # Show previously enriched data if available
            elif st.session_state.get("enriched_data") is not None:
                enriched_df = st.session_state["enriched_data"]
                st.subheader("Enriched Data")
                st.dataframe(enriched_df, use_container_width=True)
                
                # Add download button
                csv = enriched_df.to_csv(index=False)
                st.download_button("Download Enriched Data as CSV", csv, "enriched_people.csv", "text/csv")
        else:
            st.info("Please complete a People Search first.")

    elif selected_tab == "Mail Generation":
        st.title("Mail Generation")
        st.write("Generate personalized emails for your enriched leads, including follow-ups.")
        if st.session_state.get("enriched_data") is not None and not st.session_state["enriched_data"].empty:
            product = st.selectbox("Select Product", PRODUCTS)
            # Select follow-up intervals
            intervals = st.multiselect(
                "Select follow-up intervals (days after initial email)",
                options=[0, 3, 8, 17, 24, 30],
                default=[0, 3, 8, 17]
            )
            
            if st.button("Generate Emails"):
                with st.spinner("Generating emails, please wait..."):
                    from personalised_email import FOLLOWUP_PROMPTS, generate_email_for_single_lead_with_custom_prompt
                    product_details = get_product_details(product.lower())
                    
                    # Get all enriched leads
                    enriched_df = st.session_state["enriched_data"]
                    all_leads = enriched_df.to_dict(orient="records")
                    
                    logging.info(f"Generating emails for {len(all_leads)} leads with product: {product}")
                    
                    # Get user's signature
                    user_email = get_user_email()
                    signature = get_signature(user_email)
                    
                    all_generated_emails = []
                    for lead in all_leads:
                        lead_emails = []
                        for day in sorted(intervals):
                            prompt = FOLLOWUP_PROMPTS[day]
                            email = generate_email_for_single_lead_with_custom_prompt(
                                lead_details=lead,
                                product_details=product_details,
                                day=day,
                                product_name=product
                            )
                            
                            # Add signature if it exists
                            if signature:
                                body = email.get('body', '')
                                if body.strip().endswith("Best Regards,"):
                                    body = body.rstrip() + f"\n{signature['name']}\n{signature['company']}\n{signature['linkedin_url']}\n"
                                    email['body'] = body
                            
                            email["interval_day"] = day
                            lead_emails.append(email)
                            
                        all_generated_emails.append({
                            "lead_id": lead.get("id") or lead.get("lead_id"),
                            "lead_name": lead.get("name"),
                            "emails": lead_emails
                        })
                    
                    # Save generated emails both locally and to MongoDB
                    filename = save_generated_emails_locally(all_generated_emails, user_email)
                    if filename:
                        st.success(f"Emails saved locally to {filename}")
                    
                    # Save to MongoDB as well
                    save_generated_emails(all_generated_emails, user_email)
                    st.success("Emails saved to database")
                    
                    st.session_state["generated_emails"] = all_generated_emails
                    st.session_state["mail_generation_completed"] = True

            if st.session_state.get("generated_emails"):
                st.subheader("Generated Emails & Follow-ups Preview")
                email_cards_css = """
                <style>
                .followup-lead-block { background: #f8fafd; border-radius: 10px; margin-bottom: 18px; padding: 18px 20px; box-shadow: 0 1px 4px rgba(0,0,0,0.03); }
                .followup-lead-title { font-size: 18px; font-weight: 600; color: #1a237e; margin-bottom: 8px; }
                .followup-tab { margin-bottom: 10px; }
                .followup-email-body { background: #f0f1f5; border-radius: 6px; padding: 12px 14px; font-family: Menlo,Consolas,monospace,monospace; color: #222; font-size: 15px; white-space: pre-wrap; word-break: break-word; }
                .followup-email-meta { color: #555; font-size: 14px; margin-bottom: 4px; }
                </style>
                """
                st.markdown(email_cards_css, unsafe_allow_html=True)
                for lead_block in st.session_state["generated_emails"]:
                    st.markdown(f"<div class='followup-lead-block'>", unsafe_allow_html=True)
                    st.markdown(f"<div class='followup-lead-title'>{lead_block['lead_name']}</div>", unsafe_allow_html=True)
                    tabs = st.tabs([f"Day {email['interval_day']}" for email in lead_block["emails"]])
                    for idx, email in enumerate(lead_block["emails"]):
                        with tabs[idx]:
                            st.markdown(f"<div class='followup-email-meta'><b>To:</b> {email.get('recipient_email','')}</div>", unsafe_allow_html=True)
                            st.markdown(f"<div class='followup-email-meta'><b>Subject:</b> {email.get('subject','')}</div>", unsafe_allow_html=True)
                            st.markdown(f"<div style='margin-top:10px;'><b>Body:</b></div>", unsafe_allow_html=True)
                            st.markdown(f"<div class='followup-email-body'>{email.get('body','')}</div>", unsafe_allow_html=True)
                    st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("Please complete People Enrichment first.")

    elif selected_tab == "Send Emails":
        st.title("Send Emails")
        st.write("Send your generated emails in batches or schedule follow-ups.")
        
        if st.session_state.get("generated_emails"):
            enriched_data = st.session_state.get("enriched_data")
            if enriched_data is None or enriched_data.empty:
                # Try to fetch from MongoDB as fallback
                from mongodb_client import fetch_enriched_leads
                user_email = get_user_email()
                enriched_data = fetch_enriched_leads(user_email)
                if enriched_data is not None and not enriched_data.empty:
                    st.session_state["enriched_data"] = enriched_data
                    st.info("Enriched data loaded from database.")
                else:
                    st.warning("No enriched data found. Please complete enrichment before sending emails.")
                    return
            
            # Print debug info to terminal
            print("\n[DEBUG] === Email Sending Debug Info ===")
            print(f"Number of generated emails: {len(st.session_state['generated_emails'])}")
            print(f"Number of enriched leads: {len(enriched_data)}")
            #print("Generated emails structure:")
            if st.session_state['generated_emails']:
                # Convert ObjectId to string before JSON serialization
                sample_email = st.session_state['generated_emails'][0]
                if isinstance(sample_email.get('lead_id'), ObjectId):
                    sample_email['lead_id'] = str(sample_email['lead_id'])
                print(json.dumps(sample_email, indent=2, cls=MongoJSONEncoder))
            else:
                print("No emails")
            print("Enriched data columns:")
            print(enriched_data.columns.tolist())
            print("=====================================\n")
            
            if st.button("Send Emails Now", key="send_emails_btn"):
                with st.spinner("Sending emails, please wait..."):
                    # Initialize variables
                    immediate_payloads = []
                    followup_payloads = []
                    successful = 0
                    failed = 0
                    
                    # Get sender details first
                    if is_outlook_authenticated():
                        from outlook_sender import OutlookSender
                        sender = OutlookSender()
                        sender_email = get_outlook_email()
                        sender_name = get_outlook_name()
                    else:
                        from email_sender import EmailSender
                        sender = EmailSender()
                        sender_email = get_user_email()
                        sender_name = get_user_name()
                    
                    if not sender_email or not sender_name:
                        st.error("Could not get sender information. Please try logging in again.")
                        return
                    
                    # Get current time for scheduling
                    current_time = datetime.now()
                    
                    # Process each lead block
                    for lead_block in st.session_state["generated_emails"]:
                        try:
                            # Get lead data from enriched data
                            lead_id = lead_block.get("lead_id")
                            if not lead_id:
                                print("[DEBUG] No lead_id found in email data")
                                continue
                                
                            lead_data = st.session_state["enriched_data"][st.session_state["enriched_data"]['lead_id'] == lead_id]
                            if lead_data.empty:
                                print(f"[DEBUG] No matching lead data found for lead_id {lead_id}")
                                continue
                                
                            recipient_email = lead_data['email'].iloc[0]
                            
                            # Process each email in the lead_block
                            emails = lead_block.get("emails", [])
                            for email in emails:
                                try:
                                    # Get email content
                                    subject = email.get("subject", "")
                                    body = email.get("body", "")
                                    interval_day = email.get("interval_day", 0)
                                    
                                    if not all([recipient_email, subject, body]):
                                        print(f"[DEBUG] Skipping: missing required fields for lead_id {lead_id}")
                                        continue
                                    
                                    # Format the email body with proper closing
                                    if sender_name:
                                        # Remove any existing closings
                                        body = body.replace("Best regards,\n[Your Name]", "")
                                        body = body.replace("Best Regards,\n[Your Name]", "")
                                        body = body.replace("Best regards,", "")
                                        body = body.replace("Best Regards,", "")
                                        body = body.strip()
                                        
                                        # Add the properly formatted closing
                                        body = f"{body}\n\nBest Regards,\n{sender_name}"
                                    
                                    # Create payload
                                    payload = {
                                        "email": [recipient_email],
                                        "subject": subject,
                                        "body": body,
                                        "interval_day": interval_day
                                    }
                                    
                                    # Separate immediate and follow-up emails
                                    if interval_day == 0:
                                        immediate_payloads.append(payload)
                                    else:
                                        followup_payloads.append(payload)
                                    
                                    print(f"[DEBUG] Successfully prepared payload for {recipient_email} (day {interval_day})")
                                    
                                except Exception as e:
                                    print(f"[DEBUG] Error processing email in lead_block: {str(e)}")
                                    continue
                                    
                        except Exception as e:
                            print(f"[DEBUG] Error processing lead_block: {str(e)}")
                            continue
                    
                    # Check if we have any emails to send
                    if not immediate_payloads and not followup_payloads:
                        st.error("No valid email payloads to send")
                        return
                    
                    # Send immediate emails (day 0)
                    if immediate_payloads:
                        print(f"[DEBUG] Sending {len(immediate_payloads)} immediate emails")
                        if isinstance(sender, OutlookSender):
                            results = sender.send_email_batch(immediate_payloads)
                        else:
                            import asyncio
                            results = asyncio.run(sender.send_emails(immediate_payloads))
                        
                        # Update session state with results
                        st.session_state.email_sending_results = results
                        st.session_state.email_sending_completed = True
                        
                        # Display results
                        if results['successful'] > 0:
                            st.success(f"Successfully sent {results['successful']} immediate emails")
                        if results['failed'] > 0:
                            st.error(f"Failed to send {results['failed']} immediate emails")
                            for error in results['errors']:
                                st.error(error)
                    else:
                        st.warning("No immediate emails to send")
                    
                    # Schedule follow-up emails
                    if followup_payloads:
                        print(f"[DEBUG] Scheduling {len(followup_payloads)} follow-up emails")
                        from mongodb_client import schedule_followup_emails
                        from personalised_email import FOLLOWUP_PROMPTS
                        
                        # Group follow-ups by lead
                        followups_by_lead = {}
                        for payload in followup_payloads:
                            lead_email = payload['email'][0]
                            if lead_email not in followups_by_lead:
                                followups_by_lead[lead_email] = []
                            followups_by_lead[lead_email].append(payload)
                        
                        # Schedule follow-ups for each lead
                        for lead_email, lead_payloads in followups_by_lead.items():
                            # Create base payload
                            base_payload = {
                                "subject": lead_payloads[0]["subject"],
                                "body": lead_payloads[0]["body"]
                            }
                            
                            # Get intervals for this lead
                            intervals = [p["interval_day"] for p in lead_payloads]
                            
                            # Schedule the follow-ups
                            scheduled_ids = schedule_followup_emails(
                                lead_email=lead_email,
                                sender_email=sender_email,
                                sender_name=sender_name,
                                initial_time=current_time,
                                base_payload=base_payload,
                                prompts_by_day={day: FOLLOWUP_PROMPTS[day] for day in intervals},
                                intervals=intervals
                            )
                            
                            if scheduled_ids:
                                successful += 1
                            else:
                                failed += 1
                        
                        st.success(f"Successfully scheduled {successful} follow-up email sequences")
                        if failed > 0:
                            st.warning(f"Failed to schedule {failed} follow-up email sequences")
                    else:
                        st.info("No follow-up emails to schedule")

    # Add Signature page
    elif selected_tab == "Add Signature":
        st.title("Email Signature")
        
        # Get user email
        user_email = get_user_email()
        if not user_email:
            st.error("Please sign in to manage your signature.")
            return

        # Get existing signature if any
        existing_signature = get_signature(user_email)

        # Create form for signature
        with st.form("signature_form"):
            name = st.text_input("Your Name", value=existing_signature.get('name', '') if existing_signature else '')
            company = st.text_input("Your Company", value=existing_signature.get('company', '') if existing_signature else '')
            linkedin_url = st.text_input("Your LinkedIn Profile URL", value=existing_signature.get('linkedin_url', '') if existing_signature else '')
            
            submitted = st.form_submit_button("Save Signature")
            
            if submitted:
                if name and company and linkedin_url:
                    if save_signature(user_email, name, company, linkedin_url):
                        st.success("Signature saved successfully!")
                    else:
                        st.error("Failed to save signature. Please try again.")
                else:
                    st.error("Please fill in all fields.")

    # Home page
    elif selected_tab == "Home":
        st.title("Welcome to LeadX")
        st.write("Please use the sidebar to navigate through different features:")
        st.write("1. People Search - Find potential leads")
        st.write("2. People Enrichment - Get detailed information about leads")
        st.write("3. Mail Generation - Create personalized emails")
        st.write("4. Send Emails - Send or schedule your emails")
        st.write("5. Add Signature - Manage your email signature")

if __name__ == "__main__":
    main()




