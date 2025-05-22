import aiohttp
import asyncio
from typing import List, Dict, Any
import json
from datetime import datetime
import os
import pandas as pd
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from auth import get_gmail_service, get_user_email, get_user_name

class EmailSender:
    def __init__(self, batch_size: int = 5):
        self.batch_size = batch_size
        self.results_dir = "email_results"
        
        # Create results directory if it doesn't exist
        if not os.path.exists(self.results_dir):
            os.makedirs(self.results_dir)

    def create_message(self, to: str, subject: str, body: str, sender_email: str) -> Dict[str, Any]:
        """Create a message for an email."""
        message = MIMEMultipart()
        message['to'] = to
        message['from'] = sender_email
        message['subject'] = subject
        
        # Add recipient's email ID at the top of the body
        modified_body = f"Recipient Email ID: {to}\n\n{body}"
        
        # Add the body
        message.attach(MIMEText(modified_body, 'plain'))
        
        # Encode the message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        return {'raw': raw_message}

    async def send_email_batch(self, batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Send a batch of emails using Gmail API."""
        results = []
        gmail_service = get_gmail_service()
        
        if not gmail_service:
            return [{"error": "Gmail service not initialized", "status_code": 500}]
        
        for email_data in batch:
            try:
                # Create the message
                message = self.create_message(
                    to=email_data['email'][0],
                    subject=email_data['subject'],
                    body=email_data['body'],
                    sender_email=email_data['sender_email']
                )
                
                # Send the message
                sent_message = gmail_service.users().messages().send(
                    userId='me',
                    body=message
                ).execute()
                
                results.append({
                    "status": "success",
                    "message_id": sent_message['id']
                })
            except Exception as e:
                results.append({
                    "error": str(e),
                    "status_code": 500
                })
        
        return results

    async def send_emails(self, email_payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Send all emails in batches concurrently."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Create batches
        batches = [email_payloads[i:i + self.batch_size] 
                  for i in range(0, len(email_payloads), self.batch_size)]
        
        # Process batches
        all_results = []
        for batch in batches:
            results = await self.send_email_batch(batch)
            all_results.extend(results)
        
        # Return summary
        return {
            "timestamp": timestamp,
            "total_emails": len(email_payloads),
            "successful": len([r for r in all_results if r.get("status") == "success"]),
            "failed": len([r for r in all_results if r.get("error")])
        }

def prepare_email_payloads(generated_emails: List[Dict[str, Any]], enriched_data: pd.DataFrame = None) -> List[Dict[str, Any]]:
    """Convert generated emails into the format required by the API."""
    payloads = []
    
    for result in generated_emails:
        # Check if the result has the required fields
        if not isinstance(result, dict):
            continue
            
        # Get the final result from the correct structure
        final_result = result.get("final_result", {})
        if not final_result:
            continue
            
        # Get lead_id and find email from enriched data
        lead_id = result.get("lead_id")
        if not lead_id or enriched_data is None:
            continue
            
        # Get email from enriched data
        lead_data = enriched_data[enriched_data['lead_id'] == lead_id]
        if lead_data.empty:
            continue
            
        email = lead_data['email'].iloc[0]
        subject = final_result.get("subject", "")
        body = final_result.get("body", "")
        
        # Skip if any required field is missing
        if not all([email, subject, body]):
            continue
            
        # Skip if email is 'N/A'
        if email == 'N/A':
            continue
        
        # Get sender's information
        sender_email = get_user_email()
        sender_name = get_user_name()
        
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
    
    return payloads 