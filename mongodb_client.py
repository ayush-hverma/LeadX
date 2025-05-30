from pymongo import MongoClient
import os
import streamlit as st
import logging

# Try to get MongoDB URI from Streamlit secrets, fallback to environment variable
MONGODB_URI = "mongodb+srv://ayu5hhverma03:ayush2503@leadx.mnrxujx.mongodb.net/?retryWrites=true&w=majority&appName=LeadX"
if not MONGODB_URI:
    raise ValueError("MongoDB URI not found in Streamlit secrets or environment variables.")

client = MongoClient(MONGODB_URI)
db = client['LeadX']  # Use your database name
collection = db['enriched_leads']  # Use your collection name
generated_emails_collection = db['generated_emails']  # Use your collection name
scheduled_emails_collection = db['scheduled_emails']  # New collection for scheduled emails

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

def schedule_followup_emails(lead_email, sender_email, sender_name, initial_time, base_payload, prompts_by_day, intervals=[0,3,7,11]):
    """
    Schedule follow-up emails at specified day intervals if no response is received.
    prompts_by_day: dict mapping day (int) to prompt string for that day
    base_payload: dict with any extra fields (e.g., lead_id, etc.)
    """
    from datetime import timedelta
    scheduled_ids = []
    for day in intervals:
        scheduled_time = initial_time + timedelta(days=day)
        email_data = {
            "email": [lead_email],
            "subject": "",  # To be filled by Gemini prompt
            "body": "",      # To be filled by Gemini prompt
            "sender_email": sender_email,
            "sender_name": sender_name,
            "scheduled_time": scheduled_time,
            "status": "pending",
            "followup_day": day,
            "responded": False,
            "prompt": prompts_by_day.get(day, ""),
            **base_payload
        }
        scheduled_id = save_scheduled_email(email_data)
        scheduled_ids.append(scheduled_id)
    return scheduled_ids

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
