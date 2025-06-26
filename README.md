# LeadxV2 

A Streamlit application for automating lead generation, enrichment, and email outreach using Apollo.io API.

## Features

- **People Search**: Search for leads using job titles, locations, and industries
- **People Enrichment**: Enrich lead profiles with additional data
- **Mail Generation**: Generate personalized emails using AI
- **Email Sending**: Send generated emails in batches

## Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/LeadxV2.git
cd LeadxV2
```

2. Create a virtual environment and activate it:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root with your API keys:
```
APOLLO_API_KEY=your_apollo_api_key
```

5. Run the application:
```bash
streamlit run app.py
```

## Project Structure

```
LeadxV2/
├── app.py                 # Main Streamlit application
├── people_search.py       # Apollo.io search functionality
├── people_enrich.py       # Lead enrichment functionality
├── mail_generation.py     # Email generation pipeline
├── email_sender.py        # Email sending functionality
├── requirements.txt       # Project dependencies
├── .env                   # Environment variables (not in git)
└── README.md             # Project documentation
```

## Usage

1. **People Search**
   - Enter job titles, locations, and industries
   - Configure search parameters
   - View and download search results

2. **People Enrichment**
   - Enrich selected leads with additional data
   - View and download enriched profiles

3. **Mail Generation**
   - Upload product information
   - Generate personalized emails
   - View and download generated emails

4. **Send Emails**
   - Configure email sending parameters
   - Send emails in batches
   - Track sending results

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 
