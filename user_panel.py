import streamlit as st
from mongodb_client import fetch_enriched_leads, fetch_generated_emails, delete_lead_by_id, delete_email_by_id, search_enriched_leads
import pandas as pd
import requests

st.set_page_config(page_title="User Panel - Database Viewer", layout="wide")

# Custom CSS for a cleaner UI
st.markdown("""
<style>
    .stButton button {
        padding: 0.2rem 0.5rem;
        font-size: 0.8rem;
    }
    .search-container {
        display: flex;
        gap: 1rem;
        align-items: center;
        margin-bottom: 1rem;
    }
    .filter-container {
        display: flex;
        gap: 0.5rem;
        flex-wrap: wrap;
        margin-bottom: 1rem;
    }
    .delete-btn {
        color: #ff4b4b;
        background: none;
        border: none;
        cursor: pointer;
        padding: 0.2rem;
    }
    .delete-btn:hover {
        color: #ff0000;
    }
    .stDataFrame {
        font-size: 0.9rem;
    }
    .stDataFrame td {
        padding: 0.3rem !important;
    }
</style>
""", unsafe_allow_html=True)

# Authentication (replace with your actual logic)
def get_user_email():
    # Example: get from session or authentication
    return st.session_state.get("user_email", "test@example.com")

user_email = get_user_email()

# Enriched Leads Section
st.header("Your Enriched Leads")

# Search and Filter UI
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    search_term = st.text_input("🔍 Search", placeholder="Search by name, email, company...")
with col2:
    industry_filter = st.selectbox("🏢 Industry", ["All"] + list(pd.unique(fetch_enriched_leads(user_email)['company_industry'].dropna())) if fetch_enriched_leads(user_email) is not None else ["All"])
with col3:
    title_filter = st.selectbox("👔 Title", ["All"] + list(pd.unique(fetch_enriched_leads(user_email)['title'].dropna())) if fetch_enriched_leads(user_email) is not None else ["All"])

# Apply filters
filters = {}
if industry_filter != "All":
    filters['company_industry'] = industry_filter
if title_filter != "All":
    filters['title'] = title_filter

# Fetch and display leads
enriched_df = search_enriched_leads(user_email, search_term, filters)
if enriched_df is not None and not enriched_df.empty:
    # Add delete buttons to each row
    enriched_df['Actions'] = enriched_df['lead_id'].apply(
        lambda x: f'<button class="delete-btn" onclick="deleteLead(\'{x}\')">🗑️</button>'
    )
    
    # Select columns to display
    display_columns = ['name', 'email', 'title', 'organization', 'company_industry', 'Actions']
    display_df = enriched_df[display_columns].copy()
    
    # Display the dataframe
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Actions": st.column_config.Column(
                "Actions",
                width="small",
                help="Delete lead",
                unsafe_allow_html=True
            ),
            "name": st.column_config.Column("Name", width="medium"),
            "email": st.column_config.Column("Email", width="medium"),
            "title": st.column_config.Column("Title", width="medium"),
            "organization": st.column_config.Column("Company", width="medium"),
            "company_industry": st.column_config.Column("Industry", width="medium")
        }
    )
    
    # Add JavaScript for delete functionality
    st.markdown("""
    <script>
    function deleteLead(leadId) {
        if (confirm('Are you sure you want to delete this lead?')) {
            fetch('/delete_lead', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({lead_id: leadId})
            }).then(response => response.json())
            .then(data => {
                if (data.message) {
                    window.location.reload();
                } else {
                    alert('Error deleting lead: ' + data.error);
                }
            });
        }
    }
    </script>
    """, unsafe_allow_html=True)
else:
    st.info("No enriched leads found for your account.")

# Generated Emails Section
st.header("Your Generated Emails")
emails_df = fetch_generated_emails(user_email)
if emails_df is not None and not emails_df.empty:
    # Add delete buttons to each row
    emails_df['Actions'] = emails_df['_id'].apply(
        lambda x: f'<button class="delete-btn" onclick="deleteEmail(\'{x}\')">🗑️</button>'
    )
    
    # Select columns to display
    display_columns = ['lead_name', 'subject', 'interval_day', 'Actions']
    display_df = emails_df[display_columns].copy()
    
    # Display the dataframe
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Actions": st.column_config.Column(
                "Actions",
                width="small",
                help="Delete email",
                unsafe_allow_html=True
            ),
            "lead_name": st.column_config.Column("Lead Name", width="medium"),
            "subject": st.column_config.Column("Subject", width="large"),
            "interval_day": st.column_config.Column("Day", width="small")
        }
    )
    
    # Add JavaScript for delete functionality
    st.markdown("""
    <script>
    function deleteEmail(emailId) {
        if (confirm('Are you sure you want to delete this email?')) {
            fetch('/delete_email', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({email_id: emailId})
            }).then(response => response.json())
            .then(data => {
                if (data.message) {
                    window.location.reload();
                } else {
                    alert('Error deleting email: ' + data.error);
                }
            });
        }
    }
    </script>
    """, unsafe_allow_html=True)
else:
    st.info("No generated emails found for your account.")
