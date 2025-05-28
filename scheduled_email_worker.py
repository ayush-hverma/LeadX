import time
from datetime import datetime
from email_sender import EmailSender
from outlook_sender import OutlookSender
from mongodb_client import get_due_scheduled_emails, mark_email_as_sent

# This script should be run periodically (e.g., every minute) to send due scheduled emails.
def run_worker():
    while True:
        now = datetime.now().replace(second=0, microsecond=0)
        due_emails = get_due_scheduled_emails(now)
        if due_emails:
            print(f"Found {len(due_emails)} scheduled emails to send...")
        for email in due_emails:
            try:
                # Skip if responded
                if email.get('responded'):
                    continue
                # Choose sender based on email['sender_email'] (simple check for Outlook vs Gmail)
                if 'outlook.com' in email['sender_email'] or 'microsoft' in email['sender_email']:
                    sender = OutlookSender()
                else:
                    sender = EmailSender()
                payload = {
                    "email": email["email"],
                    "subject": email["subject"],
                    "body": email["body"],
                    "sender_email": email["sender_email"],
                    "sender_name": email["sender_name"]
                }
                # Send the email
                if isinstance(sender, OutlookSender):
                    sender.send_email_batch([payload])
                else:
                    import asyncio
                    asyncio.run(sender.send_emails([payload]))
                mark_email_as_sent(email['_id'])
                print(f"Sent scheduled email to {email['email']}")
            except Exception as e:
                print(f"Failed to send scheduled email: {e}")
        time.sleep(60)  # Check every minute

if __name__ == "__main__":
    run_worker()
