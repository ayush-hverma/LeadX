<<<<<<< HEAD
import requests
import pandas as pd
import json
import os
from dotenv import load_dotenv

load_dotenv()

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")

def get_people_data(lead_ids: list) -> pd.DataFrame:
    """
    Get people data from Apollo.io bulk match API and store in DataFrame.
    
    Args:
        lead_ids: List of Apollo.io lead IDs to match
    
    Returns:
        DataFrame containing people data with specified fields
    """
    url = "https://api.apollo.io/api/v1/people/bulk_match?reveal_personal_emails=false&reveal_phone_number=false"
    
    payload = {"details": [{"id": id} for id in lead_ids]}
    headers = {
        "accept": "application/json",
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "x-api-key": APOLLO_API_KEY or ""
    }
    print(f"Using Apollo API Key: {APOLLO_API_KEY}")

    try:
        response = requests.post(url, json=payload, headers=headers)
        print(f"Apollo API response status: {response.status_code}")
        print(f"Apollo API response text: {response.text[:500]}")
        response.raise_for_status()
        data = response.json()
        
        # Initialize list to store person data
        people_data = []
        
        if 'matches' in data:
            for person in data['matches']:
                # Get organization details
                org = person.get('organization', {})
                
                # Get education details
                education = person.get('education', [])
                education_str = '; '.join([
                    f"{edu.get('degree', '')} in {edu.get('field_of_study', '')}"
                    for edu in education if edu.get('degree') or edu.get('field_of_study')
                ]) if education else 'N/A'
                
                # Get experience details
                experience = person.get('experience', [])
                experience_str = '; '.join([
                    f"{exp.get('title', '')} at {exp.get('organization', {}).get('name', '')}"
                    for exp in experience if exp.get('title')
                ]) if experience else 'N/A'
                
                # Get organization details including short_description
                org_short_description = org.get('short_description', 'N/A')
                if org_short_description == 'N/A' and 'seo_description' in org:
                    org_short_description = org.get('seo_description', 'N/A')  # Fallback to seo_description if short_description is not available
                
                person_info = {
                    'lead_id': person.get('id', 'N/A'),
                    'name': f"{person.get('first_name', '')} {person.get('last_name', '')}",
                    'linkedin_url': person.get('linkedin_url', 'N/A'),
                    'title': person.get('title', 'N/A'),
                    'headline': person.get('headline', 'N/A'),
                    'email_status': person.get('email_status', 'N/A'),
                    'email': person.get('email', 'N/A'),
                    'organization': org.get('name', 'N/A'),
                    'company_industry': org.get('industry', 'N/A'),
                    'company_keywords': ', '.join(org.get('keywords', [])),
                    'company_website': org.get('website_url', 'N/A'),
                    'company_linkedin': org.get('linkedin_url', 'N/A'),
                    'company_twitter': org.get('twitter_url', 'N/A'),
                    'company_facebook': org.get('facebook_url', 'N/A'),
                    'company_angellist': org.get('angellist_url', 'N/A'),
                    'education': education_str,
                    'experience': experience_str,
                    'company_size': org.get('estimated_num_employees', 'N/A'),
                    'company_founded_year': org.get('founded_year', 'N/A'),
                    'company_location': f"{org.get('city', '')}, {org.get('state', '')}, {org.get('country', '')}"
                }
                people_data.append(person_info)
        
        # Create DataFrame
        df = pd.DataFrame(people_data)
        
        # Print summary
        print(f"\nProcessed {len(lead_ids)} lead IDs")
        print(f"Found {len(df)} matches")
        
        return df
        
    except requests.exceptions.RequestException as e:
        print(f"Error making API request: {e}")
        if hasattr(e, 'response'):
            print(f"Response status code: {e.response.status_code}")
            print(f"Response text: {e.response.text}")
        return pd.DataFrame()
    except Exception as e:
        print(f"Unexpected error: {e}")
        return pd.DataFrame()

if __name__ == "__main__":
    # Example usage
    test_ids = [
        "5ffb3288e187fc000126e479",
        "608a9e3de5abc10001230f6e",
        "6129ca2d7ecc0900011a06b6"
    ]
    
    # Get data and store in DataFrame
    df = get_people_data(test_ids)
    
    # Display DataFrame
    if not df.empty:
        print("\nDataFrame:")
        print(df)
        
        # Optionally save to CSV
        # df.to_csv('apollo_people_data.csv', index=False)
        # print("\nData saved to apollo_people_data.csv")

        # Save enriched data to MongoDB Atlas
        from mongodb_client import save_enriched_data
        data_dicts = df.to_dict('records')
        inserted_ids = save_enriched_data(data_dicts)
        print(f"\nSaved {len(inserted_ids)} records to MongoDB Atlas.")
    else:
=======
import requests
import pandas as pd
import json
import os
from dotenv import load_dotenv

load_dotenv()

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")

def get_people_data(lead_ids: list) -> pd.DataFrame:
    """
    Get people data from Apollo.io bulk match API and store in DataFrame.
    
    Args:
        lead_ids: List of Apollo.io lead IDs to match
    
    Returns:
        DataFrame containing people data with specified fields
    """
    url = "https://api.apollo.io/api/v1/people/bulk_match?reveal_personal_emails=false&reveal_phone_number=false"
    
    payload = {"details": [{"id": id} for id in lead_ids]}
    headers = {
        "accept": "application/json",
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "x-api-key": APOLLO_API_KEY or ""
    }
    print(f"Using Apollo API Key: {APOLLO_API_KEY}")

    try:
        response = requests.post(url, json=payload, headers=headers)
        print(f"Apollo API response status: {response.status_code}")
        print(f"Apollo API response text: {response.text[:500]}")
        response.raise_for_status()
        data = response.json()
        
        # Initialize list to store person data
        people_data = []
        
        if 'matches' in data:
            for person in data['matches']:
                # Get organization details
                org = person.get('organization', {})
                
                # Get education details
                education = person.get('education', [])
                education_str = '; '.join([
                    f"{edu.get('degree', '')} in {edu.get('field_of_study', '')}"
                    for edu in education if edu.get('degree') or edu.get('field_of_study')
                ]) if education else 'N/A'
                
                # Get experience details
                experience = person.get('experience', [])
                experience_str = '; '.join([
                    f"{exp.get('title', '')} at {exp.get('organization', {}).get('name', '')}"
                    for exp in experience if exp.get('title')
                ]) if experience else 'N/A'
                
                # Get organization details including short_description
                org_short_description = org.get('short_description', 'N/A')
                if org_short_description == 'N/A' and 'seo_description' in org:
                    org_short_description = org.get('seo_description', 'N/A')  # Fallback to seo_description if short_description is not available
                
                person_info = {
                    'lead_id': person.get('id', 'N/A'),
                    'name': f"{person.get('first_name', '')} {person.get('last_name', '')}",
                    'linkedin_url': person.get('linkedin_url', 'N/A'),
                    'title': person.get('title', 'N/A'),
                    'headline': person.get('headline', 'N/A'),
                    'email_status': person.get('email_status', 'N/A'),
                    'email': person.get('email', 'N/A'),
                    'organization': org.get('name', 'N/A'),
                    'company_industry': org.get('industry', 'N/A'),
                    'company_keywords': ', '.join(org.get('keywords', [])),
                    'company_website': org.get('website_url', 'N/A'),
                    'company_linkedin': org.get('linkedin_url', 'N/A'),
                    'company_twitter': org.get('twitter_url', 'N/A'),
                    'company_facebook': org.get('facebook_url', 'N/A'),
                    'company_angellist': org.get('angellist_url', 'N/A'),
                    'education': education_str,
                    'experience': experience_str,
                    'company_size': org.get('estimated_num_employees', 'N/A'),
                    'company_founded_year': org.get('founded_year', 'N/A'),
                    'company_location': f"{org.get('city', '')}, {org.get('state', '')}, {org.get('country', '')}"
                }
                people_data.append(person_info)
        
        # Create DataFrame
        df = pd.DataFrame(people_data)
        
        # Print summary
        print(f"\nProcessed {len(lead_ids)} lead IDs")
        print(f"Found {len(df)} matches")
        
        return df
        
    except requests.exceptions.RequestException as e:
        print(f"Error making API request: {e}")
        if hasattr(e, 'response'):
            print(f"Response status code: {e.response.status_code}")
            print(f"Response text: {e.response.text}")
        return pd.DataFrame()
    except Exception as e:
        print(f"Unexpected error: {e}")
        return pd.DataFrame()

if __name__ == "__main__":
    # Example usage
    test_ids = [
        "5ffb3288e187fc000126e479",
        "608a9e3de5abc10001230f6e",
        "6129ca2d7ecc0900011a06b6"
    ]
    
    # Get data and store in DataFrame
    df = get_people_data(test_ids)
    
    # Display DataFrame
    if not df.empty:
        print("\nDataFrame:")
        print(df)
        
        # Optionally save to CSV
        # df.to_csv('apollo_people_data.csv', index=False)
        # print("\nData saved to apollo_people_data.csv")

        # Save enriched data to MongoDB Atlas
        from mongodb_client import save_enriched_data
        data_dicts = df.to_dict('records')
        inserted_ids = save_enriched_data(data_dicts)
        print(f"\nSaved {len(inserted_ids)} records to MongoDB Atlas.")
    else:
>>>>>>> acf195d (Avasyu commit of email scheduling)
        print("No data to save.")