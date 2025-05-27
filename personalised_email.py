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
            # Extract JSON from the response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                response_json = json.loads(json_match.group())
                body = response_json.get("body", "")
                
                # Replace any remaining [PRODUCT_NAME] with actual product name
                body = body.replace("[PRODUCT_NAME]", product_name)
                
                # Ensure proper signature formatting
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
            "recipient": recipient_name,
            "recipient_email": recipient_email
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
        raise ValueError("No leads provided in the list")
    
    all_emails = []
    
    # Process in batches of 5 leads
    batch_size = 5
    for i in range(0, len(leads_list), batch_size):
        batch_leads = leads_list[i:i + batch_size]
        
        # Process each lead in the batch
        batch_emails = []
        for lead in batch_leads:
            try:
                # Generate email for this lead
                result = generate_email_for_single_lead(lead, product_details)
                batch_emails.append(result)
            except Exception as e:
                print(f"Error processing lead {lead.get('name', 'Unknown')}: {str(e)}")
                batch_emails.append({
                    'subject': 'Error generating email',
                    'body': f'Error generating personalized email: {str(e)}',
                    'lead_id': str(lead.get('lead_id'))
                })
        
        # Add the batch results to our main list
        all_emails.extend(batch_emails)
        
        # Add delay between batches to avoid rate limits
        if i + batch_size < len(leads_list):
            time.sleep(2)
    
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

def main():
    """
    Main function to test personalized email generation with sample data
    """
#     # Sample product details
    product_details = """
InvestorBase is an AI-powered platform designed to revolutionize deal flow management for venture capitalists (VCs). It automates the evaluation of pitch decks, enabling VCs to identify high-potential opportunities efficiently, reducing manual workloads, and minimizing missed prospects. The platform streamlines investment decision-making through AI-driven analysis, real-time market validation, and customizable deal scoring models.
Key Features & Capabilities
Comprehensive Pitch Deck Analysis
Executive Summary Assessment: Evaluates the clarity of value proposition and business model.
Market Size Validation: Cross-references TAM/SAM/SOM claims with industry databases.
Financial Model Scrutiny: Flags unrealistic growth projections and validates unit economics.
Competitive Landscape Analysis: Maps startup positioning against established players.
Team Background Verification: Assesses founder experience relevance to venture success.
Advanced Market Validation
Industry Growth Trends: Overlays startup trajectory against sector forecasts.
Regulatory Impact Assessment: Identifies compliance challenges in regulated industries.
Geographic Expansion Feasibility: Evaluates market entry barriers for scaling plans.
Technology Adoption Curves: Compares innovation timing with market readiness.
Customer Acquisition Cost Benchmarking: Compares CAC/LTV ratios with industry standards.
Customized Deal Prioritization
Investment Thesis Alignment: Scores opportunities against firm-specific criteria.
Portfolio Fit Analysis: Identifies synergies with existing investments.
Stage-Specific Metrics: Adapts evaluation criteria based on startup maturity.
Risk-Adjusted Return Potential: Weighs opportunities by both upside and risk factors.
Follow-on Investment Planning: Highlights portfolio companies ready for additional funding.

Use Cases
Efficiency Gains for Venture Capitalists
Reduces initial screening time by 70-80% through automated analysis.
Increases deal throughput capacity by 3-5x without adding staff.
Enables analysts to focus on high-value activities (founder interactions, due diligence) instead of basic screening.
Cuts meeting time spent discussing marginal deals by 40-50%.
Enhanced Market Intelligence
Automates research on industry trends, competition, and regulatory factors.
Provides real-time validation of startup claims, reducing reliance on manual verification.
Enhances decision-making with dynamic scoring models that adapt to market conditions.
Strategic Investment Decision Support
Identifies promising outliers that traditional screening might miss.
Improves portfolio diversification through objective opportunity assessment.
Enhances decision consistency across investment team members.
Increases deal flow quality through better founder targeting and feedback.

    """

    # Sample lead details
    sample_lead = {
        'name': 'Rohit Jain',
        'lead_id': 1010101,
        'experience': """CoinDCX
Angel portfolio:
ASQI (secured lending platform on blockchain; securitized by tokenized traditional financial assets like stocks, bonds) Ava Labs (blockchain/smartcontract platform) RIA (digital insurer in India) TheList (global luxury ecommerce) Canvas (HR Tech focused on diversity hires)
Advisor/Mentor:
CV Labs (global blockchain accelerator)
BuildersTribe (India blockchain accelerator)
100x.vc
TheThirdPillar (Upwork on Blockchain)
Goals101 (FIntech - API based solutions for banks)
Fundamentum is a $100M growth stage fund, founded by Nandan Nilekani and Sanjeev Aggarwal.

Portfolio: Travel Triangle PharmEasy Spinny Fareye
Helping and mentoring tech entrepreneurs with fund-raising, strategy and product development. Evaluating opportunities esp in the B2B e-commerce space.

Launched Buyoco - a B2B Crossborder E-Commerce platform that helps retailers in India (to begin with) import from manufacturers in China and Bangladesh (to begin with) and give them an end-to-end fulfilment experience.'""",
        'Education': """Education
Harvard Business School
MBA
2004 - 2006
Indian Institute of Technology, Guwahati    
Bachelor of Technology (BTech), Computer Science
1997 - 2001
Activities and societies: Cultural Secretary (Gymkhana Council), Organizer Alcheringa (annual Cultural festival), Co-organizer Techniche (annual Technical festival), Captain - Soccer Team, Member - Table Tennis and Athletics teams; Organizer Dramatics Club and other clubs on-campus.
Show all 3 educations""",
        'company': 'CoinDCX',
        'company_overview': """Established in 2018, CoinDCX is the preferred crypto exchange in India, but also an instrumental player in building the broader Web3 ecosystem. 

Trusted by over 1.4 crore registered users. Our mission is simple: to provide easy access to Web3 experiences and democratize investments in virtual digital assets. We prioritize user safety and security, strictly adhering to KYC and AML guidelines. 

In our commitment to quality, we employ a stringent 7M Framework for the listing of crypto projects, ensuring users access only the safest virtual digital assets. CoinDCX has partnered with Okto for India to launch a secure multi-chain DeFi app that offers a keyless, self-custody wallet . It aims to simplify the world of decentralized finance (DeFi) by providing a secure, user-friendly, and innovative solution for managing virtual digital assets. 

Through CoinDCX Ventures, we've invested in over 15 innovative Web3 projects, reinforcing our dedication to the Web3 ecosystem. Our flagship educational initiative, #NamasteWeb3, empowers Indians with web3 knowledge, preparing them for the future of virtual digital assets. CoinDCX's vision and potential have gained the confidence of global investors, including Pantera, Steadview Capital, Kingsway, Polychain Capital, B Capital Group, Bain Capital Ventures, Cadenza, Draper Dragon, Republic, Kindred, and Coinbase Ventures. 

At CoinDCX, we're leading India towards the decentralized future of Web3 with an unwavering commitment to safety, simplicity, and education.""",
        'Company industry': 'Financial Services'
    }

    

    single_email = generate_email_for_single_lead(sample_lead, product_details)
    print(single_email)
    print(type(single_email))

    outlook_auth_url = get_outlook_auth_url()
    st.markdown(f'<a href="{outlook_auth_url}" target="_blank"><b>Sign in with Outlook</b></a>', unsafe_allow_html=True)

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


