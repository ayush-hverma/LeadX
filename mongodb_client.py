from pymongo import MongoClient
import os
import streamlit as st
import logging
from datetime import datetime, timedelta

# Try to get MongoDB URI from Streamlit secrets, fallback to environment variable
MONGODB_URI = ""
if not MONGODB_URI:
    raise ValueError("MongoDB URI not found in Streamlit secrets or environment variables.")

client = MongoClient(MONGODB_URI)
db = client['LeadX']  # Use your database name
collection = db['enriched_leads']  # Use your collection name
generated_emails_collection = db['generated_emails']  # Use your collection name
scheduled_emails_collection = db['scheduled_emails']  # New collection for scheduled emails
signatures_collection = db['signatures']  # New collection for user signatures

def save_enriched_data(data, user_email):
    """
    Save a single enriched data dictionary or a list of dictionaries to MongoDB Atlas, tagged with user_email.
    """
    try:
        if isinstance(data, list):
            for d in data:
                d['user_email'] = user_email
            result = collection.insert_many(data)
            logging.info(f"[MongoDB] Saved {len(result.inserted_ids)} enriched records for {user_email}: {result.inserted_ids}")
            print(f"[MongoDB] Saved {len(result.inserted_ids)} enriched records for {user_email}: {result.inserted_ids}")
            return result.inserted_ids
        else:
            data['user_email'] = user_email
            result = collection.insert_one(data)
            logging.info(f"[MongoDB] Saved 1 enriched record for {user_email}: {result.inserted_id}")
            print(f"[MongoDB] Saved 1 enriched record for {user_email}: {result.inserted_id}")
            return result.inserted_id
    except Exception as e:
        logging.error(f"[MongoDB] Failed to save enriched data for {user_email}: {e}")
        print(f"[MongoDB] Failed to save enriched data for {user_email}: {e}")
        return None

def save_generated_emails(emails, user_email):
    """
    Save a single generated email dictionary or a list of dictionaries to MongoDB Atlas, tagged with user_email.
    """
    try:
        if isinstance(emails, list):
            for e in emails:
                e['user_email'] = user_email
            result = generated_emails_collection.insert_many(emails)
            logging.info(f"[MongoDB] Saved {len(result.inserted_ids)} generated emails for {user_email}: {result.inserted_ids}")
            print(f"[MongoDB] Saved {len(result.inserted_ids)} generated emails for {user_email}: {result.inserted_ids}")
            return result.inserted_ids
        else:
            emails['user_email'] = user_email
            result = generated_emails_collection.insert_one(emails)
            logging.info(f"[MongoDB] Saved 1 generated email for {user_email}: {result.inserted_id}")
            print(f"[MongoDB] Saved 1 generated email for {user_email}: {result.inserted_id}")
            return result.inserted_id
    except Exception as e:
        logging.error(f"[MongoDB] Failed to save generated emails for {user_email}: {e}")
        print(f"[MongoDB] Failed to save generated emails for {user_email}: {e}")
        return None

def lead_exists(lead_id=None, email=None):
    """
    Check if a lead already exists in the database by lead_id or email.
    Returns True if exists, False otherwise.
    """
    query = {}
    if lead_id:
        query['lead_id'] = lead_id
    if email:
        query['email'] = email
    if not query:
        return False
    return collection.count_documents(query) > 0

def delete_lead_by_id(lead_id, user_email):
    """
    Delete a specific lead from MongoDB by its lead_id and user_email.
    Returns True if deleted, False otherwise.
    """
    try:
        result = collection.delete_one({'lead_id': lead_id, 'user_email': user_email})
        logging.info(f"[MongoDB] Deleted lead {lead_id} for user {user_email}")
        return result.deleted_count > 0
    except Exception as e:
        logging.error(f"Error deleting lead with lead_id {lead_id}: {e}")
        return False

def delete_lead_by_email(email):
    """
    Delete a lead from MongoDB by its email.
    Returns True if deleted, False otherwise.
    """
    try:
        result = collection.delete_one({'email': email})
        return result.deleted_count > 0
    except Exception as e:
        print(f"Error deleting lead with email {email}: {e}")
        return False

def delete_email_by_id(email_id, user_email):
    """
    Delete a specific generated email from MongoDB by its _id and user_email.
    Returns True if deleted, False otherwise.
    """
    try:
        from bson.objectid import ObjectId
        result = generated_emails_collection.delete_one({'_id': ObjectId(email_id), 'user_email': user_email})
        logging.info(f"[MongoDB] Deleted email {email_id} for user {user_email}")
        return result.deleted_count > 0
    except Exception as e:
        logging.error(f"Error deleting email with id {email_id}: {e}")
        return False

def save_scheduled_email(email_data):
    """
    Save a scheduled email to MongoDB Atlas.
    """
    result = scheduled_emails_collection.insert_one(email_data)
    return result.inserted_id

def get_due_scheduled_emails(current_time):
    """
    Retrieve all scheduled emails that are due to be sent (scheduled_time <= current_time and status == 'pending').
    """
    return list(scheduled_emails_collection.find({
        'scheduled_time': {'$lte': current_time},
        'status': 'pending'
    }))

def mark_email_as_sent(email_id):
    """
    Mark a scheduled email as sent.
    """
    scheduled_emails_collection.update_one({'_id': email_id}, {'$set': {'status': 'sent'}})

def schedule_followup_emails(lead_email: str, base_payload: dict, followup_days: list, user_email: str):
    """
    Schedule follow-up emails for a lead.
    """
    try:
        # Get the lead's company name
        lead = collection.find_one({"email": lead_email})
        company_name = lead.get('company', 'your company') if lead else 'your company'
        
        # Get product name from the base payload
        product_name = base_payload.get("product_name", "our product")
        
        # Create follow-up subject
        followup_subject = f"Follow-up: {product_name} for {company_name}"
        
        # Schedule each follow-up email
        for day in followup_days:
            scheduled_time = datetime.now() + timedelta(days=day)
            
            # Create the email payload
            email_payload = {
                "email": base_payload["email"],
                "subject": followup_subject if day > 0 else base_payload.get("subject", ""),
                "body": base_payload["body"],
                "sender_email": base_payload["sender_email"],
                "sender_name": base_payload["sender_name"],
                "scheduled_time": scheduled_time,
                "followup_day": 0 if is_development else day,
                "status": "scheduled",
                "lead_id": base_payload.get("lead_id", ""),
                "lead_name": base_payload.get("lead_name", ""),
                "user_email": user_email
            }
            
            # Insert into scheduled_emails collection
            scheduled_emails_collection.insert_one(email_payload)
            
        return True
    except Exception as e:
        logging.error(f"Error scheduling follow-up emails: {e}")
        return False

def fetch_scheduled_emails(user_email):
    """
    Fetch scheduled emails for the specific user.
    """
    return list(scheduled_emails_collection.find({'user_email': user_email}))

def fetch_enriched_leads(user_email):
    """
    Fetch enriched leads for the specific user.
    """
    try:
        leads = list(collection.find({'user_email': user_email}))
        import pandas as pd
        return pd.DataFrame(leads) if leads else None
    except Exception as e:
        import streamlit as st
        st.error(f"Error fetching enriched leads: {e}")
        return None

def fetch_generated_emails(user_email):
    """
    Fetch generated emails for the specific user.
    """
    try:
        emails = list(generated_emails_collection.find({'user_email': user_email}))
        import pandas as pd
        return pd.DataFrame(emails) if emails else None
    except Exception as e:
        import streamlit as st
        st.error(f"Error fetching generated emails: {e}")
        return None

def delete_all_enriched_leads(user_email):
    """
    Delete all enriched leads for the specific user from MongoDB.
    Returns the number of documents deleted.
    """
    try:
        result = collection.delete_many({'user_email': user_email})
        logging.info(f"[MongoDB] Deleted {result.deleted_count} enriched leads for {user_email}.")
        return result.deleted_count
    except Exception as e:
        print(f"Error deleting all enriched leads for {user_email}: {e}")
        return 0

def delete_all_generated_emails(user_email):
    """
    Delete all generated emails for the specific user from MongoDB.
    Returns the number of documents deleted.
    """
    try:
        result = generated_emails_collection.delete_many({'user_email': user_email})
        logging.info(f"[MongoDB] Deleted {result.deleted_count} generated emails for {user_email}.")
        return result.deleted_count
    except Exception as e:
        print(f"Error deleting all generated emails for {user_email}: {e}")
        return 0

def search_enriched_leads(user_email, search_term=None, filters=None):
    """
    Search enriched leads with optional filters.
    
    Args:
        user_email (str): The user's email
        search_term (str): Optional search term to match against name, email, organization, etc.
        filters (dict): Optional dictionary of filters (e.g., {'company_industry': 'Technology'})
    
    Returns:
        pandas.DataFrame: Filtered leads data
    """
    try:
        query = {'user_email': user_email}
        
        if search_term:
            # Create a text search query
            text_query = {
                '$or': [
                    {'name': {'$regex': search_term, '$options': 'i'}},
                    {'email': {'$regex': search_term, '$options': 'i'}},
                    {'organization': {'$regex': search_term, '$options': 'i'}},
                    {'title': {'$regex': search_term, '$options': 'i'}},
                    {'company_industry': {'$regex': search_term, '$options': 'i'}},
                    {'company_location': {'$regex': search_term, '$options': 'i'}}
                ]
            }
            query.update(text_query)
        
        if filters:
            for key, value in filters.items():
                if value and value != "All":  # Only add non-empty filters
                    query[key] = {'$regex': value, '$options': 'i'}
        
        leads = list(collection.find(query))
        import pandas as pd
        df = pd.DataFrame(leads) if leads else None
        
        if df is not None and not df.empty:
            # Convert ObjectId to string for JSON serialization
            if '_id' in df.columns:
                df['_id'] = df['_id'].astype(str)
            # Ensure lead_id is string
            if 'lead_id' in df.columns:
                df['lead_id'] = df['lead_id'].astype(str)
        
        return df
    except Exception as e:
        import streamlit as st
        st.error(f"Error searching enriched leads: {e}")
        return None

def save_signature(user_email, name, company, linkedin_url):
    """
    Save or update a user's signature in MongoDB.
    """
    try:
        # Update if exists, insert if doesn't exist
        result = signatures_collection.update_one(
            {'user_email': user_email},
            {
                '$set': {
                    'name': name,
                    'company': company,
                    'linkedin_url': linkedin_url,
                    'user_email': user_email
                }
            },
            upsert=True
        )
        logging.info(f"[MongoDB] Saved/Updated signature for {user_email}")
        return True
    except Exception as e:
        logging.error(f"[MongoDB] Failed to save signature for {user_email}: {e}")
        return False

def get_signature(user_email):
    """
    Get a user's signature from MongoDB.
    Returns None if no signature exists.
    """
    try:
        signature = signatures_collection.find_one({'user_email': user_email})
        return signature
    except Exception as e:
        logging.error(f"[MongoDB] Failed to get signature for {user_email}: {e}")
        return None

def check_and_update_email_responses(sender_email: str):
    """
    Check for replies to sent emails and update the scheduled emails collection.
    This will mark all follow-up emails as cancelled if a reply is found.
    
    Args:
        sender_email: The email address of the sender to check replies for
    """
    try:
        # Get all sent emails for this sender that haven't been responded to
        sent_emails = list(scheduled_emails_collection.find({
            'sender_email': sender_email,
            'status': 'sent',
            'responded': False
        }))

        if not sent_emails:
            return

        # Group emails by conversation
        conversation_emails = {}
        for email in sent_emails:
            conv_id = email.get('conversation_id')
            if conv_id not in conversation_emails:
                conversation_emails[conv_id] = []
            conversation_emails[conv_id].append(email)

        # Check for replies for each conversation
        for conv_id, emails in conversation_emails.items():
            # Get the most recent email sent in this conversation
            latest_email = max(emails, key=lambda x: x['scheduled_time'])
            recipient = latest_email['email'][0]  # email field is a list
            
            # Check if there's a reply after the latest email
            has_reply = check_for_reply(sender_email, recipient, latest_email['scheduled_time'])
            
            if has_reply:
                # Mark all pending follow-ups for this conversation as cancelled
                scheduled_emails_collection.update_many(
                    {
                        'conversation_id': conv_id,
                        'status': 'pending'
                    },
                    {'$set': {'status': 'cancelled', 'responded': True}}
                )
                logging.info(f"Marked all follow-ups for conversation {conv_id} as cancelled due to reply")

    except Exception as e:
        logging.error(f"Error checking email responses: {str(e)}")

def check_for_reply(sender_email: str, recipient_email: str, after_time: datetime) -> bool:
    """
    Check if there's a reply from the recipient after the given time.
    This is a placeholder function - implement the actual reply checking logic
    based on your email provider (Outlook/Gmail).
    """
    try:
        # For Outlook
        if 'outlook.com' in sender_email or 'microsoft' in sender_email or 'panscience' in sender_email:
            from outlook_auth import get_outlook_account
            account = get_outlook_account()
            if account:
                mailbox = account.mailbox()
                inbox = mailbox.inbox_folder()
                
                # Search for replies from the recipient after the given time
                query = f"from:{recipient_email} after:{after_time.strftime('%Y-%m-%d')}"
                messages = inbox.get_messages(query=query, limit=1)
                
                return len(list(messages)) > 0
                
        # For Gmail
        else:
            from auth import get_gmail_service
            service = get_gmail_service()
            if service:
                # Search for replies from the recipient after the given time
                query = f"from:{recipient_email} after:{after_time.strftime('%Y/%m/%d')}"
                results = service.users().messages().list(userId='me', q=query).execute()
                messages = results.get('messages', [])
                
                return len(messages) > 0
                
        return False
        
    except Exception as e:
        logging.error(f"Error checking for reply: {str(e)}")
        return False
