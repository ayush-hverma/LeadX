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
                        st.markdown(f'<a href="{outlook_auth_url}" target="_blank"><button style="background-color: #0078D4; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; width: 100%;">Sign in with Outlook</button></a>', unsafe_allow_html=True)
                    else:
                        logger.error("Failed to generate Outlook auth URL - URL is None")
                        st.error("Failed to generate Outlook authentication URL.")
                except Exception as e:
                    logger.error(f"Error generating Outlook auth URL: {str(e)}", exc_info=True)
                    st.error(f"Outlook authentication error: {str(e)}")
        
        st.stop()

# Check if user is authenticated with either Google or Outlook
# Only check authentication once per rerun, and cache result in session state
if 'auth_checked' not in st.session_state or not st.session_state['auth_checked']:
    from outlook_auth import load_outlook_token
    from auth import load_google_token
    outlook_token = load_outlook_token()
    google_token = load_google_token()
    outlook_ok = is_outlook_authenticated() and outlook_token is not None and 'access_token' in outlook_token
    google_ok = is_authenticated() and google_token is not None
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
if is_authenticated():
    name = get_user_name()
    st.write(f"Welcome, {name if name else 'Google User'}")
else:
    name = get_outlook_name()
    st.write(f"Welcome, {name if name else 'Outlook User'}")

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

# Remove 'People Search by Organization' from sidebar_options
sidebar_options = [
    "People Search",
    "People Enrichment",
    "Mail Generation",
    "Send Emails"
]
selected_tab = st.sidebar.radio("Navigation", sidebar_options)

# Show User Panel page if requested
if st.session_state.get('show_user_panel', False):
    st.title("User Panel: Database Viewer")
    from mongodb_client import fetch_enriched_leads, fetch_generated_emails
    def get_user_email():
        return st.session_state.get("user_email") or (get_user_email() if is_authenticated() else get_outlook_email())
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
if selected_tab == "People Search":
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
                    page=1
                )
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
                "per_page": 10
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
                    people = people_data.get("people", [])
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
        lead_ids = [lead.get("id") or lead.get("lead_id") for lead in st.session_state["search_results"] if lead.get("id") or lead.get("lead_id")]
        if st.button("Enrich People Data", key="enrich_btn"):
            with st.spinner("Enriching data, please wait..."):
                enriched_df = get_people_data(lead_ids)
                if not enriched_df.empty:
                    # Save enriched data to MongoDB for the current user
                    user_email = get_user_email() if is_authenticated() else get_outlook_email()
                    from mongodb_client import save_enriched_data
                    save_enriched_data(enriched_df.to_dict('records'), user_email)
                    st.session_state["enriched_data"] = enriched_df
                    st.session_state["enrichment_completed"] = True
                    st.success("Enrichment complete!")
                    st.dataframe(enriched_df, use_container_width=True)
                    csv = enriched_df.to_csv(index=False)
                    st.download_button("Download Enriched Data as CSV", csv, "enriched_people.csv", "text/csv")
                else:
                    st.warning("No enrichment data found.")
        # Show previously enriched data if available
        elif st.session_state.get("enriched_data") is not None:
            st.dataframe(st.session_state["enriched_data"], use_container_width=True)
            csv = st.session_state["enriched_data"].to_csv(index=False)
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
        if st.button("Generate Emails", key="generate_emails_btn"):
            with st.spinner("Generating emails, please wait..."):
                from personalised_email import FOLLOWUP_PROMPTS, generate_email_for_single_lead_with_custom_prompt
                product_details = get_product_details(product.lower())
                leads = st.session_state["enriched_data"].to_dict(orient="records")
                all_generated_emails = []
                for lead in leads:
                    lead_emails = []
                    for day in sorted(intervals):
                        prompt = FOLLOWUP_PROMPTS[day]
                        email = generate_email_for_single_lead_with_custom_prompt(
                            lead_details=lead,
                            product_details=json.dumps(product_details),
                            custom_prompt=prompt,
                            product_name=product
                        )
                        email["interval_day"] = day
                        lead_emails.append(email)
                    all_generated_emails.append({
                        "lead_id": lead.get("id") or lead.get("lead_id"),
                        "lead_name": lead.get("name"),
                        "emails": lead_emails
                    })
                st.session_state["generated_emails"] = all_generated_emails
                st.session_state["mail_generation_completed"] = True
                # Save generated emails to MongoDB for the current user
                user_email = get_user_email() if is_authenticated() else get_outlook_email()
                from mongodb_client import save_generated_emails
                save_generated_emails(all_generated_emails, user_email)
                st.success("Email generation complete!")
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
            # Optionally, allow download as CSV/JSON
            # ...existing code for download if needed...
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
            user_email = get_user_email() if is_authenticated() else get_outlook_email()
            enriched_data = fetch_enriched_leads(user_email)
            if enriched_data is not None and not enriched_data.empty:
                st.session_state["enriched_data"] = enriched_data
                st.info("Enriched data loaded from database.")
            else:
                st.warning("No enriched data found. Please complete enrichment before sending emails.")
        payloads = prepare_email_payloads(st.session_state["generated_emails"], enriched_data)
        if st.button("Send Emails Now", key="send_emails_btn"):
            with st.spinner("Sending emails, please wait..."):
                sender = EmailSender()
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(sender.send_emails(payloads))
                st.session_state["email_sending_completed"] = True
                st.session_state["email_sending_results"] = result
                st.success(f"Emails sent! Successful: {result.get('successful', 0)}, Failed: {result.get('failed', 0)}")
        # --- Scheduled Email Worker UI ---
        st.subheader("Schedule Follow-up Emails")
        from mongodb_client import schedule_followup_emails
        from datetime import datetime, timedelta
        # User can pick intervals for follow-ups
        intervals = st.multiselect(
            "Select follow-up intervals (days after initial email)",
            options=[0, 3, 8, 17, 24, 30],
            default=[0, 3, 8, 17, ]
        )
        # Pick initial send time
        initial_time = st.date_input("Initial send date", value=datetime.now().date())
        initial_hour = st.number_input("Hour (24h)", min_value=0, max_value=23, value=9)
        initial_minute = st.number_input("Minute", min_value=0, max_value=59, value=0)
        # Schedule follow-ups
        if st.button("Schedule Follow-up Emails", key="schedule_followup_btn"):
            with st.spinner("Scheduling follow-up emails..."):
                user_email = get_user_email() if is_authenticated() else get_outlook_email()
                user_name = get_user_name() if is_authenticated() else get_outlook_name()
                for email in st.session_state["generated_emails"]:
                    lead_email = email.get("recipient_email") or email.get("email")
                    base_payload = {"lead_id": email.get("lead_id")}
                    # Use current time for initial send, then add intervals
                    send_time = datetime.combine(initial_time, datetime.min.time()) + timedelta(hours=initial_hour, minutes=initial_minute)
                    prompts_by_day = {i: "" for i in intervals}  # You can customize prompts if needed
                    schedule_followup_emails(
                        lead_email=lead_email,
                        sender_email=user_email,
                        sender_name=user_name,
                        initial_time=send_time,
                        base_payload=base_payload,
                        prompts_by_day=prompts_by_day,
                        intervals=intervals
                    )
                st.success("Follow-up emails scheduled! The background worker will send them automatically.")
        elif st.session_state.get("email_sending_results"):
            result = st.session_state["email_sending_results"]
            st.success(f"Emails sent! Successful: {result.get('successful', 0)}, Failed: {result.get('failed', 0)}")
        logger.info(f"Email sending results: {st.session_state.get('email_sending_results', {})}") 
    else:
        st.info("Please generate emails first.")

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


def main():
    # Initialize session state for Google only
    if 'user_info' not in st.session_state:
        st.session_state.user_info = None

    # Check if we're in the callback
    if 'code' in st.query_params:
        code = st.query_params['code']
        # Check if this is an Outlook auth callback (state param)
        if 'state' in st.query_params and str(st.query_params['state']).startswith('outlook_auth'):
            from outlook_auth import handle_outlook_callback, load_code_verifier, load_outlook_token
            state = st.query_params['state']
            code_verifier = load_code_verifier(state)
            outlook_token = load_outlook_token()
            if not code_verifier:
                st.error("Outlook authentication failed: code verifier missing or expired. Please try signing in again.")
                st.query_params.clear()
                st.stop()
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

if __name__ == "__main__":
    main()




