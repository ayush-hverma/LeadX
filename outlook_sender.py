import logging
from typing import List, Dict, Any
from datetime import datetime
import streamlit as st
import pandas as pd
from O365 import Account
from outlook_auth import get_outlook_account, get_outlook_email, get_outlook_name, is_outlook_authenticated
import json
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OutlookSender:
    def __init__(self, batch_size: int = 5):
        """Initialize Outlook sender with authentication"""
        self.batch_size = batch_size
        self.account = None
        self.mailbox = None
        self._initialize_account()

    def _initialize_account(self):
        """Initialize or reinitialize the Outlook account"""
        try:
            # Get authenticated account
            self.account = get_outlook_account()
            if not self.account:
                raise Exception("Failed to get authenticated Outlook account")
            
            # Get mailbox
            self.mailbox = self.account.mailbox()
            if not self.mailbox:
                raise Exception("Failed to get mailbox")
                
            logger.info("Successfully initialized Outlook account")
        except Exception as e:
            logger.error(f"Error initializing Outlook sender: {str(e)}")
            raise

    def create_message(self, payload):
        """Create an email message from the payload"""
        try:
            # Ensure we have a valid account
            if not self.account or not self.mailbox:
                self._initialize_account()
                
            # Create message
            message = self.mailbox.new_message()
            message.to.add(payload['email'][0])  # API expects a list of emails
            message.subject = payload['subject']
            message.body = payload['body']
            return message
        except Exception as e:
            logger.error(f"Error creating message: {str(e)}")
            raise

    def send_email_batch(self, email_payloads):
        """Send a batch of emails"""
        if not email_payloads:
            logger.error("No email payloads provided")
            return {
                'success': False,
                'message': 'No email payloads provided',
                'total': 0,
                'successful': 0,
                'failed': 0
            }

        total = len(email_payloads)
        successful = 0
        failed = 0

        try:
            # Process each email
            for payload in email_payloads:
                try:
                    # Create and send message
                    message = self.create_message(payload)
                    if not message:
                        logger.error(f"Failed to create message for {payload['email']}")
                        continue
                        
                    if message.send():
                        successful += 1
                        logger.info(f"Successfully sent email to {payload['email']}")
                    else:
                        logger.error(f"Failed to send email to {payload['email']}")
                except Exception as e:
                    failed += 1
                    logger.error(f"Error sending email to {payload['email']}: {str(e)}")
                    # If token refresh error, try to refresh and retry once
                    if "No auth token found" in str(e) or "refresh_token" in str(e):
                        try:
                            # Reinitialize account and retry
                            self._initialize_account()
                            message = self.create_message(payload)
                            if message.send():
                                successful += 1
                                failed -= 1
                                logger.info(f"Successfully sent email to {payload['email']} after token refresh")
                            else:
                                logger.error(f"Failed to send email to {payload['email']} after token refresh")
                        except Exception as retry_error:
                            logger.error(f"Error retrying email to {payload['email']}: {str(retry_error)}")

            return {
                'success': successful > 0,
                'message': f'Email sending completed. Total: {total}, Successful: {successful}, Failed: {failed}',
                'total': total,
                'successful': successful,
                'failed': failed
            }
        except Exception as e:
            logger.error(f"Error in send_email_batch: {str(e)}")
            return {
                'success': False,
                'message': f'Error sending emails: {str(e)}',
                'total': total,
                'successful': successful,
                'failed': failed
            }

    async def send_emails(self, email_payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Send all emails in batches."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if not email_payloads:
            logger.error("No email payloads provided")
            return {
                "timestamp": timestamp,
                "total_emails": 0,
                "successful": 0,
                "failed": 0,
                "error": "No email payloads provided"
            }
        
        # Create batches
        batches = [email_payloads[i:i + self.batch_size] 
                  for i in range(0, len(email_payloads), self.batch_size)]
        
        # Process batches
        total_successful = 0
        total_failed = 0
        
        for batch_num, batch in enumerate(batches, 1):
            logger.info(f"Processing batch {batch_num} of {len(batches)}")
            result = self.send_email_batch(batch)
            total_successful += result['successful']
            total_failed += result['failed']
        
        # Return summary
        return {
            "timestamp": timestamp,
            "total_emails": len(email_payloads),
            "successful": total_successful,
            "failed": total_failed,
            "message": f"Email sending completed. Total: {len(email_payloads)}, Successful: {total_successful}, Failed: {total_failed}"
        }

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
                
<<<<<<< HEAD
                # Add the properly formatted closing with the sender's name
                body = f"{body}\n\nBest Regards,\n{sender_name}"
=======
                # Add the properly formatted closing with the sender's first name
                first_name = sender_name.split()[0] if sender_name else ""
                body = f"{body}\n\nBest Regards,\n{first_name}"
>>>>>>> acf195d (Avasyu commit of email scheduling)
            
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
