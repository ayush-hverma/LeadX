import aiohttp
import asyncio
import time
from typing import List, Dict, Optional, Tuple
import json
from datetime import datetime
import os
import streamlit as st
from auth import get_user_name, get_user_email
from personalised_email import generate_email_for_single_lead
from outlook_auth import is_outlook_authenticated
from mongodb_client import get_signature

# Constants for pipeline configuration
BATCH_SIZE = 50  # Number of leads to process in each batch
MAX_CONCURRENT = 5  # Maximum concurrent requests within a batch
MAX_RETRIES = 3  # Number of retries for failed requests
RETRY_DELAY = 5  # Seconds to wait before retrying
TIMEOUT = 60  # Timeout for each request in seconds
SAVE_INTERVAL = 100  # Save results after every N leads

class EmailGenerationPipeline:
    def __init__(self, 
                 batch_size: int = BATCH_SIZE,
                 max_concurrent: int = MAX_CONCURRENT,
                 max_retries: int = MAX_RETRIES,
                 retry_delay: int = RETRY_DELAY,
                 timeout: int = TIMEOUT,
                 save_interval: int = SAVE_INTERVAL):
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        self.save_interval = save_interval
        self.all_results = []  # Store all results (successful and failed)
        
    def format_product_details(self, product_details: dict) -> str:
        """Format product details into a structured string"""
        formatted_text = []
        
        # Add problem statement
        if "problem_it_solves" in product_details:
            if isinstance(product_details["problem_it_solves"], list):
                formatted_text.append("Problems Solved:")
                for problem in product_details["problem_it_solves"]:
                    formatted_text.append(f"- {problem}")
            else:
                formatted_text.append(f"Problems Solved: {product_details['problem_it_solves']}")
        
        # Add solution
        if "solution" in product_details:
            if isinstance(product_details["solution"], list):
                formatted_text.append("\nSolution:")
                for solution in product_details["solution"]:
                    formatted_text.append(f"- {solution}")
            else:
                formatted_text.append(f"\nSolution: {product_details['solution']}")
        
        # Add unique selling points
        if "unique_selling_point" in product_details:
            if isinstance(product_details["unique_selling_point"], list):
                formatted_text.append("\nUnique Selling Points:")
                for usp in product_details["unique_selling_point"]:
                    formatted_text.append(f"- {usp}")
            else:
                formatted_text.append(f"\nUnique Selling Points: {product_details['unique_selling_point']}")
        
        # Add features
        if "features" in product_details:
            if isinstance(product_details["features"], list):
                formatted_text.append("\nFeatures:")
                for feature in product_details["features"]:
                    formatted_text.append(f"- {feature}")
            else:
                formatted_text.append(f"\nFeatures: {product_details['features']}")
        
        # Add benefits
        if "benefits" in product_details:
            if isinstance(product_details["benefits"], list):
                formatted_text.append("\nBenefits:")
                for benefit in product_details["benefits"]:
                    formatted_text.append(f"- {benefit}")
            else:
                formatted_text.append(f"\nBenefits: {product_details['benefits']}")
        
        return "\n".join(formatted_text)
    
    def generate_email(self, lead: dict, product_details: dict, product_name: str = None) -> dict:
        """Generate a single email for a lead"""
        # Format the product details
        formatted_product = self.format_product_details(product_details)
        
        # Defensive: ensure lead is a dict and not None
        if not isinstance(lead, dict):
            lead = {}
        sender_name = ''
        sender_email = ''
        # Prefer cached Outlook user info if available
        if is_outlook_authenticated():
            sender_name = st.session_state.get('outlook_user_name', '')
            sender_email = st.session_state.get('outlook_user_email', '')
        else:
            try:
                sender_name = get_user_name()
            except Exception:
                pass
            try:
                sender_email = get_user_email()
            except Exception:
                pass
        if not sender_name:
            sender_name = (st.session_state.get('outlook_user_info', {}) or {}).get('displayName') or (st.session_state.get('outlook_user_info', {}) or {}).get('name') or ''
        if not sender_email:
            sender_email = (st.session_state.get('outlook_user_info', {}) or {}).get('mail') or (st.session_state.get('outlook_user_info', {}) or {}).get('email') or ''

        # Get user's signature
        signature = get_signature(sender_email)
        
        lead_details = {
            "lead_id": str(lead.get('id', lead.get('lead_id', ''))),
            "name": str(lead.get('name', '')),
            "experience": str(lead.get('experience', '')),
            "education": str(lead.get('education', '')),
            "company": str(lead.get('organization', '')),
            "company_overview": str(lead.get('company_overview', '')),
            "company_industry": str(lead.get('company_industry', '')),
            "email": str(lead.get('email', ''))
        }
        try:
            result = generate_email_for_single_lead(lead_details, formatted_product, product_name=product_name)
            body = result.get("body", "")
            
            # Add signature if it exists
            if body.strip().endswith("Best Regards,"):
                if signature:
                    body = body.rstrip() + f"\n{signature['name']}\n{signature['company']}\n{signature['linkedin_url']}\n"
                else:
                    # Fallback to first name if no signature
                    first_name = sender_name.split()[0] if sender_name else ""
                    body = body.rstrip() + f"\n{first_name}\n"
                    
            return {
                "final_result": {
                    "subject": result.get("subject", ""),
                    "body": body
                },
                "lead_id": lead_details["lead_id"],
                "recipient": result.get("recipient", ""),
                "recipient_email": result.get("recipient_email", ""),
                "from": sender_email,
                "from_name": sender_name  # Use full name for display
            }
        except Exception as e:
            print(f"❌ Error generating email for {lead.get('name', 'Unknown')}: {str(e)}")
            return {
                "final_result": {
                    "subject": "Error generating email",
                    "body": f"An error occurred while generating the email: {str(e)}\n\n"
                },
                "lead_id": lead_details.get("lead_id", ""),
                "recipient": lead_details.get("name", ""),
                "recipient_email": lead_details.get("email", ""),
                "from": sender_email,
                "from_name": sender_name
            }
    
    def get_timestamp(self) -> str:
        """Get current timestamp for file naming"""
        return datetime.now().strftime("%Y%m%d_%H%M%S")
        
    def save_results(self, results: List[dict], batch_num: int, is_final: bool = False):
        """No-op: Results saving is disabled"""
        pass
        
    def save_payloads(self, payloads: List[dict], batch_num: int):
        """No-op: Payload saving is disabled"""
        pass

    async def send_request_with_retry(self, 
                                    session: aiohttp.ClientSession, 
                                    payload: dict, 
                                    lead_name: str) -> Tuple[Optional[dict], bool, dict]:
        """
        Send a request with retry logic.
        Returns: (result, success_status, detailed_result)
        """
        detailed_result = {
            "lead_id": payload["lead"]["lead_id"],
            "lead_name": lead_name,
            "company": payload["lead"]["company"],
            "status": "failed",
            "attempts": [],
            "final_result": None,
            "error": None,
            "payload": payload  # Include the payload in the detailed result
        }
        
        for attempt in range(self.max_retries + 1):
            attempt_info = {
                "attempt_number": attempt + 1,
                "timestamp": datetime.now().isoformat(),
                "status": "failed",
                "error": None,
                "payload": payload  # Include the payload in each attempt
            }
            
            try:
                async with session.post(
                    "https://leadxmail-c6.onrender.com/generate-single-email",
                    json=payload,
                    timeout=self.timeout
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        print(f"✅ Success for {lead_name} (Attempt {attempt + 1})")
                        attempt_info["status"] = "success"
                        detailed_result["status"] = "success"
                        detailed_result["final_result"] = result
                        detailed_result["attempts"].append(attempt_info)
                        return result, True, detailed_result
                    else:
                        error_msg = f"HTTP {response.status}"
                        print(f"❌ Failed for {lead_name} (Status: {response.status}, Attempt {attempt + 1})")
                        attempt_info["error"] = error_msg
                        
            except asyncio.TimeoutError:
                error_msg = "Timeout"
                print(f"⏰ Timeout for {lead_name} (Attempt {attempt + 1})")
                attempt_info["error"] = error_msg
            except Exception as e:
                error_msg = str(e)
                print(f"❌ Error for {lead_name}: {error_msg} (Attempt {attempt + 1})")
                attempt_info["error"] = error_msg
                
            detailed_result["attempts"].append(attempt_info)
            detailed_result["error"] = error_msg
                
            if attempt < self.max_retries:
                print(f"🔄 Retrying {lead_name} in {self.retry_delay} seconds...")
                await asyncio.sleep(self.retry_delay)
                
        return None, False, detailed_result

    async def process_batch(self, 
                          session: aiohttp.ClientSession, 
                          batch: List[dict],
                          batch_num: int) -> List[dict]:
        """Process a single batch of leads"""
        # Save payloads for this batch
        self.save_payloads(batch, batch_num)
        
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def bounded_send_request(payload: dict) -> Tuple[Optional[dict], bool, dict]:
            async with semaphore:
                return await self.send_request_with_retry(
                    session, 
                    payload, 
                    payload["lead"]["name"]
                )
        
        tasks = [bounded_send_request(payload) for payload in batch]
        results = await asyncio.gather(*tasks)
        
        # Store all results (both successful and failed)
        batch_results = [r[2] for r in results]  # Get detailed results
        self.all_results.extend(batch_results)
        
        # Return only successful results for immediate processing
        successful_results = [r[0] for r in results if r[1]]
        return successful_results

    async def process_all_leads(self, all_payloads: List[dict]) -> None:
        """Process all leads in batches"""
        total_leads = len(all_payloads)
        total_processed = 0
        total_successful = 0
        start_time = time.time()
        
        print(f"\n🚀 Starting pipeline for {total_leads} leads")
        print(f"📊 Configuration:")
        print(f"   Batch size: {self.batch_size}")
        print(f"   Max concurrent: {self.max_concurrent}")
        print(f"   Max retries: {self.max_retries}")
        print(f"   Retry delay: {self.retry_delay}s")
        print(f"   Timeout: {self.timeout}s")
        
        # Save all payloads before processing
        self.save_payloads(all_payloads, 0)  # Save complete payload list with batch number 0
        
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
            # Process in batches
            for batch_num, i in enumerate(range(0, total_leads, self.batch_size), 1):
                batch = all_payloads[i:i + self.batch_size]
                print(f"\n📦 Processing batch {batch_num} ({len(batch)} leads)")
                
                batch_start = time.time()
                successful_results = await self.process_batch(session, batch, batch_num)
                batch_time = time.time() - batch_start
                
                # Update statistics
                total_processed += len(batch)
                total_successful += len(successful_results)
                
                # Save results if we've processed enough leads
                if total_processed % self.save_interval == 0:
                    self.save_results(successful_results, batch_num)
                
                # Print batch summary
                print(f"\n📊 Batch {batch_num} Summary:")
                print(f"   Processed: {len(batch)} leads")
                print(f"   Successful: {len(successful_results)}")
                print(f"   Failed: {len(batch) - len(successful_results)}")
                print(f"   Batch time: {batch_time:.2f}s")
                print(f"   Average time per lead: {batch_time/len(batch):.2f}s")
                
                # Print overall progress
                progress = (total_processed / total_leads) * 100
                print(f"\n📈 Overall Progress: {progress:.1f}%")
                print(f"   Total processed: {total_processed}/{total_leads}")
                print(f"   Total successful: {total_successful}")
                print(f"   Success rate: {(total_successful/total_processed)*100:.1f}%")
                
                # Add a small delay between batches to prevent overwhelming the API
                if i + self.batch_size < total_leads:
                    await asyncio.sleep(2)
        
        # Final summary
        total_time = time.time() - start_time
        print("\n🎉 Pipeline Complete!")
        print(f"📊 Final Summary:")
        print(f"   Total leads: {total_leads}")
        print(f"   Total successful: {total_successful}")
        print(f"   Total failed: {total_leads - total_successful}")
        print(f"   Success rate: {(total_successful/total_leads)*100:.1f}%")
        print(f"   Total time: {total_time:.2f}s")
        print(f"   Average time per lead: {total_time/total_leads:.2f}s")
        
        # Results are now only stored in memory
        self.all_results = self.all_results


