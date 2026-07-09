import os
import json
import time
from dotenv import load_dotenv
from composio import Composio
from google import genai
from google.genai import types

load_dotenv()
composio_key = os.getenv("COMPOSIO_API_KEY")
gemini_keys_str = os.getenv("GEMINI_API_KEYS", "")
gemini_keys = [k.strip() for k in gemini_keys_str.split(",") if k.strip()]

if not composio_key or not gemini_keys:
    print("Missing API keys in .env file.")
    exit(1)

print(f"Loaded {len(gemini_keys)} Gemini API keys.")
c = Composio(api_key=composio_key)

class GeminiRotator:
    def __init__(self, keys):
        self.keys = keys
        self.current_idx = 0
        self.client = genai.Client(api_key=self.keys[self.current_idx])
        
    def get_client(self):
        return self.client
        
    def rotate(self):
        self.current_idx = (self.current_idx + 1) % len(self.keys)
        print(f"⚠️ Rotating to Gemini Key {self.current_idx + 1}/{len(self.keys)}")
        self.client = genai.Client(api_key=self.keys[self.current_idx])

rotator = GeminiRotator(gemini_keys)

def research_with_gemini(app_name, domain):
    prompt = f"""
    You are an API Integration Engineer. Research the software application '{app_name}' (website: {domain}).
    Find the following information:
    1. Category and a one-liner description of what the app does.
    2. Auth methods (OAuth2, API Key, Basic, etc).
    3. Self-serve vs gated: Can a developer get credentials for free/trial, or does it require a paid plan/sales call/partner agreement?
    4. API surface: Is there a documented REST or GraphQL API? Does it have an existing Model Context Protocol (MCP) server?
    5. Buildability verdict: Could this be an agent toolkit today? What is the main blocker if not?
    6. Evidence URLs: Provide the exact URL to their API documentation or pricing page that proves the above.
    
    RETURN STRICT JSON ONLY. Use this format: {{"category_and_description": "...", "auth_methods": "...", "self_serve_vs_gated": "...", "api_surface": "...", "buildability_verdict": "...", "evidence_urls": "..."}}
    """
    
    for attempt in range(len(gemini_keys) * 2): # Try twice per key if needed
        try:
            client = rotator.get_client()
            response = client.models.generate_content(
                model='gemini-2.5-flash-lite',
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[{"google_search": {}}],
                    temperature=0.2,
                ),
            )
            text = response.text.strip()
            if text.startswith('```json'): text = text[7:]
            if text.startswith('```'): text = text[3:]
            if text.endswith('```'): text = text[:-3]
            return json.loads(text.strip())
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "Quota" in err_str or "exhausted" in err_str.lower():
                print(f"  [Rate Limit] {err_str[:100]}...")
                rotator.rotate()
                time.sleep(2)
            elif "503" in err_str:
                print("  [503 Overloaded] Sleeping...")
                time.sleep(5)
            else:
                print(f"  [Error] {err_str}")
                return None
    return None

def main():
    try:
        with open("url_matched.json", "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print("Error reading url_matched.json:", e)
        return

    composio_baseline = {}
    final_results = []
    
    print(f"\n--- Phase 1: Composio SDK Baseline ({len(data['found'])} apps) ---")
    for app in data["found"]:
        try:
            t = c.client.toolkits.retrieve(app['slug'])
            
            auth_modes = []
            if getattr(t, 'auth_config_details', None):
                auth_modes = [getattr(d, 'mode', '') for d in t.auth_config_details if getattr(d, 'mode', '')]
            
            managed = getattr(t, 'composio_managed_auth_schemes', []) or []
            self_serve = "Self-serve via Composio Managed Auth" if managed else "Bring your own credentials"
            
            cats = []
            if getattr(t, 'meta', None) and getattr(t.meta, 'categories', None):
                cats = [c_item.slug for c_item in t.meta.categories]
            has_mcp = "Yes (model-context-protocol)" if "model-context-protocol" in cats else "No"
            
            composio_baseline[app["name"]] = {
                "auth_methods": ", ".join(auth_modes) if auth_modes else "Unknown",
                "self_serve_vs_gated": self_serve,
                "api_surface": f"MCP: {has_mcp}"
            }
        except Exception as e:
            print(f"  -> Error fetching {app['name']}: {e}")
            composio_baseline[app["name"]] = None

    print(f"\n--- Phase 2: Gemini Web Research Verification Loop (All 100 Apps) ---")
    all_apps = data["found"] + data["not_found"]
    all_apps.sort(key=lambda x: x["id"])
    
    accuracy_metrics = {
        "total_verified": 0,
        "auth_matches": 0,
        "self_serve_matches": 0,
        "conflicts": []
    }
    
    for app in all_apps:
        print(f"[{app['id']}/100] Researching: {app['name']}")
        res = research_with_gemini(app["name"], app["domain"])
        
        source = "Gemini Web Research"
        if not res:
            res = {
                "category_and_description": "Failed to research",
                "auth_methods": "Unknown",
                "self_serve_vs_gated": "Unknown",
                "api_surface": "Unknown",
                "buildability_verdict": "Unknown",
                "evidence_urls": "Unknown"
            }
            source = "Failed"
            
        is_in_composio = app["name"] in composio_baseline
        
        final_results.append({
            "id": app["id"],
            "name": app["name"],
            "in_composio": is_in_composio,
            "source": source,
            "gemini_data": res,
            "composio_baseline": composio_baseline.get(app["name"])
        })
        
        # Phase 3: Conflict Comparison for Accuracy
        if is_in_composio and res and composio_baseline.get(app["name"]):
            accuracy_metrics["total_verified"] += 1
            cb = composio_baseline[app["name"]]
            
            # Auth comparison (loose text matching)
            gemini_auth = res.get("auth_methods", "").lower()
            comp_auth = cb["auth_methods"].lower()
            auth_match = any(word in gemini_auth for word in comp_auth.split(",")) or "oauth" in gemini_auth and "oauth" in comp_auth
            if auth_match:
                accuracy_metrics["auth_matches"] += 1
                
            # Self-serve comparison
            gemini_ss = res.get("self_serve_vs_gated", "").lower()
            ss_match = "free" in gemini_ss or "trial" in gemini_ss or "self-serve" in gemini_ss
            if ss_match:
                accuracy_metrics["self_serve_matches"] += 1
                
            if not auth_match or not ss_match:
                accuracy_metrics["conflicts"].append({
                    "app": app["name"],
                    "conflict_type": "Auth Mismatch" if not auth_match else "Self-serve Mismatch",
                    "composio_truth": cb,
                    "gemini_finding": res
                })
        
        time.sleep(1) # Pacing to protect quota
        
    with open("data/final_results.json", "w", encoding="utf-8") as f:
        json.dump(final_results, f, indent=2)
        
    with open("data/accuracy_metrics.json", "w", encoding="utf-8") as f:
        json.dump(accuracy_metrics, f, indent=2)
        
    print("\n✅ Saved data/final_results.json and data/accuracy_metrics.json")

if __name__ == "__main__":
    main()
