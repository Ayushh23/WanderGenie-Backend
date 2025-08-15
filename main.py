# main.py
import os
import json
import logging
import re
import urllib.parse
from typing import List, Optional, Any, Dict
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pymongo import MongoClient
from bson import ObjectId
from google import genai
from dotenv import load_dotenv
from google.genai import types
import uvicorn
import textwrap

# -------------------------
# Basic config / logging
# -------------------------
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wandergenie-backend")
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY is missing from environment variables or .env file.")

client = genai.Client(api_key=api_key)
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
PROMPTS_COLLECTION = os.getenv("PROMPTS_COLLECTION")

# MongoDB init
mongo = MongoClient(MONGO_URI)
db = mongo[DB_NAME]
prompts_col = db[PROMPTS_COLLECTION]

# -------------------------
# App + CORS
# -------------------------
app = FastAPI(title="WanderGenie - AI Itinerary Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# Pydantic models
# -------------------------
class ItineraryRequest(BaseModel):
    from_location: str
    specific_places: Optional[str] = ""
    categories: Optional[List[str]] = Field(default_factory=list)
    days: int = 5
    currency: str = "INR"
    budget: Optional[str] = ""
    intent: Optional[List[str]] = Field(default_factory=list)
    group: Optional[str] = ""
    stay: Optional[str] = ""
    notes: Optional[str] = ""

class Activity(BaseModel):
    time: Optional[str] = ""
    title: str
    description: str
    duration: Optional[str] = ""
    cost_estimate: Optional[str] = ""
    bookings: Optional[List[str]] = Field(default_factory=list)
    map_link: Optional[str] = ""  # New field for Google Maps links

class DayPlan(BaseModel):
    day: int
    date: Optional[str] = ""
    title: Optional[str] = ""
    summary: Optional[str] = ""
    activities: List[Activity] = Field(default_factory=list)
    accommodation: Optional[str] = ""
    travel_notes: Optional[str] = ""
    rough_cost: Optional[str] = ""

class ItineraryResponse(BaseModel):
    days: List[DayPlan]

# -------------------------
# Helper utilities
# -------------------------
def get_prompt_parts() -> List[Dict[str, Any]]:
    """Return prompt parts sorted by part_id ascending."""
    parts = list(prompts_col.find({}, {"_id": 0}).sort("part_id", 1))
    return parts

def build_location_fallback(specific_places: str, categories: List[str]) -> str:
    """If specific_places provided use it; otherwise join categories into a readable string."""
    sp = (specific_places or "").strip()
    if sp:
        return sp
    if categories:
        if isinstance(categories, list):
            return ", ".join(categories)
        return str(categories)
    return ""

def generate_google_maps_link(place_name: str) -> str:
    """Generate a Google Maps search link from a place name."""
    encoded_name = urllib.parse.quote_plus(place_name)
    return f"https://www.google.com/maps/search/?api=1&query={encoded_name}"

def build_master_prompt(user: ItineraryRequest) -> str:
    """Fetch prompt parts from DB, replace placeholders, merge into a single master prompt."""
    parts = get_prompt_parts()
    if not parts:
        raise RuntimeError("No prompt parts found in DB. Seed the 4 prompt parts first.")

    location_input = build_location_fallback(user.specific_places, user.categories)

    replacements = {
        "from_location": user.from_location,
        "specific_location": location_input,
        "categories": ", ".join(user.categories) if user.categories else "",
        "days": str(user.days),
        "currency": user.currency,
        "budget": str(user.budget),
        "intent": ", ".join(user.intent) if user.intent else "",
        "group": user.group or "",
        "stay": user.stay or "",
        "notes": user.notes or "",
        "trip_type": user.intent[0] if user.intent else "general",
    }

    merged_texts = []
    for p in parts:
        txt = p.get("text", "")
        try:
            txt = txt.format(**replacements)
        except Exception as e:
            logger.warning("Prompt formatting warning for part %s: %s", p.get("part_id"), str(e))
            for k, v in replacements.items():
                txt = txt.replace("{" + k + "}", v)
        merged_texts.append(txt.strip())

    master_prompt = "\n\n".join(merged_texts)
    return master_prompt

def extract_json_from_model_output(raw: str) -> str:
    """Cleans code fences and leading text, returns JSON string starting at first brace."""
    if not raw:
        return ""
    
    cleaned = raw.strip()
    
    # Remove common code fences and markdown
    for marker in ["```json", "```"]:
        if cleaned.startswith(marker):
            cleaned = cleaned[len(marker):].strip()
        if cleaned.endswith(marker):
            cleaned = cleaned[:-len(marker)].strip()
    
    # Find first { or [
    start_idx = max(cleaned.find('{'), cleaned.find('['))
    if start_idx == -1:
        return cleaned
    
    # Try to find matching closing brace/bracket
    stack = []
    end_idx = -1
    for i, c in enumerate(cleaned[start_idx:]):
        if c in '{[':
            stack.append(c)
        elif c in '}]':
            if stack:
                stack.pop()
                if not stack:
                    end_idx = start_idx + i
                    break
    
    if end_idx != -1:
        return cleaned[start_idx:end_idx+1]
    return cleaned[start_idx:]

def fix_json(json_str: str) -> str:
    """Attempt to fix common JSON formatting issues."""
    # Add quotes around unquoted keys
    fixed = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*:)', 
                   lambda m: f'{m.group(1)}"{m.group(2)}"{m.group(3)}', 
                   json_str)
    # Remove trailing commas
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
    return fixed

# -------------------------
# Seed route (admin)
# -------------------------
@app.post("/api/prompts/seed")
async def seed_prompts():
    """Seed the 4 modular prompts used by the app."""
    seed_parts = [
        {
            "part_id": 1,
            "title": "Core Itinerary Generator",
            "text": (
                "You are an elite luxury travel concierge. "
                "Design a detailed {days}-day travel itinerary starting from {from_location}. "
                "For each activity, include a Google Maps link (format: https://www.google.com/maps/search/?api=1&query=<place_name>). "
                "Focus on {trip_type} travel with local insider knowledge. "
                "Include authentic cultural insights and time-of-day recommendations."
            ),
        },
        {
            "part_id": 2,
            "title": "Experience Enhancer",
            "text": (
                "Refine the itinerary with insider secrets and luxury-level detail. "
                "Include Google Maps links for all locations. "
                "Add sensory details and balance must-see highlights with local encounters."
            ),
        },
        {
            "part_id": 3,
            "title": "Local Insights & Tips",
            "text": (
                "Write a 'Local's Secrets' section with cultural etiquette and safety tips. "
                "Include Google Maps links for recommended places."
            ),
        },
        {
            "part_id": 4,
            "title": "SEO & Engagement Optimizer",
            "text": (
                "Rewrite the itinerary with SEO-friendly headings and compelling intros. "
                "Ensure all locations have Google Maps links."
            ),
        },
    ]

    for part in seed_parts:
        prompts_col.update_one(
            {"part_id": part["part_id"]},
            {"$set": part},
            upsert=True
        )

    return {"ok": True, "message": "Seeded prompts (4 parts) successfully."}

# -------------------------
# Admin/Prompt CRUD routes
# -------------------------
@app.get("/api/prompts")
async def list_prompts():
    parts = get_prompt_parts()
    return {"prompts": parts}

@app.post("/api/prompts")
async def upsert_prompt(part: Dict[str, Any] = Body(...)):
    """Upsert a prompt part."""
    if "part_id" not in part or "text" not in part:
        raise HTTPException(status_code=400, detail="part_id and text are required")
    prompts_col.update_one({"part_id": part["part_id"]}, {"$set": part}, upsert=True)
    return {"ok": True}

@app.delete("/api/prompts/{part_id}")
async def delete_prompt(part_id: int):
    res = prompts_col.delete_one({"part_id": part_id})
    return {"deleted_count": res.deleted_count}

# -------------------------
# Generate itinerary endpoint
# -------------------------
@app.post("/api/generate-itinerary", response_model=ItineraryResponse)
async def generate_itinerary(payload: ItineraryRequest):
    """Main endpoint used by frontend to generate itineraries."""
    try:
        # Build master prompt with placeholder replacements
        master_prompt = build_master_prompt(payload)

        # Enhanced JSON schema instruction with strict formatting
        schema_instruction = textwrap.dedent(f"""\
            IMPORTANT: You MUST return ONLY valid JSON in this EXACT format. 
            Include Google Maps links for all locations (format: https://www.google.com/maps/search/?api=1&query=<place_name>).
            
            {{
              "days": [
                {{
                  "day": 1,
                  "date": "",
                  "title": "",
                  "summary": "",
                  "activities": [
                    {{
                      "time": "",
                      "title": "",
                      "description": "",
                      "duration": "",
                      "cost_estimate": "",
                      "bookings": [],
                      "map_link": "https://www.google.com/maps/search/?api=1&query=Place+Name"
                    }}
                  ],
                  "accommodation": "",
                  "travel_notes": "",
                  "rough_cost": ""
                }}
              ]
            }}
            """)
                    
        final_prompt = master_prompt + "\n\n" + schema_instruction
        logger.info("Sending prompt to Gemini (truncated): %s", final_prompt[:800].replace("\n"," "))

        # Call Gemini with simpler configuration
        try:
            response = client.models.generate_content(
                model="gemini-1.5-flash",
                contents=[final_prompt],
                
            )
        except Exception as e:
            logger.error("Gemini API call failed: %s", str(e))
            raise HTTPException(
                status_code=500,
                detail="Failed to communicate with the AI service. Please try again later."
            )

        # Extract text with more robust handling
        raw = ""
        try:
            raw = getattr(response, "text", "")
            if not raw:
                if hasattr(response, 'candidates') and response.candidates:
                    raw = response.candidates[0].content.parts[0].text
        except Exception as e:
            logger.warning("Error extracting text from response: %s", str(e))
            raw = str(response)

        logger.info("Raw Gemini output: %r", raw)

        # Enhanced JSON extraction
        json_text = ""
        try:
            json_text = extract_json_from_model_output(raw)
            
            if not json_text.strip().startswith('{'):
                json_match = re.search(r'\{.*\}', raw, re.DOTALL)
                if json_match:
                    json_text = json_match.group(0)
                
            if not json_text.strip().startswith('{'):
                days_match = re.search(r'(\[\s*\{.*\}\s*\])', raw, re.DOTALL)
                if days_match:
                    json_text = f'{{"days": {days_match.group(1)}}}'

            logger.info("Extracted JSON text: %r", json_text)

            # Parse JSON with automatic fixing
            try:
                data = json.loads(json_text)
            except json.JSONDecodeError:
                fixed_json = fix_json(json_text)
                data = json.loads(fixed_json)

            # Validate the response structure
            if "days" not in data:
                if isinstance(data, list):
                    data = {"days": data}
                else:
                    raise ValueError("Response missing 'days' array")

            if not isinstance(data["days"], list):
                raise ValueError("'days' should be an array")

            # Ensure each activity has a map link
            for day in data["days"]:
                if "activities" not in day:
                    day["activities"] = []
                if "day" not in day:
                    raise ValueError("Each day must have a 'day' number")
                
                for activity in day["activities"]:
                    if "map_link" not in activity or not activity["map_link"]:
                        # Generate map link from title if not provided
                        activity["map_link"] = generate_google_maps_link(activity["title"])
                    elif not activity["map_link"].startswith("https://www.google.com/maps/"):
                        # Ensure valid Google Maps link format
                        activity["map_link"] = generate_google_maps_link(activity["title"])

            return data

        except Exception as e:
            logger.error("Failed to parse response: %s", str(e))
            logger.error("Original response was: %s", raw)
            raise HTTPException(
                status_code=500,
                detail="We couldn't process the AI response. Please try again with different parameters."
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error during itinerary generation")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again later."
        )

# -------------------------
# Simple health check
# -------------------------
@app.get("/health")
async def health():
    return {"status": "ok"}

# -------------------------
# Run the app
# -------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
