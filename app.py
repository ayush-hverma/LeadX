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
from personalised_email import product_database, generate_email_for_single_lead, generate_email_for_multiple_leads
from auth import init_auth, is_authenticated, get_google_auth_url, handle_auth_callback, get_user_email, get_user_name, logout, log_sign_in_attempt
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
from mongodb_client import save_enriched_data, save_generated_emails, collection, generated_emails_collection
import bson

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

def handle_auth_flow():
    """Handle the authentication flow."""
    # Check if we're handling the OAuth callback
    query_params = st.query_params
    if 'code' in query_params:
        code = query_params['code']
        logger.info(f"Received auth code: {code}")
        
        # Check if this is an Outlook auth callback
        if 'state' in query_params and query_params['state'] == 'outlook_auth':
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
                        st.markdown(f'<a href="{outlook_auth_url}" target="_blank"><button style="background-color: #0078D4; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; width: 100%;">Sign in with Outlook</button></a>', unsafe_allow_html=True)
                    else:
                        logger.error("Failed to generate Outlook auth URL - URL is None")
                        st.error("Failed to generate Outlook authentication URL.")
                except Exception as e:
                    logger.error(f"Error generating Outlook auth URL: {str(e)}", exc_info=True)
                    st.error(f"Outlook authentication error: {str(e)}")
        
        st.stop()

# Check if user is authenticated with either Google or Outlook
if not (is_authenticated() or is_outlook_authenticated()) or st.session_state.get("force_sign_in", False):
    st.session_state["force_sign_in"] = False
    handle_auth_flow()
    st.stop()

# User is authenticated, show the main app
st.title("LeadX- Discover, Enrich, Engage")
from outlook_auth import get_outlook_name
from auth import get_user_name, is_authenticated
if is_authenticated():
    name = get_user_name()
    st.write(f"Welcome, {name if name else 'Google User'}")
else:
    name = get_outlook_name()
    st.write(f"Welcome, {name if name else 'Outlook User'}")

# Remove sidebar user info and logout button
# Place logout button in the dashboard (main area)
if is_authenticated() or is_outlook_authenticated():
    if st.button("Logout", key="dashboard_logout_btn"):
        if is_authenticated():
            logout()
        elif is_outlook_authenticated():
            from outlook_auth import outlook_logout
            outlook_logout()
        st.query_params.clear()
        st.session_state["force_sign_in"] = True
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

# Product list
PRODUCTS = [
    "Parcha",
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

# Create tabs for different stages (now including Database)
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "People Search",
    "People Enrichment",
    "Mail Generation",
    "Send Emails",
    "Database"
])

from mongodb_client import collection, generated_emails_collection

def fetch_enriched_leads():
    try:
        leads = list(collection.find())
        return pd.DataFrame(leads) if leads else None
    except Exception as e:
        st.error(f"Error fetching enriched leads: {e}")
        return None

def fetch_generated_emails():
    try:
        emails = list(generated_emails_collection.find())
        return pd.DataFrame(emails) if emails else None
    except Exception as e:
        st.error(f"Error fetching generated emails: {e}")
        return None

with tab5:
    st.title("Enriched Leads & Generated Emails")
    enriched_df = fetch_enriched_leads()
    emails_df = fetch_generated_emails()
    if enriched_df is not None and emails_df is not None:
        # Merge on lead_id
        merged_df = pd.merge(enriched_df, emails_df, left_on='lead_id', right_on='lead_id', how='left', suffixes=('', '_email'))
        # Helper to extract subject/body from possibly-nested MongoDB structure
        def extract_email_field(row, field):
            # Try nested 'final_result' dict
            if isinstance(row.get('final_result'), dict):
                return row['final_result'].get(field, '')
            # Try flat key
            if field in row:
                return row[field]
            # Try with '_email' suffix
            if f'{field}_email' in row:
                return row[f'{field}_email']
            return ''
        # Search bar
        search_query = st.text_input("Search leads (name, email, company, subject, etc.)", "")
        if search_query:
            mask = (
                merged_df['name'].str.contains(search_query, case=False, na=False) |
                merged_df['email'].str.contains(search_query, case=False, na=False) |
                merged_df['organization'].str.contains(search_query, case=False, na=False) |
                merged_df.apply(lambda row: extract_email_field(row, 'subject'), axis=1).str.contains(search_query, case=False, na=False)
            )
            filtered_df = merged_df[mask]
        else:
            filtered_df = merged_df
        st.write(f"Showing {len(filtered_df)} results.")
        for idx, row in filtered_df.iterrows():
            with st.expander(f"{row['name']} - {row['organization']} ({row['email']})"):
                st.write(f"**Title:** {row.get('title', '')}")
                st.write(f"**Email Status:** {row.get('email_status', '')}")
                st.write(f"**LinkedIn:** {row.get('linkedin_url', '')}")
                st.write(f"**Company:** {row.get('organization', '')}")
                st.write(f"**Industry:** {row.get('company_industry', '')}")
                st.write(f"**Email:** {row.get('email', '')}")
                subject = extract_email_field(row, 'subject')
                body = extract_email_field(row, 'body')
                st.write(f"**Generated Email Subject:** {subject}")
                if subject or body:
                    if st.button("Show Generated Email", key=f"show_email_{idx}"):
                        st.write(f"**Subject:** {subject}")
                        st.write(f"**Body:**\n{body}")
    else:
        st.info("No enriched leads and generated emails found in the database.")

# --- People Search Tab ---
with tab1:
    st.title("People Search")
    with st.form("search_form_people_search"):
        st.subheader("Search Criteria")
        titles_input = st.text_input(
            "Job Titles (comma-separated)",
            value="Partner, Investor",
            help="Enter job titles separated by commas"
        )
        include_similar_titles = st.checkbox(
            "Include Similar Titles",
            value=False,
            help="Include people with similar job titles in the search results"
        )
        locations_input = st.text_input(
            "Locations (comma-separated)",
            value="India",
            help="Enter locations separated by commas"
        )
        industries_input = st.text_input(
            "Industries (comma-separated)",
            value="Venture Capital & Private Equity",
            help="Enter industries separated by commas"
        )
        col1, col2 = st.columns(2)
        with col1:
            per_page = st.number_input("Results per page", min_value=1, max_value=100, value=5)
        with col2:
            page = st.number_input("Page number", min_value=1, value=1)
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
                company_locations=locations,
                company_industries=industries,
                per_page=per_page,
                page=page
            )
            if results:
                st.session_state.search_results = results
                st.session_state.search_completed = True
                df = pd.DataFrame(results)
                column_order = ['id', 'name', 'title', 'company', 'email', 'email_status', 'linkedin_url', 'location', 'page_number']
                df = df[column_order]
                st.subheader("Search Results")
                st.dataframe(
                    df,
                    use_container_width=True,
                    column_config={
                        "id": st.column_config.TextColumn("Lead ID", width="medium"),
                        "name": st.column_config.TextColumn("Name", width="medium"),
                        "title": st.column_config.TextColumn("Title", width="medium"),
                        "company": st.column_config.TextColumn("Company", width="medium"),
                        "email": st.column_config.TextColumn("Email", width="medium"),
                        "email_status": st.column_config.TextColumn("Email Status", width="small"),
                        "linkedin_url": st.column_config.LinkColumn("LinkedIn", width="medium"),
                        "location": st.column_config.TextColumn("Location", width="medium"),
                        "page_number": st.column_config.NumberColumn("Page", width="small")
                    }
                )
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
                st.warning("No results found. Try adjusting your search criteria.")

# --- People Enrichment Tab ---
with tab2:
    st.title("People Enrichment")
    if not st.session_state.search_completed or not st.session_state.search_results:
        st.warning("Please complete the People Search step first.")
    else:
        if st.button("Enrich People Search Data"):
            with st.spinner("Enriching person data..."):
                lead_ids = [lead['lead_id'] for lead in st.session_state.search_results]
                enriched_df = get_people_data(lead_ids)
                if enriched_df is not None and not enriched_df.empty:
                    st.session_state.enriched_data = enriched_df
                    st.session_state.enrichment_completed = True
                    st.success("Enrichment complete! Proceed to the Mail Generation tab.")
                    st.dataframe(enriched_df)
                else:
                    st.session_state.enriched_data = None
                    st.session_state.enrichment_completed = False
                    st.error("Could not enrich the person data.")
        elif st.session_state.enrichment_completed and st.session_state.enriched_data is not None:
            st.dataframe(st.session_state.enriched_data)

# --- Mail Generation Tab ---
with tab3:
    st.title("Mail Generation")
    if not st.session_state.enrichment_completed or st.session_state.enriched_data is None:
        st.warning("Please complete the People Enrichment step first.")
    else:
        st.subheader("Select Product for Mail Generation")
        selected_product = st.selectbox("Choose a product", options=PRODUCTS)
        if st.button("Generate Mail"):
            with st.spinner("Generating mail for the lead..."):
                pipeline = EmailGenerationPipeline()
                lead = st.session_state.enriched_data.iloc[0].to_dict()
                product_details = get_product_details(selected_product)
                generated = pipeline.generate_email(lead, product_details)
                st.session_state.generated_emails = [generated]
                st.session_state.mail_generation_completed = True
                st.success("Mail generated! Proceed to the Send Emails tab.")
                st.write(f"**To:** {lead.get('email', '')}")
                st.write(f"**Subject:** {generated['final_result']['subject']}")
                st.write(f"**Body:**\n{generated['final_result']['body']}")
        elif st.session_state.mail_generation_completed and st.session_state.generated_emails:
            generated = st.session_state.generated_emails[0]
            lead = st.session_state.enriched_data.iloc[0].to_dict()
            st.write(f"**To:** {lead.get('email', '')}")
            st.write(f"**Subject:** {generated['final_result']['subject']}")
            st.write(f"**Body:**\n{generated['final_result']['body']}")

# --- Send Emails Tab ---
with tab4:
    st.title("Send Emails")
    if not st.session_state.mail_generation_completed or not st.session_state.generated_emails:
        st.warning("Please complete the Mail Generation step first.")
    else:
        lead = st.session_state.enriched_data.iloc[0].to_dict()
        email = lead.get('email', '')
        subject = st.session_state.generated_emails[0]['final_result']['subject']
        body = st.session_state.generated_emails[0]['final_result']['body']
        if st.button("Send Email"):
            with st.spinner("Sending email..."):
                if is_authenticated() or is_outlook_authenticated():
                    if is_outlook_authenticated():
                        email_payloads = [{
                            "email": [email],
                            "subject": subject,
                            "body": body,
                            "sender_email": get_outlook_email(),
                            "sender_name": get_outlook_name()
                        }]
                        email_sender = OutlookSender()
                    else:
                        email_payloads = [{
                            "email": [email],
                            "subject": subject,
                            "body": body,
                            "sender_email": get_user_email(),
                            "sender_name": get_user_name()
                        }]
                        email_sender = EmailSender()
                    results = asyncio.run(email_sender.send_emails(email_payloads))
                    if results.get("error"):
                        st.error(f"Error sending email: {results['error']}")
                    else:
                        st.success("Email sent successfully!")
                else:
                    st.warning("Please sign in with Google or Outlook to send emails.")

# Update pipeline information
with st.expander("Pipeline Information"):
    st.write("""
    This pipeline consists of three stages:
    
    1. **People Search**
       - Search for people using job titles, locations, and industries
       - Results include basic profile information
       - Download search results as CSV
    
    2. **People Enrichment**
       - Enrich the found profiles with additional data
       - Process lead IDs in batches of 10
       - Get detailed information including industry and keywords
       - Download enriched data as CSV
    
    3. **Mail Generation**
       - Upload product information document
       - Generate personalized emails for each lead
       - View and download generated emails
       - Process leads in batches with retry logic
    
    Note: Each stage must be completed in sequence. The enrichment and mail generation processes may take some time as they process profiles in batches.
    """)

@app.route('/api/generate-email', methods=['POST'])
def generate_email():
    try:
        data = request.get_json()
        leads = data.get('leads', [])
        product = data.get('product', '')
        
        if not leads or not product:
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Get product details from the database
        product_details = product_database.get(product.lower())
        if not product_details:
            return jsonify({'error': 'Invalid product'}), 400
        
        # Convert product details to string format
        product_details_str = json.dumps(product_details)
        
        # Generate emails for all leads
        generated_emails = generate_email_for_multiple_leads(leads, product_details_str)
        
        return jsonify({
            'emails': generated_emails
        })
        
    except Exception as e:
        print(f"Error generating email: {str(e)}")
        return jsonify({'error': str(e)}), 500


def main():
    # Initialize session state for Google only
    if 'user_info' not in st.session_state:
        st.session_state.user_info = None

    # Check if we're in the callback
    if 'code' in st.query_params:
        code = st.query_params['code']
        # Check if this is an Outlook auth callback (state param)
        if 'state' in st.query_params and st.query_params['state'] == 'outlook_auth':
            user_info = handle_outlook_callback(code)
            # handle_outlook_callback already saves the token to file
            # and returns user_info if successful
            if user_info:
                st.query_params.clear()
                st.success("Outlook authentication successful!")
                st.rerun()
            else:
                st.error("Failed to authenticate with Outlook. Please try again.")
                st.stop()
        else:
            # Assume Google auth
            token_result = get_token_from_code(code)
            if 'access_token' in token_result:
                user_info = get_user_info(token_result['access_token'])
                st.session_state.user_info = user_info
                st.query_params.clear()
                st.success("Google authentication successful!")
                st.rerun()
            else:
                st.error("Failed to get access token")
                st.stop()

    # Show user info for Google or Outlook
    # For Google: use session_state.user_info
    # For Outlook: use get_outlook_name/get_outlook_email (file-based)
    if is_authenticated() and st.session_state.user_info:
        st.write("Welcome,", st.session_state.user_info.get('name', 'User'))
        st.write("Email:", st.session_state.user_info.get('email', ''))
        if st.button("Logout"):
            st.session_state.user_info = None
            st.rerun()
    elif is_outlook_authenticated():
        from outlook_auth import get_outlook_name, get_outlook_email
        name = get_outlook_name()
        email = get_outlook_email()
        # Removed duplicate 'Signed in as' lines at the bottom of the dashboard
        # Only show Outlook info if authenticated with Outlook
        if is_outlook_authenticated():
            # Clean up any Google session state and token file BEFORE fetching Outlook email
            for k in ["user_info", "credentials", "gmail_service"]:
                if k in st.session_state:
                    st.session_state[k] = None
            import os
            if os.path.exists('token.pickle'):
                os.remove('token.pickle')
            if os.path.exists('google_token.pkl'):
                os.remove('google_token.pkl')
            user_email = None
            from outlook_auth import get_outlook_email
            if hasattr(st.session_state, 'user_info'):
                st.session_state.user_info = None
            user_email = get_outlook_email()  # Only Outlook email
            # Removed duplicate 'Signed in as' lines

if __name__ == "__main__":
    main()




