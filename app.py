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
from mongodb_client import save_enriched_data, save_generated_emails, collection, generated_emails_collection, lead_exists
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

# Sidebar: Show user info and logout button
with st.sidebar:
    if is_authenticated():
        name = get_user_name()
        st.write(f"Signed in as: {name if name else 'Google User'}")
        if st.button("Logout", key="sidebar_logout_btn"):
            logout()
            st.query_params.clear()
            st.session_state["force_sign_in"] = True
            st.rerun()
    elif is_outlook_authenticated():
        from outlook_auth import get_outlook_name, outlook_logout
        name = get_outlook_name()
        st.write(f"Signed in as: {name if name else 'Outlook User'}")
        if st.button("Logout", key="sidebar_logout_btn"):
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

# Remove st.tabs and use sidebar navigation
sidebar_options = [
    "People Search",
    "People Enrichment",
    "Mail Generation",
    "Send Emails",
    "Database"
]
selected_tab = st.sidebar.radio("Navigation", sidebar_options)

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

# Remove st.tabs and tab variables, replace with sidebar logic
if selected_tab == "People Search":
    # --- People Search Tab ---
    st.title("People Search")
    with st.form("search_form_people_search"):
        with st.expander("Job Titles", expanded=True):
            titles_input = st.text_input(
                "Job Titles ",
                #value="Partner, Investor",
                help="Enter job titles separated by commas"
            )
            include_similar_titles = st.checkbox(
                "Include Similar Titles",
                value=False,
                help="Include people with similar job titles in the search results"
            )
        with st.expander("Organization Name"):
            organization_names_input = st.text_input(
                "Organization name (comma-separated)",
                help="Enter organization names separated by commas (optional)"
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
                #value="Venture Capital & Private Equity",
                help="Enter industries separated by commas"
            )
        results_count = st.number_input(
            "Results (number of people to fetch)",
            min_value=1,
            max_value=250,
            value=5,
            help="Number of people search results to return"
        )
        submitted = st.form_submit_button("Search")
    if submitted:
        titles = [title.strip() for title in titles_input.split(",")]
        locations = [location.strip() for location in locations_input.split(",")]
        industries = [industry.strip() for industry in industries_input.split(",")]
        organizations = [c.strip() for c in organization_names_input.split(",") if c.strip()]
        # Removed keywords
        with st.spinner("Searching..."):
            results = get_people_search_results(
                person_titles=titles,
                include_similar_titles=include_similar_titles,
                person_locations=locations,
                company_names=organizations,
                company_locations=locations,
                company_industries=industries,
                per_page=results_count,
                page=1
            )
            #print(f"[DEBUG] Results returned to UI: {len(results)}")
            #print(results)
            if results and isinstance(results, list) and len(results) > 0:
                st.session_state.search_results = results
                st.session_state.search_completed = True
                try:
                    df = pd.DataFrame(results)
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
elif selected_tab == "People Enrichment":
    st.title("People Enrichment")
    if not st.session_state.search_completed or not st.session_state.search_results:
        st.warning("Please complete the People Search step first.")
    else:
        if st.button("Enrich People Search Data"):
            with st.spinner("Enriching person data..."):
                # Fix: Use 'id' if 'lead_id' is missing in search results
                lead_ids = [lead.get('lead_id', lead.get('id')) for lead in st.session_state.search_results if lead.get('lead_id', lead.get('id'))]
                if not lead_ids:
                    st.error("No valid lead IDs found in search results. Please check your search results.")
                else:
                    st.info(f"Enriching {len(lead_ids)} leads. Sample IDs: {lead_ids[:5]}")
                    enriched_df = get_people_data(lead_ids)
                    if enriched_df is not None and not enriched_df.empty:
                        # Duplicates Detection
                        duplicate_mask = enriched_df.apply(lambda row: lead_exists(lead_id=row['lead_id'], email=row['email']), axis=1)
                        duplicates = enriched_df[duplicate_mask]
                        new_leads = enriched_df[~duplicate_mask]
                        if not duplicates.empty:
                            st.warning(f"{len(duplicates)} duplicate lead(s) detected and skipped. See below:")
                            st.dataframe(duplicates)
                        if not new_leads.empty:
                            from mongodb_client import save_enriched_data
                            save_enriched_data(new_leads.to_dict('records'))
                            st.session_state.enriched_data = new_leads
                            st.session_state.enrichment_completed = True
                            st.success("Enrichment complete! Proceed to the Mail Generation tab.")
                            # Reorder columns: Company name and Profile name first
                            display_cols = [
                                'organization',  # Company name
                                'name',          # Profile name
                            ] + [col for col in new_leads.columns if col not in ['organization', 'name']]
                            st.dataframe(new_leads[display_cols])
                        else:
                            st.session_state.enriched_data = None
                            st.session_state.enrichment_completed = False
                            st.error("All leads are duplicates. No new leads to enrich.")
                    else:
                        st.session_state.enriched_data = None
                        st.session_state.enrichment_completed = False
                        st.error("Could not enrich the person data. Please check your API key, network connection, and lead IDs. See terminal/logs for details.")
                        st.info(f"Tried to enrich {len(lead_ids)} leads. Sample IDs: {lead_ids[:5]}")
        elif st.session_state.enrichment_completed and st.session_state.enriched_data is not None:
            st.dataframe(st.session_state.enriched_data)
elif selected_tab == "Mail Generation":
    st.title("Mail Generation")
    if not st.session_state.enrichment_completed or st.session_state.enriched_data is None:
        st.warning("Please complete the People Enrichment step first.")
    else:
        st.subheader("Select Product for Mail Generation")
        selected_product = st.selectbox("Choose a product", options=PRODUCTS)
        if st.button("Generate Mail"):
            with st.spinner("Generating mail for the lead(s)..."):
                pipeline = EmailGenerationPipeline()
                leads = st.session_state.enriched_data.to_dict(orient="records")
                product_details = get_product_details(selected_product)
                generated_emails = []
                mail_logs = []
                for idx, lead in enumerate(leads):
                    try:
                        mail = pipeline.generate_email(lead, product_details, product_name=selected_product)
                        generated_emails.append(mail)
                        mail_logs.append(f"[SUCCESS] Mail generated for {lead.get('name', lead.get('email', 'Unknown'))}")
                    except Exception as e:
                        mail_logs.append(f"[ERROR] Failed for {lead.get('name', lead.get('email', 'Unknown'))}: {str(e)}")
                st.session_state.generated_emails = generated_emails
                st.session_state.mail_generation_completed = True
                # Save generated emails to MongoDB and print logs
                from mongodb_client import save_generated_emails
                save_generated_emails(generated_emails)
                st.success(f"Mail(s) generated for {len(generated_emails)} lead(s)! Proceed to the Send Emails tab.")
                # Print mail generation logs in the terminal only
                for log in mail_logs:
                    print(log)
        # Always show generated mails if available
        if st.session_state.mail_generation_completed and st.session_state.generated_emails:
            st.write("### Generated Mails")
            for idx, mail in enumerate(st.session_state.generated_emails):
                subject = mail['final_result']['subject']
                body = mail['final_result']['body']
                lead = st.session_state.enriched_data.iloc[idx].to_dict() if idx < len(st.session_state.enriched_data) else {}
                from_user = mail.get('from', '')
                user_name = mail.get('from_name', '') if mail.get('from_name', '') else ''
                with st.expander(subject):
                    st.write(f"**To:** {lead.get('email', '')}")
                    st.write(f"**From:** {from_user}")
                    st.write(f"**Subject:** {subject}")
                    # Ensure user's name is on the line after Best Regards, and do not print recipient's name
                    if "Best Regards," in body:
                        body_lines = body.splitlines()
                        new_body_lines = []
                        for i, line in enumerate(body_lines):
                            new_body_lines.append(line)
                            if line.strip() == "Best Regards,":
                                if user_name:
                                    new_body_lines.append(user_name)
                        body = "\n".join(new_body_lines)
                    st.write(f"**Body:**\n{body}")
elif selected_tab == "Send Emails":
    st.title(":mailbox_with_mail: Send Emails")
    st.markdown("""
    <style>
    .schedule-card {
        background: #f8f9fa;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }
    .stButton>button {
        font-size: 1.1rem;
        padding: 0.5rem 1.5rem;
        border-radius: 8px;
    }
    .option-label {
        font-weight: 600;
        color: #1a73e8;
    }
    </style>
    """, unsafe_allow_html=True)
    if not st.session_state.mail_generation_completed or not st.session_state.generated_emails:
        st.warning(":warning: Please complete the Mail Generation step first.")
    else:
        lead = st.session_state.enriched_data.iloc[0].to_dict()
        email = lead.get('email', '')
        subject = st.session_state.generated_emails[0]['final_result']['subject']
        body = st.session_state.generated_emails[0]['final_result']['body']
        with st.container():
            st.markdown('<div class="schedule-card">', unsafe_allow_html=True)
            st.markdown("#### :calendar: Schedule Email")
            st.markdown("<span class='option-label'>Choose when to send:</span>", unsafe_allow_html=True)
            schedule_option = st.radio(
                "",
                ("Send Now", "Send Tomorrow", "Send Day After Tomorrow", "Custom Date & Time"),
                horizontal=True,
                index=0,
                key="schedule_option_radio"
            )
            import datetime
            scheduled_time = None
            if schedule_option == "Send Tomorrow":
                scheduled_time = (datetime.datetime.now() + datetime.timedelta(days=1)).replace(second=0, microsecond=0)
            elif schedule_option == "Send Day After Tomorrow":
                scheduled_time = (datetime.datetime.now() + datetime.timedelta(days=2)).replace(second=0, microsecond=0)
            elif schedule_option == "Custom Date & Time":
                date = st.date_input(":date: Pick date", value=datetime.date.today(), key="custom_date_input")
                default_time = st.session_state.get('custom_time_default', (datetime.datetime.now() + datetime.timedelta(hours=1)).time())
                time_val = st.time_input(":alarm_clock: Pick time", value=default_time, key="custom_time_input")
                st.session_state['custom_time_default'] = time_val
                scheduled_time = datetime.datetime.combine(date, time_val)
                st.info(f"Selected: {scheduled_time.strftime('%A, %d %B %Y at %I:%M %p')}")
                print(f"[LOG] User selected custom scheduled time: {scheduled_time}")
                logging.info(f"[LOG] User selected custom scheduled time: {scheduled_time}")
            if schedule_option == "Send Now":
                scheduled_time = datetime.datetime.now()
            st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('<div style="margin-top:1.5rem"></div>', unsafe_allow_html=True)
        with st.expander(":mag: Preview Email", expanded=True):
            st.markdown(f"<b>To:</b> {email}", unsafe_allow_html=True)
            st.markdown(f"<b>Subject:</b> {subject}", unsafe_allow_html=True)
            st.markdown(f"<b>Body:</b><br><div style='background:#f4f6fb;padding:1rem;border-radius:8px;white-space:pre-wrap'>{body}</div>", unsafe_allow_html=True)
        st.markdown('<div style="margin-top:1.5rem"></div>', unsafe_allow_html=True)
        col1, col2 = st.columns([1,2])
        with col1:
            send_btn = st.button(
                ":rocket: Send/Schedule Email",
                use_container_width=True,
                key="send_schedule_btn"
            )
        with col2:
            if schedule_option != "Send Now":
                st.info("Your email will be sent automatically at the scheduled time. You can view scheduled emails in the database tab.")
        if send_btn:
            with st.spinner("Processing..."):
                if is_authenticated() or is_outlook_authenticated():
                    if schedule_option == "Send Now":
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
                            st.success(":white_check_mark: Email sent successfully!")
                    else:
                        from mongodb_client import save_scheduled_email
                        email_data = {
                            "email": [email],
                            "subject": subject,
                            "body": body,
                            "sender_email": get_outlook_email() if is_outlook_authenticated() else get_user_email(),
                            "sender_name": get_outlook_name() if is_outlook_authenticated() else get_user_name(),
                            "scheduled_time": scheduled_time,
                            "status": "pending"
                        }
                        save_scheduled_email(email_data)
                        print(f"[LOG] Email scheduled for {scheduled_time}")
                        logging.info(f"[LOG] Email scheduled for {scheduled_time}")
                        st.success(f":white_check_mark: Email scheduled for {scheduled_time.strftime('%A, %d %B %Y at %I:%M %p')}")
                else:
                    st.warning(":lock: Please sign in with Google or Outlook to send emails.")
elif selected_tab == "Database":
    st.title("Enriched Leads & Generated Emails")
    enriched_df = fetch_enriched_leads()
    emails_df = fetch_generated_emails()
    if enriched_df is not None and emails_df is not None:
        merged_df = pd.merge(enriched_df, emails_df, left_on='lead_id', right_on='lead_id', how='left', suffixes=('', '_email'))
        def extract_email_field(row, field):
            if isinstance(row.get('final_result'), dict):
                return row['final_result'].get(field, '')
            if field in row:
                return row[field]
            if f'{field}_email' in row:
                return row[f'{field}_email']
            return ''
        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
        filter_name = filter_col1.text_input("Filter by Name", "", key="db_filter_name")
        filter_email = filter_col2.text_input("Filter by Email", "", key="db_filter_email")
        filter_company = filter_col3.text_input("Filter by Organization", "", key="db_filter_company")
        filter_industry = filter_col4.text_input("Filter by Industry", "", key="db_filter_industry")
        filtered_df = merged_df.copy()
        if filter_name:
            filtered_df = filtered_df[filtered_df['name'].str.contains(filter_name, case=False, na=False)]
        if filter_email:
            filtered_df = filtered_df[filtered_df['email'].str.contains(filter_email, case=False, na=False)]
        if filter_company:
            filtered_df = filtered_df[filtered_df['organization'].str.contains(filter_company, case=False, na=False)]
        if filter_industry:
            filtered_df = filtered_df[filtered_df['company_industry'].str.contains(filter_industry, case=False, na=False)]
        st.write(f"Showing {len(filtered_df)} results after filtering.")
        st.write("### Delete Records")
        delete_indices = st.multiselect(
            "Select rows to delete (by index)",
            options=filtered_df.index.tolist(),
            format_func=lambda x: f"{filtered_df.loc[x, 'name']} ({filtered_df.loc[x, 'email']})"
        )
        if st.button("Delete Selected Records") and delete_indices:
            from mongodb_client import delete_lead_by_id
            deleted_count = 0
            for idx in delete_indices:
                lead_id = filtered_df.loc[idx, 'lead_id']
                if delete_lead_by_id(lead_id):
                    deleted_count += 1
            st.success(f"Deleted {deleted_count} record(s) from the database.")
            st.experimental_rerun()
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

# --- Pipeline Information Expander ---
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
            from auth import handle_auth_callback
            user_info = handle_auth_callback(code)
            if user_info:
                st.session_state.user_info = user_info
                st.query_params.clear()
                st.success("Google authentication successful!")
                st.rerun()
            else:
                st.error("Failed to authenticate with Google. Please try again.")
                st.stop()

    # Show user info for Google or Outlook
    # For Google: use session_state.user_info
    # For Outlook: use get_outlook_name/get_outlook_email (file-based)
    # REMOVE Google user info and logout button at the bottom
    # REMOVE Outlook user info and logout button at the bottom
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




