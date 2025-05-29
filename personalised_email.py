from dotenv import load_dotenv
import os
import warnings
import io
import google.generativeai as genai
import time
import asyncio
from pydantic import BaseModel, Field
import json
import re
import logging
import streamlit as st
from outlook_auth import get_outlook_auth_url

warnings.filterwarnings("ignore", category=UserWarning)

# Load environment variables
load_dotenv()

# Configure Gemini
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

class EmailResponse(BaseModel):
    subject: str
    body: str
    lead_id: str

# Define the email generation prompt
subject_style = """
Write a strict, direct, and to-the-point subject line (60-90 characters) that captures the core value or insight of the email. The subject line must:
- Be a concise heading of the email body, focused on how we can help the client or the reason for reaching out.
- NOT contain any greetings (like hello, hi, hey, etc.), the receiver's name, or any personal references.
- NOT contain any softening, fluff, or generic phrases (like follow-up, introduction, etc.).
- NOT contain any statistics or numbers.
- NOT mention the recipient's company name or any other company names.
- Be specific, actionable, and engaging, reflecting the main value or insight of the email.
- Mention the product details in the subject line and highlight the benefits of the product.
- Mention how the product can solve the problem of the lead.
- Only state the core value or insight, with no unnecessary words or pleasantries.
- DO NOT use the detailed body style guide for the subject.
"""

body_style = """
Start with a greeting and then go on to say that you are reaching out because of [reason].
Do not use too much buttering and unnecessary words specially after the first line (I was going through your profile and noticed your inspiring journey is phenomenal,fabulous, etc. Don't use such unnecessary buttering. Jus go like "I was going through your profile and noticed [mention things which are relevant to product and matches with the lead's profile, no unnecessary buttering]")
Be casual, friendly and direct but not too casual.
Do not use general statements like "I was going through your profile and noticed your inspiring journey is phenomenal,fabulous, etc."
Do not use generic phrases like " I was checking out <company name> and noticed <something relevant to product>".
Never print the lead's id in the email.
Always mention the product name as provided in the product details.
Always mention the company name as 'PanScience Innovations' when referring to the company.
Never mention the sender's name in the email except in the signature.
It should be a short, personalized email (150-200 words) to a potential lead who could benefit from your product/service/solution. It should:
                    1.  Start with deep personalization — Reference something specific about the lead's business, role, recent announcement, or pain point you've identified. Show you understand them—not just their company name. Use different phrases/styles/variation/words to start the email.
                    2.  Make a relevant connection — Briefly explain that you are from PanScience Innovations and why you're reaching out. Make it clear why they specifically are a fit for what you offer.
                    3.  Talk about the problems in the lead's industry and how [PRODUCT_NAME] can solve the problem.
                    4.  Focus on value (not features) — Position [PRODUCT_NAME] around a problem or opportunity that matters to them. Avoid a hard sell—offer insight, benefit, or a useful idea that shows you can help.
                    5.  Keep it short and natural — Write like a human, not a sales robot. 
                    6.  End with a simple CTA (e.g., "open to a quick chat?" or "would you be interested in exploring this further?").
                    7.  End the email with "Best Regards," on a new line, followed by a blank line (the system will automatically add the sender's name on the next line)

When describing the product, include:
1.  Start with the product name and then go on to describe the product.
2. Core Problem Solved: Clearly state the main problem [PRODUCT_NAME] addresses in their industry
3. Key Features: Mention 2-3 most relevant features that directly solve their pain points
4. Specific Benefits: Include concrete benefits with numbers/statistics where possible (e.g., "reduces processing time by 40%")
5. Industry-Specific Value: Explain how [PRODUCT_NAME] is particularly valuable for their specific industry/role
6. Implementation Ease: Briefly mention how easy it is to get started or integrate

Use human like tone and language. Follow this style:
1. First Person Pronouns: I, me, my, mine, we, us, our, ours. Write as if you are the one talking to the lead and do not use generalised statements.
2. Fillers & Disfluencies
Spoken or informal written human language often includes:
    •   uh, um, like, you know, kinda, sorta, actually, basically, literally, just, u, so, of course, ok, sure, etc.
    •   contractions: gonna, wanna, gotta, ain't, don't, can't, won't, wasn't, weren't, wouldn't, couldn't, shouldn't, needn't, aren't, isn't, etc.
3. Personal Experience Markers
    •   I think, I believe, I feel, in my opinion, according to me, in my view, as per me, as I see, as I feel, as I believe, as I think, so, of course, etc.
    •   yesterday, last week, when I was in school, last month, last year, just last week, just last month, just last year, first thing in the morning, last night, morning, evening, etc.
    •   my friend, my boss, my mom, my friend's friend, my friend's boss, my friend's mom, etc.
4. Typos and Misspellings
Humans often make minor spelling or grammatical errors:
    •   definately → definitely
    •   alot → a lot
    •   seperate → separate
    •   seperately → separately
    •   seperated → separated
    •   you're → you are
    •   your → you're
    •   there → their
    •   theirs → there's
    •   they're → they are
    •   we're → we are
    •   we've → we have
    •   we'll → we will
    •   wasn't → was not
    •   weren't → were not
    •   wouldn't → would not
    •   couldn't → could not
    •   shouldn't → should not
    •   needn't → need not
    •   aren't → are not
    •   isn't → is not
5. Emotional/Spontaneous Expressions
Humans express feelings impulsively or with less filter:
    •   wow, amazing, omg, oh my god, oh my gosh, oh my gosh, oh my gosh, aww, haha, lol, rofl, lmao, hehehe,  damn, smh, idk, meh, pfft, yikes, whaaat, no way, sigh, yay, wuhoo, hell yeah, hell no, hell yeah, hell no,hahaha, haha, woohoo, woot, yay, yaaay, whoa, woah, omg, oh my god, lol, lmao, rofl, hehe, heehee, yaaas, yesss, wow, wowza, omgosh, oh wow, aww, awww, whew, phew, omg yaaay, ooooh, oooh la la, huzzah, let's gooo, heck yeah, hell yeah, oh!, ohhh, huh?, no way!, whaaat?!, yikes, dang, daaaang, whaaat the—, ugh, ughhh, meh, pfft, grrr, smh, sigh, sheesh, huhh, etc.
    •   love it, hate that, so cool, super weird, so bad, so good, so happy, so sad, so excited, so nervous, hahaha, haters gonna hate, lovers gonna love, etc.

Important: The email body should end with "Best Regards," on a new line, followed by a blank line. DO NOT include the sender's name in the email body - it will be added automatically by the system.
"""

product_database = {
    "parcha": {
        "problem_it_solves": [
            "Long OPD wait times due to high patient footfall",
            "Short consultation durations and overworked staff",
            "Manual processes and lack of automation",
            "Poor patient engagement and adherence",
            "Lack of authentic health data for governance and research",
            "Insufficient infrastructure and digital tools in rural/NGO settings",
            "Inefficiencies and errors in emergency room triaging",
            "Limited mental healthcare access in academic institutions"
        ],
        "solution": [
            "A comprehensive AI-powered digital health platform covering OPD, emergency, air-gapped, and wellness workflows",
            "Supports the full healthcare journey—onboarding, consultation, follow-up, and monitoring",
            "Interoperable with existing hospital systems and government initiatives like ABHA and Ayushman Bharat",
            "Offers remote, offline-compatible deployments, smart dashboards, and CDSS support"
        ],
        "unique_selling_point": [
            "End-to-end digital healthcare platform functional in both online and offline modes",
            "Powered by advanced AI/LLM models trained on Indian and global clinical standards (ICMR, WHO, CDC, etc.)",
            "First-in-class emergency room automation tools including triage classification and resource dashboards",
            "Deep focus on underserved areas and community care",
            "Modular, white-label deployment suitable for hospitals, NGOs, and academic institutions"
        ],
        "features": [
            "Smart OPD with AI-led triaging, diagnosis, and prescriptions",
            "Clinical Decision Support System (CDSS) with alerts for ADRs and contra-indications",
            "Patient app with teleconsultation, medication reminders, and adherence tracking",
            "Emergency module with auto-triaging and saturation dashboards",
            "Air-gapped mode for rural deployment with vitals tracking, inventory management, and follow-up tools",
            "WellKiwi for campus wellness including mental health support, insurance, and health analytics",
            "Dashboards for administrators, wardens, and doctors",
            "Interoperability with existing HIS, ABHA, PHRs, pharmacies, and diagnostics (e.g., 1mg integration)"
        ],
        "benefits": [
            "Reduces patient wait time and improves quality of consultations",
            "Supports doctors with AI-based decision tools",
            "Boosts hospital efficiency through automation and data insights",
            "Enables healthcare access in rural and remote regions",
            "Improves patient follow-up, engagement, and outcomes",
            "Promotes mental wellness and proactive health management in students",
            "Enables fast, accurate emergency triaging",
            "Standardizes care protocols and improves collaboration among stakeholders"
        ]
    },
    "predco": {
        "problem_it_solves": [
            "Unplanned equipment failures causing production delays and financial losses",
            "Inefficient maintenance strategies leading to safety concerns and operational disruptions",
            "Fragmented systems and lack of centralized monitoring in industrial operations",
            "Lack of real-time visibility and decision-making across assets and departments",
            "Stockouts, overstocking, and asset mismanagement in supply chain operations",
            "Manual, error-prone inventory tracking methods",
            "Delayed threat detection and response in surveillance operations"
        ],
        "solution": [
            "AI-powered predictive maintenance and condition monitoring platform",
            "Digital Twin technology to simulate and optimize operations in real time",
            "Smart inventory management using RFID and computer vision",
            "Centralized monitoring and data integration for legacy systems and SCADA",
            "GenAI-powered assistants for real-time document retrieval and support",
            "Geofencing solutions for real-time asset tracking and alerts",
            "Role-based access and proactive alert systems for operations control"
        ],
        "unique_selling_point": [
            "Unified AI-driven platform integrating IoT, ML, and digital twin technologies",
            "Real-time actionable insights across a wide array of machinery and assets",
            "Highly scalable and adaptable solutions tailored for legacy and modern systems",
            "Seamless integration with existing infrastructure, no new hardware needed",
            "Use-case agnostic architecture spanning energy, manufacturing, logistics, and security"
        ],
        "features": [
            "Dynamic dashboards with real-time visualization and KPI tracking",
            "Customizable alerts based on threshold breaches and anomaly detection",
            "Real-time data acquisition from diverse IoT sensors",
            "Integrated ML models to predict equipment failure and remaining useful life",
            "Computer vision for automated shelf and item recognition",
            "GenAI tools for document digitization and knowledge retrieval",
            "Geofencing alerts and asset movement tracking",
            "Role-based access and operational rule configuration"
        ],
        "benefits": [
            "Reduce equipment downtime by 35-40%",
            "Extend asset lifespan by up to 30%",
            "Lower maintenance costs by 8-12%",
            "Improve inventory turnover by 40% and reduce shrinkage by 50%",
            "Minimize manual monitoring efforts and decision-making delays",
            "Achieve up to 87% accuracy in lifecycle predictions of critical components",
            "Enhance workplace safety and compliance through AI-powered surveillance",
            "Boost operational transparency and inter-departmental collaboration"
        ]
    },
    "investorbase": {
        "problem_it_solves": [
            "Overwhelming volume of inbound pitch decks makes it hard for VCs to evaluate each one thoroughly",
            "Current deal evaluation processes are manual, slow, biased, and inconsistent",
            "Due diligence is time-consuming, taking up to 2 weeks per deal",
            "Missed opportunities due to delays and inefficient workflows"
        ],
        "solution": [
            "AI-driven pitch deck analyzer that extracts key information instantly",
            "Human-augmented analysis ensures depth and credibility of insights",
            "Dynamic opportunity scoring aligned with the fund's investment thesis",
            "Automated red flag detection, validation, and memo generation"
        ],
        "unique_selling_point": [
            "Combines speed and precision of AI with expert analyst judgment",
            "Customizable scoring tailored to specific investment theses",
            "Scalable solution that handles 10 to 1,000+ decks per month",
            "Delivers analyst-grade insights in 24–48 hours"
        ],
        "features": [
            "Pitch Deck Analyzer – instant insights from uploaded decks",
            "Thesis Alignment – auto scoring of decks based on fund criteria",
            "InsightMaster – AI assistant for deeper analysis",
            "Auto Analysis + Alerts – real-time notifications for matching deals",
            "Market Intel – context-rich competitive and news insights",
            "Investor Research – deeper, customized insights beyond basic data",
            "Automated Collection – centralized collection from various sources",
            "Investor Memos – auto-generated, ready-to-use investment memos"
        ],
        "benefits": [
            "Faster and smarter deal evaluation with reduced manual effort",
            "Increased chances of discovering high-potential investments",
            "Higher quality decisions through objective and consistent scoring",
            "Significant time savings in screening and due diligence",
            "Enhanced founder engagement and reduced deal drop-offs"
        ]
    },
    "sankalpam": {
        "problem_it_solves": [
            "Inefficient temple operations",
            "Outdated communication",
            "Inadequate resource management",
            "Limited accessibility for devotees",
            "Challenges in preserving cultural heritage",
            "Managing religious tourism"
        ],
        "solution": [
            "A technology-driven platform that empowers temples through AI, IoT, and cloud tools",
            "Improves operational efficiency",
            "Enhances devotee engagement",
            "Enables secure fundraising",
            "Digitizes cultural assets",
            "Modernizes communication"
        ],
        "unique_selling_point": [
            "Bridges the gap between tradition and modernity",
            "Offers temples smart management tools",
            "Provides immersive devotee experiences",
            "Includes government collaboration frameworks",
            "All under one unified platform"
        ],
        "features": [
            "AI-powered surveillance and crowd control",
            "IoT-enabled resource and environmental monitoring",
            "Mobile app for temple services, communication, and ticketing",
            "Digital donation platforms with global access",
            "AR/VR-based cultural immersion experiences",
            "Live streaming of religious rituals (Darshan)",
            "Virtual pooja booking (Sankalp)",
            "Online astrology consultations (Jyotish Vani)",
            "Sacred offering delivery (Prasadam)",
            "Pilgrimage planning assistance (Yatra)",
            "Comprehensive Hindu knowledge repository (Gyan Kosh)"
        ],
        "benefits": [
            "Enhanced operational efficiency and crowd management",
            "Reduced administrative costs and better resource allocation",
            "Increased donations and new revenue streams",
            "Greater transparency in financial management",
            "Improved security and heritage preservation",
            "Seamless access to services through online bookings and virtual participation",
            "Personalized spiritual experiences",
            "Improved accessibility for elderly and differently-abled",
            "Interactive cultural education and deeper immersion"
        ]
    },
    "opticall": {
        "problem_it_solves": [
            "High call volumes and inconsistent call handling quality",
            "Delayed insights and ineffective coaching",
            "Increased costs and reduced performance",
            "Chaotic lead volumes and cold leads in sales",
            "Lack of real-time visibility into performance gaps",
            "Overwhelmed agents and long wait times",
            "Inconsistent service and buried insights",
            "Low customer satisfaction and limited performance visibility"
        ],
        "solution": [
            "A unified AI platform that automates queries via bots",
            "Real-time agent support and assistance",
            "Customizable dashboards for actionable insights",
            "Automated repetitive lead engagement",
            "Real-time pitch coaching for sales",
            "Virtual agents for customer queries",
            "Performance insights from every call",
            "Support quality improvement tools"
        ],
        "unique_selling_point": [
            "Modular, phygital-ready architecture with deep tech",
            "Lightweight deployment that fits any workflow",
            "Real-time insights across audio, video, and text",
            "No change required in existing sales workflows",
            "Flexible tools and custom templates",
            "Sales-specific dashboards",
            "Fully customizable to existing support operations"
        ],
        "features": [
            "Agent Assist with automated call scoring",
            "Dynamic dashboards and vernacular engine (28+ languages)",
            "Real-time prompts and video/audio analytics",
            "Virtual sales agents and real-time objection handling",
            "Pitch prompts and AI-powered knowledge base",
            "Performance dashboards and multilingual support",
            "Coaching tools and real-time agent guidance",
            "Visual checklists and instant knowledge access",
            "Automated escalations and compliance support"
        ],
        "benefits": [
            "+18 CSAT points improvement",
            "95% QA coverage (up from 2%)",
            "22% reduction in support costs",
            "12% increase in conversions",
            "9% growth in monthly bookings",
            "18% reduction in customer acquisition cost",
            "Accelerated deal closures",
            "Real-time insights and automation"
        ]
    },
    "indikaai": {
        "problem_it_solves": [
            "Unclear AI roadmaps and data readiness issues",
            "Lack of internal expertise in AI implementation",
            "Difficulty integrating AI with existing systems",
            "Rapid technology changes affecting ROI",
            "Challenges in effective AI implementation"
        ],
        "solution": [
            "End-to-end AI solutions including strategy formulation",
            "Data preparation and foundation model selection",
            "Model fine-tuning and deployment",
            "Continuous monitoring and support",
            "Tailored products for healthcare, judiciary, infrastructure, and customer service"
        ],
        "unique_selling_point": [
            "Comprehensive AI development lifecycle support",
            "Domain-specific AI products",
            "Access to 50,000+ experts across 100+ languages",
            "Experience across judiciary, healthcare, infrastructure, and BFSI sectors"
        ],
        "features": [
            "AI strategy and roadmap development",
            "Data digitization, anonymization, and labeling",
            "Custom generative AI, NLP, computer vision, and audio processing",
            "Platforms: DigiVerse, DataStudio, FlexiBench",
            "Industry-specific AI solutions (Nyaay AI, PredCo, RoadVision AI, Parchaa AI, Choice AI)",
            "Ready-to-deploy tools (OCR, speech-to-text, trust & safety, synthetic data generation)"
        ],
        "benefits": [
            "Faster and smoother AI adoption",
            "Improved operational efficiency and automation",
            "Enhanced decision-making through AI-powered insights",
            "Access to scalable AI solutions tailored to specific industries",
            "Expert support across all AI development stages",
            "Multilingual and multidisciplinary support"
        ]
    },
    "flexibench": {
        "problem_it_solves": [
            "Lack of trained professionals with domain-specific expertise",
            "Need for culturally and linguistically aware AI development",
            "Limited access to real project experience",
            "Gap between academic knowledge and practical AI implementation"
        ],
        "solution": [
            "A talent development hub for AI training",
            "Hands-on experience with real AI projects",
            "Domain-specific expertise development",
            "Earning opportunities while learning",
            "Comprehensive training in AI tasks"
        ],
        "unique_selling_point": [
            "Combines real-world AI project exposure with specialized training",
            "Global language support and cultural awareness",
            "Transforms professionals into AI contributors",
            "Practical experience with real industry projects"
        ],
        "features": [
            "Training across 100+ languages for localization",
            "Bias reduction techniques",
            "Tailored learning paths in law, medicine, engineering, and linguistics",
            "Real industry experience through live AI projects",
            "Focus on essential AI lifecycle skills",
            "Support for 20+ academic fields",
            "60,000+ experts onboarded"
        ],
        "benefits": [
            "Earn while gaining AI industry experience",
            "Transform domain knowledge into valuable AI contributions",
            "Enable accurate, culturally aware AI systems",
            "Promote India's global role in AI excellence",
            "Join a global network of trained professionals"
        ]
    },
    "inspireai": {
        "problem_it_solves": [
            "Content creator burnout and creative blocks",
            "Inefficiencies in content generation",
            "Difficulty maintaining consistent content across platforms",
            "Time-consuming content creation process",
            "Challenges in personalizing content at scale"
        ],
        "solution": [
            "AI-powered platform for content generation",
            "Personalized, high-quality content creation",
            "Scalable content production system",
            "Automated content optimization",
            "Integrated content management tools"
        ],
        "unique_selling_point": [
            "Combines personalization with scalability",
            "AI-powered creative storytelling",
            "Tailored for content marketers and creators",
            "Multi-platform content optimization"
        ],
        "features": [
            "AI-driven content generation",
            "Personalized content suggestions",
            "Multi-platform optimization",
            "Content calendar integration",
            "Real-time collaboration tools",
            "Performance analytics and insights"
        ],
        "benefits": [
            "Saves time and reduces creative fatigue",
            "Increases content output without compromising quality",
            "Boosts audience engagement through personalized storytelling",
            "Streamlines content workflow for teams and individuals",
            "Improves ROI through data-driven content strategies"
        ]
    },
    "insituate": {
        "problem_it_solves": [
            "Lack of AI talent in businesses",
            "Compliance concerns with sensitive data",
            "Compatibility issues with legacy systems",
            "Complex AI implementation process",
            "Security and privacy challenges"
        ],
        "solution": [
            "Secure, no-code, end-to-end AI development platform",
            "State-of-the-art LLMs and RAG pipelines",
            "In-house data management",
            "Legacy system integration",
            "Comprehensive AI development tools"
        ],
        "unique_selling_point": [
            "No-code, one-stop solution for AI copilots",
            "Legacy system integration capabilities",
            "Ironclad data security",
            "Rapid deployment within a week"
        ],
        "features": [
            "In-situ (on-premise) database",
            "No-code development interface",
            "Ironclad security protocols",
            "State-of-the-art LLM and RAG integration",
            "100+ pre-built templates",
            "Compatibility with legacy software",
            "Gridsearch for copilot optimization",
            "Sentry mode for continuous improvement",
            "AutoLLM deployment within a week",
            "LLMOps capabilities",
            "On-cloud and on-premise deployment options",
            "Team collaboration and one-click export"
        ],
        "benefits": [
            "Accelerates enterprise AI adoption without requiring in-house AI talent",
            "Maintains data privacy and regulatory compliance",
            "Saves time and cost (AutoLLM in 1 week vs. traditional 24 months)",
            "Streamlines development and deployment with minimal technical barriers",
            "Empowers internal teams to create domain-specific copilots",
            "Taps into a large, global, multi-vertical market"
        ]
    },
    "choiceai": {
        "problem_it_solves": [
            "Lack of regulatory framework for OTT content certification",
            "Ineffective filtering of offensive or harmful content",
            "Viewer concerns about explicit/inappropriate content",
            "Limited parental controls",
            "Delays in content release due to censorship",
            "Lack of personalized content access"
        ],
        "solution": [
            "AI tool for responsible content distribution",
            "Personalized viewer experience system",
            "Advanced content tagging and filtering",
            "Parental controls and content warnings",
            "Streamlined certification process",
            "Intelligent content assessment"
        ],
        "unique_selling_point": [
            "Comprehensive customization options",
            "Real-time AI moderation",
            "Personalized viewing experience",
            "Compliance with censorship requirements",
            "Collaboration with CBFC and OTT platforms"
        ],
        "features": [
            "Choice Tagger for content classification",
            "Choice Viewer for content filtering",
            "AI-powered moderation and certification",
            "Personalized recommendations",
            "Parental control and age-based filtering",
            "Collaboration tools for CBFC",
            "OEM integration with OTT platforms"
        ],
        "benefits": [
            "Safe and personalized content viewing",
            "Effective parental control features",
            "Creative freedom with regulatory compliance",
            "Enhanced user experience for OTT platforms",
            "Streamlined CBFC verification process",
            "Support for independent creators",
            "Faster content approval process"
        ]
    }
}

def generate_email_for_single_lead(lead_details: dict, product_details: str, product_name: str = None) -> dict:
    """Generate a personalized email for a single lead."""
    try:
        # Log the start of email generation
        logging.info(f"Starting email generation for lead: {lead_details.get('name', 'Unknown')} (ID: {lead_details.get('id', 'Unknown')})")
        
        # Use explicit product_name if provided, else extract from product_details
        if product_name is None:
            for key in product_database.keys():
                if key.lower() in product_details.lower():
                    product_name = key
                    break
            if not product_name:
                for line in product_details.split('\n'):
                    if any(key.lower() in line.lower() for key in product_database.keys()):
                        for key in product_database.keys():
                            if key.lower() in line.lower():
                                product_name = key
                                break
                        if product_name:
                            break
            if not product_name:
                product_name = "our product"  # Fallback if no product name found
                logging.warning(f"No product name found in product details, using fallback: {product_name}")

        recipient_name = lead_details.get('name', 'No recipient')
        recipient_email = lead_details.get('email', 'No email provided')

        prompt = f"""
        Generate a personalized email for the following lead:
        
        Lead Details:
        {json.dumps({k: v for k, v in lead_details.items() if k != 'id'}, indent=2)}
        
        Product Details:
        {product_details}
        
        Follow this style guide for the subject:
        {subject_style}
        
        Follow this style guide for the body:
        {body_style}
        
        Important: 
        1. DO NOT include any lead IDs, reference numbers, or technical identifiers in the email.
        2. End the email body with "Best Regards," on a new line, followed by a blank line.
        3. DO NOT include any sender name in the email body.
        4. Always use "{product_name}" instead of [PRODUCT_NAME] when referring to the product.
        5. The email will be sent to: {recipient_name} <{recipient_email}>
        
        Return ONLY the email subject and body in this exact JSON format:
        {{
            "subject": "The subject line",
            "body": "The email body ending with 'Best Regards,' on a new line"
        }}
        """
        
        # Get response from Gemini
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=5000,
            )
        )
        
        # Parse the response
        try:
            response_text = response.text
            print(f"\n📄 Raw response from Gemini for lead {recipient_name}:")
            print(response_text)
            logging.info(f"Raw response from Gemini for lead {recipient_name}: {response_text}")
            
            # Clean the response text to ensure it's valid JSON
            response_text = response_text.strip()
            
            # Remove markdown code blocks if present
            if response_text.startswith('```'):
                response_text = response_text.split('```', 2)[1]
            if response_text.endswith('```'):
                response_text = response_text.rsplit('```', 1)[0]
            response_text = response_text.strip()
            
            # More aggressive JSON cleaning
            response_text = re.sub(r'\n\s*"', '"', response_text)  # Remove newlines and spaces before quotes
            response_text = re.sub(r'"\s*\n\s*', '"', response_text)  # Remove newlines and spaces after quotes
            response_text = re.sub(r'\n\s*}', '}', response_text)  # Remove newlines and spaces before closing brace
            response_text = re.sub(r'{\s*\n\s*', '{', response_text)  # Remove newlines and spaces after opening brace
            response_text = re.sub(r',\s*\n\s*', ', ', response_text)  # Clean up commas with newlines
            response_text = re.sub(r'\s+', ' ', response_text)  # Replace multiple spaces with single space
            
            print(f"\n🧹 Cleaned response text:")
            print(response_text)
            logging.info(f"Cleaned response text: {response_text}")
            
            # Try to parse the JSON directly first
            try:
                response_json = json.loads(response_text)
            except json.JSONDecodeError:
                # If direct parsing fails, try to extract JSON using regex
                json_match = re.search(r'\{[^{}]*\}', response_text)
                if json_match:
                    try:
                        response_json = json.loads(json_match.group())
                    except json.JSONDecodeError:
                        # If still failing, try to manually construct JSON
                        subject_match = re.search(r'"subject"\s*:\s*"([^"]*)"', response_text)
                        body_match = re.search(r'"body"\s*:\s*"([^"]*)"', response_text)
                        
                        if subject_match and body_match:
                            response_json = {
                                "subject": subject_match.group(1),
                                "body": body_match.group(1)
                            }
                        else:
                            # Last resort: try to extract any text between quotes after "subject" and "body"
                            subject_match = re.search(r'subject["\s:]+([^"]+)', response_text, re.IGNORECASE)
                            body_match = re.search(r'body["\s:]+([^"]+)', response_text, re.IGNORECASE)
                            
                            if subject_match and body_match:
                                response_json = {
                                    "subject": subject_match.group(1).strip(),
                                    "body": body_match.group(1).strip()
                                }
                            else:
                                raise ValueError("Could not extract subject and body from response")
                else:
                    raise ValueError("No valid JSON found in response")
            
            print(f"\n✅ Parsed JSON response:")
            print(json.dumps(response_json, indent=2))
            logging.info(f"Parsed JSON response for lead {recipient_name}: {response_json}")
            
            # Defensive: ensure 'subject' and 'body' keys exist and are strings
            subject = response_json.get("subject", "")
            body = response_json.get("body", "")
            
            # Clean and validate subject
            if isinstance(subject, str):
                subject = subject.strip()
            else:
                subject = str(subject).strip()
                print(f"⚠️ Subject was not a string, converted to: {subject}")
                logging.warning(f"Subject was not a string for lead {recipient_name}, converted to: {subject}")
            
            # Clean and validate body
            if isinstance(body, str):
                body = body.strip()
            else:
                body = str(body).strip()
                print(f"⚠️ Body was not a string, converted to: {body}")
                logging.warning(f"Body was not a string for lead {recipient_name}, converted to: {body}")
            
            if not subject:
                print(f"❌ Empty subject in model response")
                logging.error(f"Empty subject in model response for lead {recipient_name}: {response_json}")
                subject = "[No subject generated]"
            if not body:
                print(f"❌ Empty body in model response")
                logging.error(f"Empty body in model response for lead {recipient_name}: {response_json}")
                body = "[No body generated]\n\n"
            
            body = body.replace("[PRODUCT_NAME]", product_name)
            if not body.endswith('\n\n'):
                body = body.rstrip() + '\n\n'
            
            print(f"\n✨ Successfully generated email:")
            print(f"Subject: {subject}")
            print(f"Body: {body[:100]}...")
            logging.info(f"Successfully generated email for lead {recipient_name}")
            return {
                "subject": subject,
                "body": body,
                "lead_id": lead_details.get("id", ""),
                "recipient": recipient_name,
                "recipient_email": recipient_email
            }
            
        except Exception as e:
            print(f"\n❌ Error parsing response: {str(e)}")
            print(f"Response text: {response.text if 'response' in locals() else ''}")
            logging.error(f"Error parsing response for lead {recipient_name}: {str(e)} | Response text: {response.text if 'response' in locals() else ''}")
            return {
                "subject": "[No subject generated]",
                "body": "[No body generated]\n\n",
                "lead_id": lead_details.get("id", ""),
                "recipient": recipient_name,
                "recipient_email": recipient_email
            }
            
    except Exception as e:
        logging.error(f"Error generating email for lead {lead_details.get('name', 'Unknown')}: {str(e)}")
        return {
            "subject": "Error generating email",
            "body": f"An error occurred while generating the email: {str(e)}\n\n",
            "lead_id": lead_details.get("id", ""),
            "recipient": lead_details.get('name', ''),
            "recipient_email": lead_details.get('email', '')
        }

def generate_email_for_multiple_leads(leads_list: list, product_details: str) -> list:
    """
    Generate personalized emails for multiple leads
    
    Args:
        leads_list (list): List of dictionaries, where each dictionary contains lead details with keys:
            - name: str
            - lead_id: str
            - experience: str
            - education: str
            - company: str
            - company_overview: str
            - company_industry: str
        product_details (str): Product documentation/information
        
    Returns:
        list: List of dictionaries, each containing 'subject', 'body', and 'lead_id' of the email
    """
    if not leads_list:
        print("❌ Error: No leads provided in the list")
        logging.error("No leads provided in the list")
        raise ValueError("No leads provided in the list")

    print(f"\n📧 Starting email generation for {len(leads_list)} leads")
    logging.info(f"Starting email generation for {len(leads_list)} leads")
    all_emails = []
    batch_size = 5
    successful_leads = 0
    failed_leads = 0

    for i in range(0, len(leads_list), batch_size):
        batch_leads = leads_list[i:i + batch_size]
        print(f"\n🔄 Processing batch {i//batch_size + 1} of {(len(leads_list) + batch_size - 1)//batch_size}")
        logging.info(f"Processing batch {i//batch_size + 1} of {(len(leads_list) + batch_size - 1)//batch_size}")
        batch_emails = []
        
        for lead in batch_leads:
            try:
                lead_name = lead.get('name', 'Unknown')
                lead_id = lead.get('lead_id', lead.get('id', ''))
                print(f"\n📝 Generating email for lead: {lead_name} (ID: {lead_id})")
                logging.info(f"Generating email for lead: {lead_name} (ID: {lead_id})")
                
                result = generate_email_for_single_lead(lead, product_details)
                subj = result.get('subject', '').strip()
                body = result.get('body', '').strip()
                
                if not subj or subj == '[No subject generated]' or not body or body == '[No body generated]':
                    print(f"❌ Failed to generate valid email for lead: {lead_name} (ID: {lead_id})")
                    print(f"   Subject: '{subj}'")
                    print(f"   Body: '{body[:100]}...'")
                    logging.error(f"Failed to generate valid email for lead: {lead_name} (ID: {lead_id})")
                    logging.error(f"Subject: '{subj}' | Body: '{body[:40]}...'")
                    failed_leads += 1
                    batch_emails.append({
                        'subject': '[No subject generated]',
                        'body': '[No body generated]',
                        'lead_id': str(lead_id)
                    })
                else:
                    print(f"✅ Successfully generated email for lead: {lead_name} (ID: {lead_id})")
                    print(f"   Subject: '{subj}'")
                    logging.info(f"Successfully generated email for lead: {lead_name} (ID: {lead_id})")
                    logging.info(f"Subject: '{subj}'")
                    successful_leads += 1
                    batch_emails.append(result)
            except Exception as e:
                lead_name = lead.get('name', 'Unknown')
                lead_id = lead.get('lead_id', lead.get('id', ''))
                print(f"❌ Error processing lead {lead_name} (ID: {lead_id}): {str(e)}")
                logging.error(f"Error processing lead {lead_name} (ID: {lead_id}): {str(e)}")
                failed_leads += 1
                batch_emails.append({
                    'subject': 'Error generating email',
                    'body': f'Error generating personalized email: {str(e)}',
                    'lead_id': str(lead_id)
                })
        
        all_emails.extend(batch_emails)
        if i + batch_size < len(leads_list):
            print("\n⏳ Waiting 2 seconds before processing next batch...")
            logging.info("Waiting 2 seconds before processing next batch...")
            time.sleep(2)
    
    print(f"\n📊 Email generation completed:")
    print(f"   ✅ Successful: {successful_leads}")
    print(f"   ❌ Failed: {failed_leads}")
    print(f"   📝 Total: {len(leads_list)}")
    logging.info(f"Email generation completed. Success: {successful_leads}, Failed: {failed_leads}, Total: {len(leads_list)}")
    return all_emails

async def process_lead_email_generation(lead, product_details):
    """Process email generation for a single lead (async)."""
    try:
        return generate_email_for_single_lead(lead, product_details)
    except Exception as e:
        logging.error(f"Error processing lead {lead.get('name', 'Unknown')}: {str(e)}")
        return {
            'subject': 'Error generating email',
            'body': f'Error generating personalized email: {str(e)}',
            'lead_id': str(lead.get('lead_id'))
        }

def generate_emails_for_leads(leads_data, pipeline, product_details):
    """
    Generate emails for multiple leads using the email generation pipeline.
    
    Args:
        leads_data (List[dict]): List of lead data dictionaries
        pipeline (EmailGenerationPipeline): Instance of email generation pipeline
        product_details (dict): Product details for email generation
        
    Returns:
        List[dict]: List of generated emails
    """
    try:
        # Format leads data and prepare payloads
        payloads = []
        for lead in leads_data:
            payload = {
                "lead": lead,
                "product_details": product_details,
            }
            payloads.append(payload)
        
        # Run the pipeline asynchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results = loop.run_until_complete(pipeline.process_all_leads(payloads))
        finally:
            loop.close()
        
        return results if results else []
        
    except Exception as e:
        logging.error(f"Error generating emails: {str(e)}")
        return []

# --- Follow-up Email Prompts for Each Interval ---
FOLLOWUP_PROMPTS = {
    0: '''# Gemini prompt for initial email (0th day)
Generate a personalized initial outreach email for the following lead:

Lead Details:
{{lead_details}}

Product Details:
{{product_details}}

Follow this style guide for the subject:
{subject_style}

Follow this style guide for the body:
{body_style}

Important:
1. DO NOT include any lead IDs, reference numbers, or technical identifiers in the email.
2. End the email body with "Best Regards," on a new line, followed by a blank line.
3. DO NOT include any sender name in the email body.
4. Always use "{product_name}" instead of [PRODUCT_NAME] when referring to the product.
5. The email will be sent to: {recipient_name} <{recipient_email}>

Return ONLY the email subject and body in this exact JSON format:
{
    "subject": "The subject line",
    "body": "The email body ending with 'Best Regards,' on a new line"
}
''',
    3: '''# Gemini prompt for Day 3 follow-up
Generate a personalized follow-up email for the following lead who has not responded to the initial outreach sent 3 days ago.

Lead Details:
{{lead_details}}

Product Details:
{{product_details}}

Instructions:
- Reference the previous email briefly, but do NOT repeat the original content.
- Politely remind the lead of the value or benefit of {product_name} for their specific context.
- Add a new, relevant insight, use case, or benefit that was not mentioned in the initial email.
- Maintain a direct, professional, and concise tone—avoid unnecessary pleasantries or repetition.
- Personalize the email based on the lead's profile or recent activity if possible.
- End with a clear, simple CTA (e.g., "Would you be open to a quick call this week?").
- Do NOT mention the lack of response directly or sound pushy.
- End the email body with "Best Regards," on a new line, followed by a blank line. Do NOT include the sender's name.

Return ONLY the email subject and body in this exact JSON format:
{
    "subject": "The subject line",
    "body": "The email body ending with 'Best Regards,' on a new line"
}
''',
    8: '''# Gemini prompt for 8th day follow-up
Generate a personalized second follow-up email for the following lead who has not responded to previous emails (initial and 3-day follow-up).

Lead Details:
{{lead_details}}

Product Details:
{{product_details}}

Instructions:
- Reference your previous attempts to connect, but do NOT sound desperate or repeat earlier content.
- Share a new, compelling benefit, case study, or testimonial relevant to the lead's industry or role.
- Emphasize how {product_name} can address a specific pain point or opportunity for the lead.
- Keep the tone professional, direct, and value-focused.
- Personalize the message with any new information or context about the lead or their company.
- End with a gentle, actionable CTA (e.g., "Let me know if you'd like more details or a quick demo.").
- Do NOT mention the lack of response directly or use guilt-tripping language.
- End the email body with "Best Regards," on a new line, followed by a blank line. Do NOT include the sender's name.

Return ONLY the email subject and body in this exact JSON format:
{
    "subject": "The subject line",
    "body": "The email body ending with 'Best Regards,' on a new line"
}
''',
    17: '''# Gemini prompt for 17th day follow-up
Generate a personalized third follow-up email for the following lead who has not responded to previous outreach attempts (initial, 3-day, and 8-day follow-ups).

Lead Details:
{{lead_details}}

Product Details:
{{product_details}}

Instructions:
- Briefly acknowledge your previous emails without repeating their content.
- Offer a new perspective, recent update, or industry trend that makes {product_name} especially relevant now.
- Highlight a unique feature or benefit of {product_name} that has not been mentioned before.
- Keep the message concise, professional, and strictly value-driven.
- Personalize the email with any new insights about the lead or their business.
- End with a low-friction CTA (e.g., "Would you be open to a short call to discuss if this is relevant for you?").
- Do NOT mention the lack of response directly or use negative language.
- End the email body with "Best Regards," on a new line, followed by a blank line. Do NOT include the sender's name.

Return ONLY the email subject and body in this exact JSON format:
{
    "subject": "The subject line",
    "body": "The email body ending with 'Best Regards,' on a new line"
}
''',
    24: '''# Gemini prompt for 24th day follow-up
Generate a personalized fourth follow-up email for the following lead who has not responded to any previous outreach (initial, 3-day, 8-day, and 17-day follow-ups).

Lead Details:
{{lead_details}}

Product Details:
{{product_details}}

Instructions:
- Reference your previous attempts to connect, but keep it brief and professional.
- Share a new, relevant success story, testimonial, or recent achievement of {product_name} that could resonate with the lead.
- Emphasize the potential missed opportunity or value for the lead's business, but do NOT use guilt or pressure.
- Keep the tone direct, respectful, and focused on the lead's needs.
- Personalize the message with any new context or developments.
- End with a clear, non-intrusive CTA (e.g., "If now isn't the right time, just let me know—happy to reconnect later.").
- End the email body with "Best Regards," on a new line, followed by a blank line. Do NOT include the sender's name.

Return ONLY the email subject and body in this exact JSON format:
{
    "subject": "The subject line",
    "body": "The email body ending with 'Best Regards,' on a new line"
}
''',
    30: '''# Gemini prompt for 30th day follow-up
Generate a final personalized follow-up email for the following lead who has not responded to any previous outreach (initial, 3-day, 8-day, 17-day, and 24-day follow-ups).

Lead Details:
{{lead_details}}

Product Details:
{{product_details}}

Instructions:
- Politely acknowledge your previous outreach and that this will be your last follow-up unless you hear back.
- Summarize the key value or unique benefit of {product_name} for the lead's business in one or two sentences.
- Offer to provide more information, answer questions, or reconnect in the future if their priorities change.
- Keep the tone professional, respectful, and leave the door open for future engagement.
- Personalize the message with any final relevant insight or context.
- End with a courteous, open-ended CTA (e.g., "If you'd like to revisit this in the future, just reply to this email.").
- End the email body with "Best Regards," on a new line, followed by a blank line. Do NOT include the sender's name.

Return ONLY the email subject and body in this exact JSON format:
{
    "subject": "The subject line",
    "body": "The email body ending with 'Best Regards,' on a new line"
}
''',
}

def main():
    """
    Main function placeholder. No mock data or test calls.
    """
    pass

if __name__ == "__main__":
    main()

def get_product_details(product_name):
    # Convert product name to lowercase for case-insensitive matching
    product_name = product_name.lower()
    try:
        for key, value in product_database.items():
            if key.lower() == product_name:
                return value
    except Exception as e:
        # If running in Streamlit context, show error, else just print
        try:
            import streamlit as st
            st.error(f"Error getting product details: {str(e)}")
        except ImportError:
            print(f"Error getting product details: {str(e)}")
        return None
    return None

def generate_email_for_single_lead_with_custom_prompt(lead_details: dict, product_details: str, custom_prompt: str, product_name: str = None) -> dict:
    """
    Generate a personalized email for a single lead using a custom prompt (for follow-ups).
    """
    import google.generativeai as genai
    import json, re, logging
    try:
        # Use explicit product_name if provided, else extract from product_details
        if product_name is None:
            for key in product_database.keys():
                if key.lower() in product_details.lower():
                    product_name = key
                    break
            if not product_name:
                for line in product_details.split('\n'):
                    if any(key.lower() in line.lower() for key in product_database.keys()):
                        for key in product_database.keys():
                            if key.lower() in line.lower():
                                product_name = key
                                break
                        if product_name:
                            break
            if not product_name:
                product_name = "our product"  # Fallback if no product name found

        recipient_name = lead_details.get('name', 'No recipient')
        recipient_email = lead_details.get('email', 'No email provided')

        # --- FIX: Inject subject_style and body_style if needed ---
        # If the prompt expects {subject_style} or {body_style}, inject them
        prompt = custom_prompt
        if '{subject_style}' in prompt or '{body_style}' in prompt:
            from personalised_email import subject_style, body_style
            prompt = prompt.format(
                lead_details=json.dumps({k: v for k, v in lead_details.items() if k != 'id'}, indent=2),
                product_details=product_details,
                product_name=product_name,
                recipient_name=recipient_name,
                recipient_email=recipient_email,
                subject_style=subject_style,
                body_style=body_style
            )
        else:
            prompt = prompt.format(
                lead_details=json.dumps({k: v for k, v in lead_details.items() if k != 'id'}, indent=2),
                product_details=product_details,
                product_name=product_name,
                recipient_name=recipient_name,
                recipient_email=recipient_email
            )

        # Get response from Gemini
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=5000,
            )
        )
        # Parse the response
        try:
            response_text = response.text
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                response_json = json.loads(json_match.group())
                body = response_json.get("body", "")
                body = body.replace("[PRODUCT_NAME]", product_name)
                if not body.endswith('\n\n'):
                    body = body.rstrip() + '\n\n'
                return {
                    "subject": response_json.get("subject", ""),
                    "body": body,
                    "lead_id": lead_details.get("id", ""),
                    "recipient": recipient_name,
                    "recipient_email": recipient_email
                }
            else:
                raise ValueError("No JSON found in response")
        except Exception as e:
            logging.error(f"Error parsing response: {str(e)}")
            return {
                "subject": "Error generating email",
                "body": f"An error occurred while generating the email: {str(e)}\n\n",
                "lead_id": lead_details.get("id", ""),
                "recipient": recipient_name,
                "recipient_email": recipient_email
            }
    except Exception as e:
        logging.error(f"Error generating email: {str(e)}")
        return {
            "subject": "Error generating email",
            "body": f"An error occurred while generating the email: {str(e)}\n\n",
            "lead_id": lead_details.get("id", ""),
            "recipient": lead_details.get('name', ''),
            "recipient_email": lead_details.get('email', '')
        }


