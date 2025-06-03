import time
from datetime import datetime, time as dt_time
from email_sender import EmailSender
from outlook_sender import OutlookSender
from mongodb_client import get_due_scheduled_emails, mark_email_as_sent, check_and_update_email_responses, scheduled_emails_collection
import os

def is_time_to_send(current_time):
    """Check if it's 9 AM to send scheduled emails."""
    return current_time.hour == 9 and current_time.minute == 0

def send_email(email_data):
    """Send a single email using the appropriate sender."""
    try:
        # Choose sender based on email['sender_email']
        if 'outlook.com' in email_data['sender_email'] or 'microsoft' in email_data['sender_email'] or 'panscience' in email_data['sender_email']:
            sender = OutlookSender()
        else:
            sender = EmailSender()
            
        payload = {
            "email": email_data["email"],
            "subject": email_data["subject"],
            "body": email_data["body"],
            "sender_email": email_data["sender_email"],
            "sender_name": email_data["sender_name"]
        }
        
        # Send the email
        if isinstance(sender, OutlookSender):
            result = sender.send_email_batch([payload])
        else:
            import asyncio
            result = asyncio.run(sender.send_emails([payload]))
            
        return result
    except Exception as e:
        print(f"Failed to send email: {e}")
        return None

def run_worker():
    """
    Worker that runs periodically to send scheduled emails.
    - Sends initial emails immediately
    - In development: Sends follow-ups after 2 minutes
    - In production: Sends follow-ups at 9 AM
    - Checks for replies before sending any follow-up
    """
    while True:
        now = datetime.now()
        is_development = os.getenv('ENVIRONMENT', 'production').lower() == 'development'
        
        # Get all pending emails
        due_emails = get_due_scheduled_emails(now)
        
        if due_emails:
            print(f"Found {len(due_emails)} scheduled emails to process...")
            
            # Group emails by conversation
            conversation_emails = {}
            for email in due_emails:
                conv_id = email.get('conversation_id')
                if conv_id not in conversation_emails:
                    conversation_emails[conv_id] = []
                conversation_emails[conv_id].append(email)
            
            # Process each conversation
            for conv_id, emails in conversation_emails.items():
                # Sort emails by followup_day
                emails.sort(key=lambda x: x['followup_day'])
                
                # Check if any email in this conversation has been responded to
                has_response = any(email.get('responded', False) for email in emails)
                
                if has_response:
                    # Mark all pending follow-ups as cancelled
                    for email in emails:
                        if email['status'] == 'pending':
                            scheduled_emails_collection.update_one(
                                {'_id': email['_id']},
                                {'$set': {'status': 'cancelled', 'responded': True}}
                            )
                    continue
                
                # Process each email in the conversation
                for email in emails:
                    # Skip if already sent or cancelled
                    if email['status'] in ['sent', 'cancelled']:
                        continue
                    
                    # For initial email (day 0), send immediately
                    if email['followup_day'] == 0:
                        result = send_email(email)
                        if result:
                            mark_email_as_sent(email['_id'])
                            print(f"Sent initial email to {email['email']}")
                    
                    # For follow-ups
                    else:
                        # In development, send after 2 minutes
                        # In production, only send at 9 AM
                        if is_development or is_time_to_send(now):
                            # Check for replies before sending
                            check_and_update_email_responses(email['sender_email'])
                    
                            # Recheck if the email should still be sent
                            updated_email = scheduled_emails_collection.find_one({'_id': email['_id']})
                            if updated_email and updated_email['status'] == 'pending' and not updated_email.get('responded', False):
                                result = send_email(email)
                                if result:
                                    mark_email_as_sent(email['_id'])
                                    print(f"Sent follow-up email to {email['email']}")
        
        # Sleep for 1 minute before next check
        time.sleep(120)

if __name__ == "__main__":
    run_worker()
