from pymongo import MongoClient
import os
import streamlit as st

# Try to get MongoDB URI from Streamlit secrets, fallback to environment variable
MONGODB_URI = "mongodb+srv://ayu5hhverma03:ayush2503@leadx.mnrxujx.mongodb.net/?retryWrites=true&w=majority&appName=LeadX"
if not MONGODB_URI:
    raise ValueError("MongoDB URI not found in Streamlit secrets or environment variables.")

client = MongoClient(MONGODB_URI)
db = client['LeadX']  # Use your database name
collection = db['enriched_leads']  # Use your collection name
generated_emails_collection = db['generated_emails']  # Use your collection name

def save_enriched_data(data):
    """
    Save a single enriched data dictionary or a list of dictionaries to MongoDB Atlas.
    """
    if isinstance(data, list):
        result = collection.insert_many(data)
        return result.inserted_ids
    else:
        result = collection.insert_one(data)
        return result.inserted_id

def save_generated_emails(emails):
    """
    Save a single generated email dictionary or a list of dictionaries to MongoDB Atlas.
    """
    if isinstance(emails, list):
        result = generated_emails_collection.insert_many(emails)
        return result.inserted_ids
    else:
        result = generated_emails_collection.insert_one(emails)
        return result.inserted_id
