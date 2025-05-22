import logging
from typing import List, Dict, Any
from datetime import datetime
import streamlit as st
import pandas as pd
from O365 import Account
from outlook_auth import get_outlook_account, get_outlook_email, get_outlook_name, is_outlook_authenticated
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OutlookSender:
    def __init__(self, batch_size: int = 5):
        self.batch_size = batch_size
        logger.info("Initializing OutlookSender")
        try:
            self.account = get_outlook_account()
            if not self.account:
                logger.error("Failed to get Outlook account - account is None")
                raise ValueError("Outlook account not initialized")
            logger.info("Successfully initialized Outlook account")
        except Exception as e:
            logger.error(f"Error initializing Outlook account: {str(e)}")
            raise
        
    def create_message(self, to: str, subject: str, body: str, sender_email: str) -> Dict[str, Any]:
        """Create a message for an email."""
        try:
            if not self.account:
                logger.error("Outlook account not initialized")
                raise ValueError("Outlook account not initialized")
                
            # Create a new message
            mailbox = self.account.mailbox()
            if not mailbox:
                logger.error("Failed to get mailbox")
                raise ValueError("Failed to get mailbox")
                
            message = mailbox.new_message()
            if not message:
                logger.error("Failed to create new message")
                raise ValueError("Failed to create new message")
            
            # Set message properties
            message.to.add(to)
            message.subject = subject
            
            # Add recipient's email ID in the header using the correct method
            message.headers = {'X-Recipient-ID': to}
            
            # Add recipient's email ID at the top of the body
            modified_body = f"Recipient Email ID: {to}\n\n{body}"
            message.body = modified_body
            
            logger.info(f"Successfully created message for recipient: {to}")
            return message
        except Exception as e:
            logger.error(f"Error creating message for {to}: {str(e)}")
            raise

    async def send_email_batch(self, batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Send a batch of emails using Outlook API."""
        results = []
        
        if not self.account:
            logger.error("Outlook account not initialized")
            return [{"error": "Outlook account not initialized. Please sign in again.", "status_code": 500}]
        
        for email_data in batch:
            try:
                # Validate required fields
                if not all(key in email_data for key in ['email', 'subject', 'body', 'sender_email']):
                    raise ValueError("Missing required email fields")
                
                # Create the message
                message = self.create_message(
                    to=email_data['email'][0],
                    subject=email_data['subject'],
                    body=email_data['body'],
                    sender_email=email_data['sender_email']
                )
                
                # Send the message
                message.send()
                
                logger.info(f"Successfully sent email to {email_data['email'][0]}")
                results.append({
                    "status": "success",
                    "recipient": email_data['email'][0]
                })
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error sending email to {email_data.get('email', ['unknown'])[0]}: {error_msg}")
                results.append({
                    "error": error_msg,
                    "status_code": 500,
                    "recipient": email_data.get('email', ['unknown'])[0]
                })
        
        return results

    async def send_emails(self, email_payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Send all emails in batches concurrently."""
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
        all_results = []
        for batch_num, batch in enumerate(batches, 1):
            logger.info(f"Processing batch {batch_num} of {len(batches)}")
            results = await self.send_email_batch(batch)
            all_results.extend(results)
        
        # Calculate summary
        successful = len([r for r in all_results if r.get("status") == "success"])
        failed = len([r for r in all_results if r.get("error")])
        
        # Log summary
        logger.info(f"Email sending completed. Total: {len(email_payloads)}, Successful: {successful}, Failed: {failed}")
        
        # Return detailed summary
        return {
            "timestamp": timestamp,
            "total_emails": len(email_payloads),
            "successful": successful,
            "failed": failed,
            "results": all_results
        }

def prepare_outlook_email_payloads(generated_emails: List[Dict[str, Any]], enriched_data: pd.DataFrame = None) -> List[Dict[str, Any]]:
    """Convert generated emails into the format required for Outlook sending."""
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
        logger.info(f"First generated email structure: {json.dumps(generated_emails[0], indent=2)}")
        logger.info(f"Enriched data columns: {enriched_data.columns.tolist()}")
        logger.info(f"Sample lead_id from enriched data: {enriched_data['lead_id'].iloc[0] if 'lead_id' in enriched_data.columns else 'No lead_id column'}")
    
    for result in generated_emails:
        try:
            # Check if the result has the required fields
            if not isinstance(result, dict):
                logger.warning(f"Skipping invalid result type: {type(result)}")
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
            subject = result.get("subject", "")
            body = result.get("body", "")
            
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
