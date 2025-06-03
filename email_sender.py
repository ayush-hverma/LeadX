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
from auth import get_gmail_service, get_user_email, get_user_name, is_authenticated
from outlook_auth import is_outlook_authenticated, get_outlook_email, get_outlook_name

class EmailSender:
    def __init__(self, batch_size: int = 5):
        self.batch_size = batch_size
        self.results_dir = "email_results"
        
        # Create results directory if it doesn't exist
        if not os.path.exists(self.results_dir):
            os.makedirs(self.results_dir)

    def create_message(self, to: str, subject: str, body: str, sender_email: str) -> Dict[str, Any]:
        """Create a message for an email."""
        try:
            message = MIMEMultipart()
            message['to'] = to
            message['from'] = sender_email
            message['subject'] = subject
            
            # Add recipient's email ID in the header using the correct MIME method
            message.add_header('X-Recipient-ID', to)
            
            # Add recipient's email ID at the top of the body
            modified_body = f"Recipient Email ID: {to}\n\n{body}"
            
            # Add the body
            message.attach(MIMEText(modified_body, 'plain'))
            
            # Encode the message
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            return {'raw': raw_message}
        except Exception as e:
            raise

    async def send_email_batch(self, batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Send a batch of emails using Gmail API."""
        results = []
        gmail_service = get_gmail_service()
        
        if not gmail_service:
            return [{"error": "Gmail service not initialized. Please sign in again.", "status_code": 500}]
        
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
                sent_message = gmail_service.users().messages().send(
                    userId='me',
                    body=message
                ).execute()
                
                print(f"✅ Successfully sent email to {email_data['email'][0]}")
                results.append({
                    "status": "success",
                    "message_id": sent_message['id'],
                    "recipient": email_data['email'][0]
                })
            except Exception as e:
                error_msg = str(e)
                print(f"❌ Failed to send email to {email_data.get('email', ['unknown'])[0]}: {error_msg}")
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
            results = await self.send_email_batch(batch)
            all_results.extend(results)
        
        # Print per-email summary after all batches
        print("\n--- Per-email send results (Gmail) ---")
        for res in all_results:
            if res.get("status") == "success":
                print(f"✅ Email sent to {res.get('recipient')} (Message ID: {res.get('message_id', '-')})")
            else:
                print(f"❌ Failed to send email to {res.get('recipient')}: {res.get('error')}")
        print("--- End of Gmail send results ---\n")
        
        # Calculate summary
        successful = len([r for r in all_results if r.get("status") == "success"])
        failed = len([r for r in all_results if r.get("error")])
        
        # Return detailed summary
        return {
            "timestamp": timestamp,
            "total_emails": len(email_payloads),
            "successful": successful,
            "failed": failed,
            "results": all_results
        }

def prepare_email_payloads(generated_emails: List[Dict[str, Any]], enriched_data: pd.DataFrame = None) -> List[Dict[str, Any]]:
    """Convert generated emails into the format required by the API."""
    print(f"[DEBUG] prepare_email_payloads: received {len(generated_emails) if generated_emails else 0} generated_emails.")
    if enriched_data is None or enriched_data.empty:
        print("[DEBUG] prepare_email_payloads: enriched_data is None or empty! No payloads will be created.")
        return []
    payloads = []
    
    # Check authentication for either Gmail or Outlook
    gmail_auth = is_authenticated()
    outlook_auth = is_outlook_authenticated()
    
    if not (gmail_auth or outlook_auth):
        print("[DEBUG] No authentication found for either Gmail or Outlook")
        return payloads
        
    # Get sender information based on authentication method
    if outlook_auth:
        sender_email = get_outlook_email()
        sender_name = get_outlook_name()
    else:
        sender_email = get_user_email()
        sender_name = get_user_name()
    
    if not sender_email:
        print("[DEBUG] No sender email found")
        return payloads
    
    if not generated_emails:
        print("[DEBUG] No generated emails provided")
        return payloads

    # Get user's signature
    signature = get_signature(sender_email)
    
    for lead_block in generated_emails:
        try:
            # Get lead data from enriched data
            lead_id = lead_block.get("lead_id")
            if not lead_id:
                print("[DEBUG] No lead_id found in email data")
                continue
                
            lead_data = enriched_data[enriched_data['lead_id'] == lead_id]
            if lead_data.empty:
                print(f"[DEBUG] No matching lead data found for lead_id {lead_id}")
                continue
                
            recipient_email = lead_data['email'].iloc[0]
            
            # Process each email in the lead_block
            emails = lead_block.get("emails", [])
            for email in emails:
                try:
                    # Get email content
                    subject = email.get("subject", "")
                    body = email.get("body", "")
                    
                    if not all([recipient_email, subject, body]):
                        print(f"[DEBUG] Skipping: missing required fields for lead_id {lead_id}")
                        continue
                    
                    # Format the email body with proper closing
                    if body.strip().endswith("Best Regards,"):
                        if signature:
                            body = body.rstrip() + f"\n{signature['name']}\n{signature['company']}\n{signature['linkedin_url']}\n"
                        else:
                            # Fallback to first name if no signature
                            first_name = sender_name.split()[0] if sender_name else ""
                            body = body.rstrip() + f"\n{first_name}\n"
                    
                    # Create payload for Outlook
                    payload = {
                        "email": [recipient_email],
                        "subject": subject,
                        "body": body
                    }
                    
                    payloads.append(payload)
                    print(f"[DEBUG] Prepared payload for {recipient_email} (lead_id: {lead_id})")
                except Exception as e:
                    print(f"[DEBUG] Exception while processing email in lead_block: {e}")
                    continue
                    
        except Exception as e:
            print(f"[DEBUG] Exception while processing lead_block: {e}")
            continue
            
    print(f"[DEBUG] prepare_email_payloads: prepared {len(payloads)} payloads")
    return payloads
