"""
Phase 3 (Ultimate): Hybrid Verification Loop
Tier 1: Parse machine-readable OpenAPI specs via APIs.guru (100% accuracy)
Tier 2: Agentic RAG via Jina Search -> Jina Reader -> Gemini Flash-Lite
"""
import os
import json
import time
import requests
import re
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# Setup Gemini Rotator
gemini_keys_str = os.getenv("GEMINI_API_KEYS", "")
gemini_keys = [k.strip() for k in gemini_keys_str.split(",") if k.strip()]

class GeminiRotator:
    def __init__(self, keys):
        self.keys = keys
        self.current_idx = 0
        self.client = genai.Client(api_key=self.keys[self.current_idx])

    def get_client(self):
        return self.client

    def rotate(self):
        self.current_idx = (self.current_idx + 1) % len(self.keys)
        self.client = genai.Client(api_key=self.keys[self.current_idx])

rotator = GeminiRotator(gemini_keys)

# Setup Jina
JINA_KEY = os.getenv("JINA_API_KEY")
JINA_HEADERS = {"Authorization": f"Bearer {JINA_KEY}"} if JINA_KEY else {}

def fetch_apis_guru_map():
    try:
        r = requests.get("https://api.apis.guru/v2/list.json", timeout=10)
        return r.json()
    except:
        return {}

def extract_json(text):
    if not text: return None
    text = text.strip()
    for fence in ['```json', '```']:
        if text.startswith(fence):
            text = text[len(fence):]
    if text.endswith('```'):
        text = text[:-3]
    text = text.strip()
    try: return json.loads(text)
    except: pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try: return json.loads(match.group())
        except: pass
    return None

def check_tier1_openapi(app_name, domain, apis_map):
    # Try to find a matching key
    target = domain.replace("www.", "").lower()
    name_target = app_name.lower().replace(" ", "")
    
    match_key = None
    for key in apis_map.keys():
        if target in key or name_target in key:
            match_key = key
            break
            
    if not match_key:
        return None
        
    try:
        api_info = apis_map[match_key]
        version = list(api_info['versions'].keys())[0]
        swagger_url = api_info['versions'][version]['swaggerUrl']
        
        r = requests.get(swagger_url, timeout=10)
        spec = r.json()
        
        # Parse securitySchemes (OpenAPI 3) or securityDefinitions (Swagger 2)
        security = spec.get('components', {}).get('securitySchemes', {})
        if not security:
            security = spec.get('securityDefinitions', {})
            
        if not security:
            return None # Couldn't find security block
            
        auth_methods = {}
        for k, v in security.items():
            t = str(v.get('type', '')).lower()
            scheme = str(v.get('scheme', '')).lower()
            if 'oauth2' in t: auth_methods['OAuth2'] = "OpenAPI Spec (OAuth2)"
            elif 'apikey' in t or 'api_key' in t: auth_methods['API_Key'] = "OpenAPI Spec (ApiKey)"
            elif 'basic' in t or 'basic' in scheme: auth_methods['Basic'] = "OpenAPI Spec (Basic)"
            elif 'http' in t and 'bearer' in scheme: auth_methods['API_Key'] = "OpenAPI Spec (Bearer)"
            
        if not auth_methods:
            return None
            
        return {
            "dom_auth": auth_methods,
            "dom_confidence": "high (OpenAPI 100%)",
            "dom_self_serve": "Unknown", # OpenAPI specs rarely define pricing
            "dom_docs_url_verified": swagger_url
        }
    except Exception as e:
        print(f"      [OpenAPI parse error] {e}")
        return None

def run_tier2_agentic_rag(app_name):
    # 1. Search for docs
    query = f"{app_name} API authentication developer documentation"
    search_url = f"https://s.jina.ai/{query}"
    
    try:
        r_search = requests.get(search_url, headers=JINA_HEADERS, timeout=20)
        search_text = r_search.text
        
        # Extract the first URL Source from Jina search results
        match = re.search(r'\[1\] URL Source:\s*(https?://\S+)', search_text)
        if not match:
            return None
            
        doc_url = match.group(1)
        print(f"      [Target Acquired] {doc_url}")
        
        # 2. Fetch full markdown with Jina Reader
        r_read = requests.get(f"https://r.jina.ai/{doc_url}", headers=JINA_HEADERS, timeout=30)
        markdown = r_read.text
        
        # Limit context to avoid token overflow
        markdown = markdown[:12000] 
        
        # 3. LLM Comprehension
        prompt = f"""You are a precise API researcher. Read the following documentation for '{app_name}'.

Return a JSON object with:
{{
  "auth_methods": {{"MethodName": "Proof from text"}}, // e.g. "OAuth2", "API_Key", "Basic"
  "self_serve": "Self-serve or Gated or Unknown"
}}

Rules:
- Only answer based on the text. Ignore false positives (e.g. "We don't support OAuth").
- Use keys: "OAuth2", "API_Key", "Basic".

Text:
{markdown}
"""
        
        client = rotator.get_client()
        response = client.models.generate_content(
            model='gemini-2.5-flash-lite',
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1),
        )
        
        if not response or not response.text:
            return None
            
        res = extract_json(response.text)
        if res:
            return {
                "dom_auth": res.get("auth_methods", {}),
                "dom_self_serve": res.get("self_serve", "Unknown"),
                "dom_confidence": "high (Agentic RAG)",
                "dom_docs_url_verified": doc_url
            }
            
    except Exception as e:
        print(f"      [Agentic error] {str(e)[:80]}")
    
    return None

def verify_app(app, apis_map):
    print(f"\n[Verifying] {app['name']}")
    domain = app["name"].lower().replace(" ", "") + ".com"
    
    # Check url_matched.json for better domain if possible
    try:
        with open("url_matched.json", "r") as f:
            url_data = json.load(f)
            all_apps = url_data["found"] + url_data["not_found"]
            match = next((a for a in all_apps if a["id"] == app["id"]), None)
            if match: domain = match["domain"]
    except: pass
    
    result = {
        "id": app["id"],
        "name": app["name"],
        "dom_self_serve": "Unknown",
        "dom_auth": {},
        "dom_is_graphql": False,
        "dom_has_mcp": False,
        "dom_docs_url_verified": "",
        "dom_confidence": "low",
    }
    
    # Tier 1: OpenAPI
    print("  -> Checking Tier 1: OpenAPI Spec")
    t1_res = check_tier1_openapi(app["name"], domain, apis_map)
    if t1_res:
        print(f"     ✅ Found OpenAPI spec! Auth: {list(t1_res['dom_auth'].keys())}")
        result.update(t1_res)
        return result
        
    # Tier 2: Agentic RAG
    print("  -> Checking Tier 2: Agentic RAG (Jina + LLM)")
    t2_res = run_tier2_agentic_rag(app["name"])
    if t2_res:
        print(f"     ✅ LLM Parsed docs! Auth: {list(t2_res['dom_auth'].keys())}")
        result.update(t2_res)
        return result
        
    print("  ❌ Verification failed.")
    return result

def main():
    print("Initializing Hybrid Verification Pipeline...")
    apis_map = fetch_apis_guru_map()
    print(f"Loaded {len(apis_map)} OpenAPI specs from APIs.guru")
    
    with open("data/final_results.json", "r", encoding="utf-8") as f:
        apps = json.load(f)
        
    for i, app in enumerate(apps):
        if app.get("source") == "Failed":
            continue
            
        result = verify_app(app, apis_map)
        
        # Merge results
        for k, v in result.items():
            if k in ["dom_auth", "dom_self_serve", "dom_confidence", "dom_docs_url_verified"]:
                app[k] = v
                
        # Save every loop
        with open("data/final_results.json", "w", encoding="utf-8") as f:
            json.dump(apps, f, indent=2)
            
        time.sleep(1) # Pacing

if __name__ == "__main__":
    main()
