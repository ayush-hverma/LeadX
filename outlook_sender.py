import logging
from typing import List, Dict, Any
from datetime import datetime
import streamlit as st
import pandas as pd
from O365 import Account
from outlook_auth import get_outlook_account, get_outlook_email, get_outlook_name, is_outlook_authenticated
import json
import time
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OutlookSender:
    def __init__(self):
        self.token = None
        self.initialize_account()
        
    def initialize_account(self):
        """Initialize the Outlook account with a valid token."""
        try:
            from outlook_auth import load_outlook_token, refresh_token, save_outlook_token
            self.token = load_outlook_token()
            
            if not self.token:
                raise Exception("No auth token found. Authentication Flow needed")
                
            # Check if token is expired
            if self.token.get('expires_at', 0) < time.time():
                new_token = refresh_token(self.token)
                if new_token:
                    save_outlook_token(new_token)
                    self.token = new_token
                else:
                    raise Exception("Failed to refresh token")
                    
            logger.info("Successfully initialized Outlook account")
        except Exception as e:
            logger.error(f"Failed to initialize Outlook account: {str(e)}")
            raise
            
    def send_email_batch(self, payloads):
        """Send a batch of emails using Outlook."""
        results = {
            'successful': 0,
            'failed': 0,
            'errors': []
        }
        
        for payload in payloads:
            try:
                # Ensure we have a valid token before sending
                if not self.token or self.token.get('expires_at', 0) < time.time():
                    self.initialize_account()
                    
                response = requests.post(
                    'https://graph.microsoft.com/v1.0/me/sendMail',
                    headers={
                        'Authorization': f'Bearer {self.token["access_token"]}',
                        'Content-Type': 'application/json'
                    },
                    json={
                        'message': {
                            'subject': payload['subject'],
                            'body': {
                                'contentType': 'Text',
                                'content': payload['body']
                            },
                            'toRecipients': [
                                {
                                    'emailAddress': {
                                        'address': email
                                    }
                                } for email in payload['email']
                            ]
                        }
                    }
                )
                
                if response.status_code == 202:
                    results['successful'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append(f"Failed to send email to {payload['email']}: {response.text}")
                    
            except Exception as e:
                results['failed'] += 1
                results['errors'].append(f"Error sending email to {payload['email']}: {str(e)}")
                
        return results

def prepare_outlook_email_payloads(generated_emails: List[Dict[str, Any]], enriched_data: pd.DataFrame = None) -> List[Dict[str, Any]]:
    """Convert generated emails into the format required by the Outlook API."""
    payloads = []
    
    logger.info(f"Starting to prepare email payloads. Generated emails count: {len(generated_emails)}")
    logger.info(f"Enriched data available: {enriched_data is not None}")
    
    # Check authentication
    if not is_outlook_authenticated():
        logger.error("Not authenticated with Outlook")
        return payloads
        
    # Get sender information
    sender_email = get_outlook_email()
    sender_name = get_outlook_name()
    logger.info(f"Sender email: {sender_email}")
    logger.info(f"Sender name: {sender_name}")
    
    if not sender_email:
        logger.error("No sender email found")
        return payloads
    
    if not generated_emails:
        logger.error("No generated emails provided")
        return payloads
        
    if enriched_data is None:
        logger.error("No enriched data provided")
        return payloads
    
    # Log the structure of the first generated email for debugging
    if generated_emails:
        try:
            def _json_default(obj):
                import bson
                if isinstance(obj, bson.ObjectId):
                    return str(obj)
                raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")
            logger.info(f"First generated email structure: {json.dumps(generated_emails[0], indent=2, default=_json_default)}")
        except Exception as e:
            logger.warning(f"Could not log generated email structure due to: {e}")
        logger.info(f"Enriched data columns: {enriched_data.columns.tolist()}")
        logger.info(f"Sample lead_id from enriched data: {enriched_data['lead_id'].iloc[0] if 'lead_id' in enriched_data.columns else 'No lead_id column'}")
    
    for result in generated_emails:
        try:
            # Check if the result has the required fields
            if not isinstance(result, dict):
                logger.warning(f"Skipping invalid result type: {type(result)}")
                continue
                
            # Get the final result from the correct structure
            final_result = result.get("final_result", {})
            if not final_result:
                logger.warning(f"No final_result found in email data: {result}")
                continue
                
            # Get lead_id and find email from enriched data
            lead_id = result.get("lead_id")
            if not lead_id:
                logger.warning(f"No lead_id found in email data: {result}")
                continue
                
            # Get email from enriched data
            lead_data = enriched_data[enriched_data['lead_id'] == lead_id]
            if lead_data.empty:
                logger.warning(f"No matching lead data found for lead_id: {lead_id}")
                continue
                
            email = lead_data['email'].iloc[0]
            subject = final_result.get("subject", "")
            body = final_result.get("body", "")
            
            # Skip if any required field is missing
            if not all([email, subject, body]):
                logger.warning(f"Missing required fields for lead_id {lead_id}. Email: {bool(email)}, Subject: {bool(subject)}, Body: {bool(body)}")
                continue
                
            # Skip if email is 'N/A'
            if email == 'N/A':
                logger.warning(f"Invalid email 'N/A' for lead_id {lead_id}")
                continue
            
            logger.info(f"Preparing payload for lead_id {lead_id} with email {email}")
            
            # Format the email body with proper closing
            if sender_name:
                # Remove any existing "Best regards" or similar closings
                body = body.replace("Best regards,\n[Your Name]", "")
                body = body.replace("Best Regards,\n[Your Name]", "")
                body = body.replace("Best regards,", "")
                body = body.replace("Best Regards,", "")
                body = body.strip()
                
                # Add the properly formatted closing with the sender's name
                body = f"{body}\n\nBest Regards,\n{sender_name}"
            
            payloads.append({
                "email": [email],  # API expects a list of emails
                "subject": subject,
                "body": body,
                "sender_email": sender_email,
                "sender_name": sender_name
            })
            logger.info(f"Successfully added payload for lead_id {lead_id}")
        except Exception as e:
            logger.error(f"Error processing lead_id {lead_id}: {str(e)}")
            continue
    
    logger.info(f"Successfully prepared {len(payloads)} email payloads")
    return payloads
