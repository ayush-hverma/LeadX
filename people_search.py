import requests
import json
import os
import dotenv
from typing import List, Dict, Any

dotenv.load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

def get_people_search_results(
    person_titles: List[str],
    include_similar_titles: bool,
    person_locations: List[str],
    company_locations: List[str],
    company_industries: List[str],
    company_names: List[str],         # Company filter
    per_page: int,
    page: int
) -> List[Dict[Any, Any]]:
    """
    Fetch people search results from Apollo.io API.

    Args:
        person_titles: List of job titles to search for
        include_similar_titles: Whether to include similar job titles in search
        person_locations: List of locations where people are based
        company_locations: List of locations where companies are based
        company_industries: List of industries to search in
        company_names: List of company names to filter people by
        per_page: Number of results per page
        page: Page number to fetch (will fetch all pages up to this number)
    Returns:
        List of people dicts
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

    for current_page in range(1, page + 1):
        payload = {
            "per_page": per_page,
            "page": current_page,
            "include_similar_titles": include_similar_titles
        }
        if person_titles and person_titles[0].strip():
            payload["person_titles"] = person_titles
        if company_names and company_names[0].strip():
            payload["organization_names"] = company_names
        if person_locations and person_locations[0].strip():
            payload["person_locations"] = person_locations
        if company_industries and company_industries[0].strip():
            payload["company_industries"] = company_industries
        print("\nPayload:")
        print(json.dumps(payload, indent=2))
        try:
            response = requests.post(url, headers=headers, json=payload)
            print(f"Apollo.io API status: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            print(f"\nPage {current_page} - Response has {len(data.get('people', []))} people")
            if 'people' in data:
                for person in data['people']:
                    if person.get('email_status') != 'unavailable':
                        org_name = person.get('organization', {}).get('name')
                        if not org_name or org_name == 'N/A':
                            employment = person.get('employment_history', [])
                            org_name = None
                            for job in employment:
                                if job.get('current') and job.get('organization_name'):
                                    org_name = job['organization_name']
                                    break
                            if not org_name and employment:
                                org_name = employment[0].get('organization_name', 'N/A')
                            if not org_name:
                                org_name = 'N/A'
                        person_data = {
                            'id': person.get('id', 'N/A'),
                            'name': f"{person.get('first_name', '')} {person.get('last_name', '')}",
                            'title': person.get('title', 'N/A'),
                            'company': org_name,
                            'email': person.get('email', 'N/A'),
                            'email_status': person.get('email_status', 'N/A'),
                            'linkedin_url': person.get('linkedin_url', 'N/A'),
                            'location': person.get('location', 'N/A'),
                            'page_number': current_page
                        }
                        all_results.append(person_data)
                if len(data['people']) < per_page:
                    break
        except requests.exceptions.RequestException as e:
            print(f"❌ Error on page {current_page}: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response status code: {e.response.status_code}")
                print(f"Response text: {e.response.text}")
            break
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error on page {current_page}: {e}")
            print(f"Raw response: {response.text}")
            break
    # Post-filter: strictly match company names if provided
    if company_names and company_names[0].strip():
        filtered_results = []
        company_names_lower = [c.lower() for c in company_names]
        for person in all_results:
            person_company = person['company'].lower() if person['company'] and person['company'] != 'N/A' else ''
            # Allow partial match for any company name entered by user, but if no match, keep the person
            if person_company and any(cn in person_company for cn in company_names_lower):
                filtered_results.append(person)
        # Only filter if we actually found matches, otherwise keep all_results
        if filtered_results:
            all_results = filtered_results
    if all_results:
        print("\n✅ Found People:")
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
        print("❌ No results found.")
    return all_results


if __name__ == "__main__":
    # Example usage
    results = get_people_search_results(
        person_titles=["Partner", "Investor"],
        include_similar_titles=False,
        person_locations=["India"],
        company_locations=[],
        company_industries=["Venture Capital & Private Equity"],
        company_names=["Sequoia Capital"],
        per_page=5,
        page=1
    )
    # Print results summary
    print(f"\nTotal results returned: {len(results)}")
