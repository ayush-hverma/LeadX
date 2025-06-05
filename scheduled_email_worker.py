import time
import logging
from datetime import datetime
from mongodb_client import get_due_scheduled_emails, mark_email_as_sent, check_and_update_email_responses, scheduled_emails_collection
import os

def is_time_to_send(scheduled_time):
    """Check if it's time to send the scheduled email."""
    # Check if we're in development mode
    is_development = os.getenv('ENVIRONMENT', 'production').lower() == 'development'
    current_time = datetime.now()
    
    if is_development:
        # In development, check if 2 minutes have passed since the scheduled time
        time_diff = current_time - scheduled_time
        return time_diff.total_seconds() >= 120  # 120 seconds = 2 minutes
    else:
        # In production, check if it's 9 AM on the scheduled day
        return (current_time.hour == 9 and 
                # current_time.minute < 2 and  # Give a 2-minute window
                current_time.date() == scheduled_time.date())

def send_email(email_data):
    """Send a single email using the appropriate sender"""
    try:
        # Determine which sender to use based on the email address
        if '@panscience' in email_data['sender_email'].lower() or '@outlook.com' in email_data['sender_email'].lower():
            from outlook_sender import OutlookSender
            sender = OutlookSender()
        else:
            from email_sender import EmailSender
            sender = EmailSender()
        
        # Send the email
        result = sender.send_email_batch([{
            'email': email_data['email'][0],
            'subject': email_data['subject'],
            'body': email_data['body'],
            'sender_email': email_data['sender_email'],
            'sender_name': email_data['sender_name']
        }])
        
        return result
    except Exception as e:
        logging.error(f"Error sending email: {e}")
        return False

def run_worker():
    """Run the worker to process scheduled emails."""
    while True:
        try:
            # Get all pending scheduled emails
            scheduled_emails = scheduled_emails_collection.find({
                "status": "pending"
            })
            
            # Group emails by conversation
            emails_by_conversation = {}
            for email in scheduled_emails:
                conv_id = email.get('conversation_id')
                if conv_id not in emails_by_conversation:
                    emails_by_conversation[conv_id] = []
                emails_by_conversation[conv_id].append(email)
            
            # Process each conversation
            for conv_id, emails in emails_by_conversation.items():
                # Check if any email in the conversation has been responded to
                has_response = any(email.get('responded', False) for email in emails)
                
                if not has_response:
                    # Process each email in the conversation
                    for email in emails:
                        if is_time_to_send(email['scheduled_time']):
                            try:
                                # Send the email
                                send_email(email)
                                
                                # Update status
                                scheduled_emails_collection.update_one(
                                    {"_id": email["_id"]},
                                    {"$set": {"status": "sent"}}
                                )
                            except Exception as e:
                                logging.error(f"Error sending scheduled email: {str(e)}")
                                # Update status to failed
                                scheduled_emails_collection.update_one(
                                    {"_id": email["_id"]},
                                    {"$set": {"status": "failed", "error": str(e)}}
                                )
            
            # Sleep for 1 minute before next check
            time.sleep(60)
            
        except Exception as e:
            logging.error(f"Error in worker loop: {str(e)}")
            time.sleep(60)  # Sleep for 1 minute before retrying

if __name__ == "__main__":
    run_worker()
