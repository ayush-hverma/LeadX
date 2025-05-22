import requests
import json
import os
import dotenv
import pandas as pd
from typing import List, Dict, Any

dotenv.load_dotenv()

def get_people_search_results(
    person_titles: List[str],
    include_similar_titles: bool,
    person_locations: List[str],
    company_locations: List[str],
    company_industries: List[str],
    per_page: int,
    page: int
) -> List[Dict[Any, Any]]:
    """
    Fetch people search results from Apollo.io API.
    If page > 1, fetches all results from page 1 to the requested page.
    
    Args:
        person_titles: List of job titles to search for
        include_similar_titles: Whether to include similar job titles in search
        person_locations: List of locations where people are based
        company_locations: List of locations where companies are based
        company_industries: List of industries to search in
        per_page: Number of results per page
        page: Page number to fetch (will fetch all pages up to this number)
    """
    url = "https://api.apollo.io/api/v1/mixed_people/search"
    api_key = os.getenv("APOLLO_API_KEY")
    
    if not api_key:
        print("Error: APOLLO_API_KEY not found in .env file")
        return []

    headers = {
        "accept": "application/json",
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "X-Api-Key": api_key
    }

    all_results = []
    print(f"\nFetching results from pages 1 to {page}...")
    
    # Fetch results from page 1 up to the requested page
    for current_page in range(1, page + 1):
        payload = {
            "person_titles": person_titles,
            "include_similar_titles": include_similar_titles,
            "person_locations": person_locations,
            "company_locations": company_locations,
            "email_status": ["verified"],
            "company_industries": company_industries,
            "per_page": per_page,
            "page": current_page,
            "with_email_data": True
        }

        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            
            data = response.json()
            
            if 'people' in data:
                # Filter out unavailable results and format the data
                for person in data['people']:
                    if person.get('email_status') != 'unavailable':
                        person_data = {
                            'id': person.get('id', 'N/A'),
                            'name': f"{person.get('first_name', '')} {person.get('last_name', '')}",
                            'title': person.get('title', 'N/A'),
                            'company': person.get('organization', {}).get('name', 'N/A'),
                            'email': person.get('email', 'N/A'),
                            'email_status': person.get('email_status', 'N/A'),
                            'linkedin_url': person.get('linkedin_url', 'N/A'),
                            'location': person.get('location', 'N/A'),
                            'page_number': current_page
                        }
                        all_results.append(person_data)
                
                # If we got fewer results than per_page, we've reached the end
                if len(data['people']) < per_page:
                    break
                    
        except requests.exceptions.RequestException as e:
            print(f"Error making API request for page {current_page}: {e}")
            break
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON response for page {current_page}: {e}")
            break

    if all_results:
        print("\nFound People:")
        print("-" * 80)
        for person in all_results:
            print(f"ID: {person['id']}")
            print(f"Name: {person['name']}")
            print(f"Title: {person['title']}")
            print(f"Company: {person['company']}")
            print(f"Email: {person['email']}")
            print(f"Location: {person['location']}")
            print(f"LinkedIn: {person['linkedin_url']}")
            print(f"Page: {person['page_number']}")
            print("-" * 80)
        print(f"\nTotal results found: {len(all_results)}")
    else:
        print("No results found.")
    
    return all_results

if __name__ == "__main__":
    # Example usage
    results = get_people_search_results(
        person_titles=["Partner", "Investor"],
        include_similar_titles=False,
        person_locations=["India"],
        company_locations=["India"],
        company_industries=["Venture Capital & Private Equity"],
        per_page=5,
        page=3  # This will fetch results from pages 1, 2, and 3
    )