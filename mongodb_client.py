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

def save_enriched_data(data):
    """
    Save a single enriched data dictionary or a list of dictionaries to MongoDB Atlas.
    """
    if isinstance(data, list):
        result = collection.insert_many(data)
        logging.info(f"[MongoDB] Saved {len(result.inserted_ids)} enriched records: {result.inserted_ids}")
        print(f"[MongoDB] Saved {len(result.inserted_ids)} enriched records: {result.inserted_ids}")
        return result.inserted_ids
    else:
        result = collection.insert_one(data)
        logging.info(f"[MongoDB] Saved 1 enriched record: {result.inserted_id}")
        print(f"[MongoDB] Saved 1 enriched record: {result.inserted_id}")
        return result.inserted_id

def save_generated_emails(emails):
    """
    Save a single generated email dictionary or a list of dictionaries to MongoDB Atlas.
    """
    if isinstance(emails, list):
        result = generated_emails_collection.insert_many(emails)
        logging.info(f"[MongoDB] Saved {len(result.inserted_ids)} generated emails: {result.inserted_ids}")
        print(f"[MongoDB] Saved {len(result.inserted_ids)} generated emails: {result.inserted_ids}")
        return result.inserted_ids
    else:
        result = generated_emails_collection.insert_one(emails)
        logging.info(f"[MongoDB] Saved 1 generated email: {result.inserted_id}")
        print(f"[MongoDB] Saved 1 generated email: {result.inserted_id}")
        return result.inserted_id

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

def delete_lead_by_id(lead_id):
    """
    Delete a lead from MongoDB by its lead_id.
    Returns True if deleted, False otherwise.
    """
    try:
        result = collection.delete_one({'lead_id': lead_id})
        return result.deleted_count > 0
    except Exception as e:
        print(f"Error deleting lead with lead_id {lead_id}: {e}")
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
