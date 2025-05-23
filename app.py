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
st.title("Apollo.io People Pipeline")

# Add user info and logout button in the sidebar
with st.sidebar:
    # Show the appropriate email based on authentication method
    user_email = get_user_email() if is_authenticated() else get_outlook_email()
    st.write(f"Signed in as: {user_email}")
    if st.button("Logout"):
        if is_authenticated():
            logout()
        # Clear query params to avoid invalid_grant error
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

# Function to get product details
def get_product_details(product_name):
    # Convert product name to lowercase for case-insensitive matching
    product_name = product_name.lower()
    
    # Get the product data directly from the dictionary
    try:
        # Find the matching product
        for key, value in product_database.items():
            if key.lower() == product_name:
                return value
    except Exception as e:
        st.error(f"Error getting product details: {str(e)}")
        return None
    
    return None
def json_default(obj):
    if isinstance(obj, bson.ObjectId):
        return str(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

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
                col1, col2 = st.columns(2)
                with col1:
                    st.button("Copy Email", key=f"copy_{idx}")
                with col2:
                    st.download_button(
                        label="Download Email as TXT",
                        data=f"Subject: {subject}\n\n{body}",
                        file_name=f"email_{row['lead_id']}.txt",
                        mime="text/plain",
                        key=f"download_{idx}"
                    )
    else:
        st.info("No enriched leads and generated emails found in the database.")

with tab1:
    st.title("Apollo.io People Search")
    st.write("Search for people using Apollo.io API")

    # Add clear button for search results
    if st.session_state.search_completed:
        if st.button("Clear Search Results"):
            st.session_state.search_results = None
            st.session_state.search_completed = False
            st.rerun()

    # Create input fields for search
    with st.form("search_form"):
        st.subheader("Search Criteria")
        titles_input = st.text_input(
            "Job Titles (comma-separated)",
            value="Partner, Investor",
            help="Enter job titles separated by commas"
        )
        
        # Add include similar titles checkbox
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
        # Process inputs
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
                # Store results in session state
                st.session_state.search_results = results
                st.session_state.search_completed = True
                
                # Convert results to DataFrame for display
                df = pd.DataFrame(results)
                column_order = ['id', 'name', 'title', 'company', 'email', 'email_status', 
                              'linkedin_url', 'location', 'page_number']
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
                
                # Download button for search results
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

with tab2:
    st.title("People Enrichment")
    
    # Add clear button for enrichment results
    if st.session_state.enrichment_completed:
        if st.button("Clear Enrichment Results"):
            st.session_state.enriched_data = None
            st.session_state.enrichment_completed = False
            st.rerun()
    
    if not st.session_state.search_completed:
        st.warning("Please complete the search first to get lead IDs for enrichment.")
    else:
        if not st.session_state.enrichment_completed:
            if st.button("Start Enrichment"):
                # Get all lead IDs from search results
                lead_ids = [result['id'] for result in st.session_state.search_results]
                
                # Process in batches of 10
                batch_size = 10
                enriched_data = []
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for i in range(0, len(lead_ids), batch_size):
                    batch = lead_ids[i:i + batch_size]
                    status_text.text(f"Processing batch {i//batch_size + 1} of {(len(lead_ids) + batch_size - 1)//batch_size}")
                    
                    # Get enriched data for batch
                    batch_df = get_people_data(batch)
                    if not batch_df.empty:
                        enriched_data.append(batch_df)
                    
                    # Update progress
                    progress = min((i + batch_size) / len(lead_ids), 1.0)
                    progress_bar.progress(progress)
                    
                    # Add a small delay to avoid rate limiting
                    time.sleep(1)
                
                # Combine all batch results
                if enriched_data:
                    final_df = pd.concat(enriched_data, ignore_index=True)
                    st.session_state.enriched_data = final_df
                    st.session_state.enrichment_completed = True

                    # Save enriched data to MongoDB Atlas
                    try:
                        data_dicts = final_df.to_dict('records')
                        inserted_ids = save_enriched_data(data_dicts)
                        st.success(f"Saved {len(inserted_ids)} records to MongoDB Atlas.")
                    except Exception as e:
                        st.error(f"Failed to save to MongoDB Atlas: {e}")

                    # Clear progress indicators
                    progress_bar.empty()
                    status_text.empty()
                    
                    st.success("Enrichment completed!")
                else:
                    st.error("No data was enriched. Please try again.")
        
        # Display enriched data if available
        if st.session_state.enrichment_completed and st.session_state.enriched_data is not None:
            st.subheader("Enriched Data")
            st.dataframe(
                st.session_state.enriched_data,
                use_container_width=True,
                column_config={
                    "name": st.column_config.TextColumn("Name", width="medium"),
                    "linkedin_url": st.column_config.LinkColumn("LinkedIn", width="medium"),
                    "title": st.column_config.TextColumn("Title", width="medium"),
                    "email_status": st.column_config.TextColumn("Email Status", width="small"),
                    "email": st.column_config.TextColumn("Email", width="medium"),
                    "organization": st.column_config.TextColumn("Organization", width="medium"),
                    "company_industry": st.column_config.TextColumn("Industry", width="medium"),
                    "company_keywords": st.column_config.TextColumn("Keywords", width="large"),
                    "company_website": st.column_config.LinkColumn("Website", width="medium"),
                    "company_linkedin": st.column_config.LinkColumn("Company LinkedIn", width="medium"),
                    "company_twitter": st.column_config.LinkColumn("Twitter", width="medium"),
                    "company_facebook": st.column_config.LinkColumn("Facebook", width="medium"),
                    "company_angellist": st.column_config.LinkColumn("AngelList", width="medium"),
                    "company_size": st.column_config.NumberColumn("Company Size", width="small"),
                    "company_founded_year": st.column_config.NumberColumn("Founded Year", width="small"),
                    "company_location": st.column_config.TextColumn("Location", width="medium"),
                    "education": st.column_config.TextColumn("Education", width="large"),
                    "experience": st.column_config.TextColumn("Experience", width="large")
                }
            )
            
            # Download button for enriched data
            csv = st.session_state.enriched_data.to_csv(index=False)
            st.download_button(
                label="Download Enriched Data as CSV",
                data=csv,
                file_name="apollo_enriched_data.csv",
                mime="text/csv"
            )

with tab3:
    st.title("Mail Generation")
    
    # Add clear button for mail generation results
    if st.session_state.mail_generation_completed:
        if st.button("Clear Generated Emails"):
            st.session_state.generated_emails = []
            st.session_state.mail_generation_completed = False
            st.rerun()
    
    # Add data source selection
    st.subheader("Select Data Source")
    data_source = st.radio(
        "Choose your data source",
        ["Use Enriched Data", "Upload New Leads Data"],
        help="Select whether to use the enriched data from previous steps or upload new leads data"
    )
    
    leads_data = None
    
    if data_source == "Use Enriched Data":
        if st.session_state.enrichment_completed and st.session_state.enriched_data is not None:
            st.success("Using enriched data from previous steps")
            # Convert enriched data to the required format
            enriched_df = st.session_state.enriched_data
            leads_data = enriched_df.to_dict('records')
            st.write("Preview of enriched data:")
            st.dataframe(enriched_df.head())
        else:
            st.warning("No enriched data available. Please complete the enrichment step first or choose to upload new leads data.")
            data_source = "Upload New Leads Data"
    
    if data_source == "Upload New Leads Data":
        # Add file upload section for direct processing
        st.subheader("Upload Leads Data")
        
        # Add template download button
        template_data = pd.DataFrame({
            'lead_id': ['example_id_1', 'example_id_2'],
            'name': ['John Doe', 'Jane Smith'],
            'title': ['CEO', 'CTO'],
            'organization': ['Tech Corp', 'Innovation Inc'],
            'headline': ['Technology Leader', 'Software Expert'],
            'education': ['MBA, Computer Science', 'PhD, Engineering'],
            'company_industry': ['Technology', 'Software'],
            'email': ['john@example.com', 'jane@example.com'],
            'linkedin_url': ['https://linkedin.com/in/johndoe', 'https://linkedin.com/in/janesmith'],
            'email_status': ['verified', 'verified'],
            'company_keywords': ['AI, ML', 'Cloud, DevOps'],
            'company_website': ['https://techcorp.com', 'https://innovationinc.com'],
            'company_linkedin': ['https://linkedin.com/company/techcorp', 'https://linkedin.com/company/innovationinc'],
            'company_twitter': ['https://twitter.com/techcorp', 'https://twitter.com/innovationinc'],
            'company_facebook': ['https://facebook.com/techcorp', 'https://facebook.com/innovationinc'],
            'company_angellist': ['https://angel.co/techcorp', 'https://angel.co/innovationinc'],
        })
        
        # Download template button
        template_csv = template_data.to_csv(index=False)
        st.download_button(
            label="Download Template CSV",
            data=template_csv,
            file_name="leads_template.csv",
            mime="text/csv"
        )
        
        # File uploader
        uploaded_file = st.file_uploader("Upload your leads CSV file", type=['csv'])
        
        if uploaded_file is not None:
            try:
                # Read the uploaded file
                df = pd.read_csv(uploaded_file)
                st.write("Preview of uploaded data:")
                st.dataframe(df.head())
                
                # Convert DataFrame to list of dictionaries
                leads_data = df.to_dict('records')
            except Exception as e:
                logger.error(f"Error processing uploaded file: {str(e)}")
                st.error(f"Error processing file: {str(e)}")
    
    # Add product selection dropdown
    st.subheader("Select Product")
    selected_product = st.selectbox(
        "Choose a product",
        options=PRODUCTS,
        help="Select the product you want to generate emails for"
    )
    
    # Get product details when a product is selected
    if selected_product:
        product_details = get_product_details(selected_product)
        if product_details:
            st.session_state.product_details = product_details
            logger.info(f"Selected product: {selected_product}")
        else:
            logger.error(f"Could not find details for product: {selected_product}")
            st.error(f"Could not find details for {selected_product}")
    
    # Generate emails button
    if leads_data and st.button("Generate Emails"):
        if not st.session_state.product_details:
            logger.error("No product selected")
            st.error("Please select a product first")
        else:
            with st.spinner("Generating emails..."):
                # Initialize email generation pipeline
                pipeline = EmailGenerationPipeline()
                
                # Get sender's information
                sender_name = get_user_name() or get_outlook_name() or ""
                
                # Generate emails for each lead
                generated_emails = []
                for lead in leads_data:
                    try:
                        logger.info(f"Generating email for lead: {lead.get('name', 'Unknown')}")
                        email = pipeline.generate_email(lead, st.session_state.product_details)
                        generated_emails.append(email)
                    except Exception as e:
                        logger.error(f"Error generating email for lead {lead.get('name', 'Unknown')}: {str(e)}")
                        st.error(f"Error generating email for lead {lead.get('name', 'Unknown')}: {str(e)}")
                
                if generated_emails:
                    st.session_state.generated_emails = generated_emails
                    st.session_state.mail_generation_completed = True
                    logger.info(f"Successfully generated {len(generated_emails)} emails")
                    st.success("Emails generated successfully!")

                    # Save generated emails to MongoDB Atlas
                    try:
                        inserted_ids = save_generated_emails(generated_emails)
                        logger.info(f"Saved {len(inserted_ids)} generated emails to MongoDB Atlas.")
                        st.success(f"Saved {len(inserted_ids)} generated emails to MongoDB Atlas.")
                    except Exception as e:
                        logger.error(f"Failed to save generated emails to MongoDB Atlas: {e}")
                        st.error(f"Failed to save generated emails to MongoDB Atlas: {e}")

                    # Display generated emails
                    st.subheader("Generated Emails")
                    for i, email in enumerate(generated_emails, 1):
                        with st.expander(f"Email {i} - {email.get('final_result', {}).get('subject', 'No Subject')}"):
                            # Try to get recipient email from the generated email dict first
                            recipient_email = email.get('recipient_email')
                            # Fallback: Try to get from enriched data using lead_id
                            if not recipient_email:
                                lead_id = email.get('lead_id')
                                if lead_id and st.session_state.enriched_data is not None:
                                    lead_data = st.session_state.enriched_data[st.session_state.enriched_data['lead_id'] == lead_id]
                                    if not lead_data.empty:
                                        recipient_email = lead_data['email'].iloc[0]
                            # Fallback: Try to get from any 'email' field directly
                            if not recipient_email:
                                recipient_email = email.get('email')
                            st.write("To:", recipient_email or "No recipient")
                            st.write("From:", get_user_email() or get_outlook_email() or "No sender")
                            st.write("Subject:", email.get('final_result', {}).get('subject', 'No subject'))
                            # Format the email body with the sender's name
                            body = email.get('final_result', {}).get('body', 'No body')
                            if not body.endswith('\n'):
                                body = f"{body}\n"
                            body = f"{body}{sender_name}"
                            st.write("Body:", body)
                    
                    # Download generated emails
                    emails_json = json.dumps(generated_emails, indent=2, default=json_default)
                    st.download_button(
                        label="Download Generated Emails",
                        data=emails_json,
                        file_name="generated_emails.json",
                        mime="application/json"
                    )
                else:
                    logger.error("No emails were generated")
                    st.error("No emails were generated. Please check your input data.")

with tab4:
    st.title("Send Emails")
    
    # Add clear button for email sending results
    if st.session_state.email_sending_completed:
        if st.button("Clear Email Sending Results"):
            st.session_state.email_sending_results = None
            st.session_state.email_sending_completed = False
            st.rerun()
    
    if not st.session_state.mail_generation_completed:
        st.warning("Please complete the mail generation first.")
    else:
        if not st.session_state.email_sending_completed:
            if st.button("Send Emails"):
                # Check if user is authenticated with either Gmail or Outlook
                if not (is_authenticated() or is_outlook_authenticated()):
                    st.error("Please sign in with either Google or Outlook to send emails.")
                    st.stop()
                
                # Prepare email payloads based on authentication method
                if is_outlook_authenticated():
                    logger.info("Using Outlook for email sending")
                    email_payloads = prepare_outlook_email_payloads(
                        st.session_state.generated_emails,
                        st.session_state.enriched_data
                    )
                    email_sender = OutlookSender()
                else:
                    logger.info("Using Gmail for email sending")
                    email_payloads = prepare_email_payloads(
                        st.session_state.generated_emails,
                        st.session_state.enriched_data
                    )
                    email_sender = EmailSender()
                
                if not email_payloads:
                    logger.error("No valid email payloads to send.")
                    st.error("No valid email payloads to send. Please check the logs for details.")
                    st.stop()
                
                # Send emails
                results = asyncio.run(email_sender.send_emails(email_payloads))
                
                st.session_state.email_sending_results = results
                st.session_state.email_sending_completed = True
                
                if results.get("error"):
                    st.error(f"Error sending emails: {results['error']}")
                else:
                    st.success(f"Emails sent successfully! Total emails: {results['total_emails']}")
                    if results['failed'] > 0:
                        st.warning(f"{results['failed']} emails failed to send. Check the logs for details.")
        else:
            st.success("Emails have been sent!")
            st.write(f"Total emails sent: {st.session_state.email_sending_results['total_emails']}")
            if st.session_state.email_sending_results.get('failed', 0) > 0:
                st.warning(f"{st.session_state.email_sending_results['failed']} emails failed to send.")

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
    # Initialize session state
    if 'user_info' not in st.session_state:
        st.session_state.user_info = None

    # Check if we're in the callback
    if 'code' in st.query_params:
        code = st.query_params['code']
        token_result = get_token_from_code(code)
        
        if 'access_token' in token_result:
            user_info = get_user_info(token_result['access_token'])
            st.session_state.user_info = user_info
            # Clear the URL parameters
            st.query_params.clear()
        else:
            st.error("Failed to get access token")

    if st.session_state.user_info:
        st.write("Welcome,", st.session_state.user_info.get('displayName', 'User'))
        st.write("Email:", st.session_state.user_info.get('userPrincipalName', ''))
        if st.button("Logout"):
            st.session_state.user_info = None
            st.rerun()

if __name__ == "__main__":
    main()




