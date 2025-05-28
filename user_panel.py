import streamlit as st
from mongodb_client import fetch_enriched_leads, fetch_generated_emails

st.set_page_config(page_title="User Panel - Database Viewer", layout="wide")
st.title("User Panel: Database Viewer")

# Authentication (replace with your actual logic)
def get_user_email():
    # Example: get from session or authentication
    return st.session_state.get("user_email", "test@example.com")

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
