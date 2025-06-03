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
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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
            from outlook_auth import load_outlook_token, refresh_token, save_outlook_token, get_outlook_account
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
                    # Try to get a new token using the account
                    account = get_outlook_account()
                    if account and account.connection.token_backend.token:
                        self.token = account.connection.token_backend.token
                        save_outlook_token(self.token)
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
        
        # Check if we're in development environment using environment variable
        is_development = os.getenv('ENVIRONMENT', 'production').lower() == 'development'
        logging.info(f"is_development: {is_development}")
        for payload in payloads:
            try:
                # Ensure we have a valid token before sending
                if not self.token or self.token.get('expires_at', 0) < time.time():
                    self.initialize_account()
                    
                # Get the access token
                access_token = self.token.get('access_token')
                if not access_token:
                    raise Exception("No access token available")
                
                # In development, use test emails from .env
                if is_development:
                    test_emails = os.getenv('TEST_EMAILS', '').split(',')
                    if not test_emails:
                        raise Exception("No test emails configured in .env file")
                    recipient_emails = test_emails
                else:
                    recipient_emails = payload['email']
                    
                response = requests.post(
                    'https://graph.microsoft.com/v1.0/me/sendMail',
                    headers={
                        'Authorization': f'Bearer {access_token}',
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
                                } for email in recipient_emails
                            ]
                        }
                    }
                )
                
                if response.status_code == 202:
                    results['successful'] += 1
                    logger.info(f"Successfully sent email to {recipient_emails}")
                else:
                    results['failed'] += 1
                    error_msg = f"Failed to send email to {recipient_emails}: {response.text}"
                    results['errors'].append(error_msg)
                    logger.error(error_msg)
                    
            except Exception as e:
                results['failed'] += 1
                error_msg = f"Error sending email to {payload['email']}: {str(e)}"
                results['errors'].append(error_msg)
                logger.error(error_msg)
                
        return results

def prepare_outlook_email_payloads(generated_emails: List[Dict[str, Any]], enriched_data: pd.DataFrame = None) -> List[Dict[str, Any]]:
    """Convert generated emails into the format required by the Outlook API."""
    logger.info(f"Preparing Outlook email payloads for {len(generated_emails) if generated_emails else 0} generated emails")
    if enriched_data is None or enriched_data.empty:
        logger.warning("No enriched data provided")
        return []
        
    payloads = []
    
    # Get sender information
    sender_email = get_outlook_email()
    sender_name = get_outlook_name()
    
    if not sender_email:
        logger.error("No sender email found")
        return []
        
    # Get user's signature
    signature = get_signature(sender_email)
    
    for lead_block in generated_emails:
        try:
            lead_id = lead_block.get("lead_id")
            if not lead_id:
                logger.warning("No lead_id found in email data")
                continue
                
            lead_data = enriched_data[enriched_data['lead_id'] == lead_id]
            if lead_data.empty:
                logger.warning(f"No matching lead data found for lead_id {lead_id}")
                continue
                
            recipient_email = lead_data['email'].iloc[0]
            
            # Process each email in the lead_block
            emails = lead_block.get("emails", [])
            for email in emails:
                try:
                    subject = email.get("subject", "")
                    body = email.get("body", "")
                    
                    if not all([recipient_email, subject, body]):
                        logger.warning(f"Missing required fields for lead_id {lead_id}")
                        continue
                    
                    # Format the email body with proper closing
                    if body.strip().endswith("Best Regards,"):
                        if signature:
                            body = body.rstrip() + f"\n{signature['name']}\n{signature['company']}\n{signature['linkedin_url']}\n"
                        else:
                            # Fallback to first name if no signature
                            first_name = sender_name.split()[0] if sender_name else ""
                            body = body.rstrip() + f"\n{first_name}\n"
                    
                    # Create payload with only lead_id
                    payloads.append({
                        "lead_id": lead_id
                    })
                    logger.info(f"Successfully added payload for lead_id {lead_id}")
                except Exception as e:
                    logger.error(f"Error processing email for lead_id {lead_id}: {str(e)}")
                    continue
        except Exception as e:
            logger.error(f"Error processing lead_block: {str(e)}")
            continue
    
    logger.info(f"Successfully prepared {len(payloads)} email payloads")
    return payloads
