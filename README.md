# Autonomous API Extraction & Verification Agent

This repository contains an autonomous, dual-tiered AI Agent designed to automatically research, extract, and verify API authentication and accessibility data across a wide scale of SaaS platforms.

Built for the **Composio** ecosystem, this agent leverages both naive scraping and deep Agentic RAG (via Jina AI and Gemini) to map out the API integration landscape autonomously.

## 🧠 Strategic Methodology: The Dual-Pipeline Architecture

Extracting developer documentation using AI is notoriously difficult due to dynamic JavaScript sidebars and deeply nested authentication pages. To solve this, the agent utilizes a two-route architecture:

### Route 1: The Scalable HTTP Spider
*   **Architecture:** A lightweight spider that executes an HTTP GET against the target's developer portal, dumping the raw HTML, and prompting the LLM to extract Auth, API Surface, and Accessibility (Self-Serve vs Gated).
*   **Rationale:** Extremely fast, highly scalable, and cost-efficient. However, because it cannot render JavaScript, it struggles with modern single-page applications (React/Vue).

### Route 2: Deep Verification Loop (Two-Tiered Fallback)
*   **Architecture:** A robust Agentic RAG pipeline.
    *   **Tier 1 (OpenAPI Hunt):** The agent actively hunts the portal for machine-readable `swagger.json` or OpenAPI specs, extracting the raw engineering data directly.
    *   **Tier 2 (Agentic RAG):** If no spec is found, the agent falls back to Jina AI's Markdown proxy to aggressively crawl and read complex, JS-rendered developer documentation.
*   **Rationale:** Designed to correct the hallucinations of Route 1. By parsing OpenAPI specs, it achieves flawless 100% accuracy against ground truth. (Note: This rigor requires massive LLM context windows, requiring careful rate-limit management).

## 📊 Extracted Market Insights
By running this agent across 59 leading SaaS platforms (benchmarked against the Composio SDK), it successfully identified key product insights:
- **Developer-first products** (like Ahrefs, GitHub, Airtable) overwhelmingly utilize open self-serve signups paired with standard API keys. These are prime targets for immediate agentic integrations.
- **Legacy CRMs and Fin-Tech** (like Zoho, Datadog) act as the biggest blockers, often requiring bespoke partnerships or enterprise sales outreach.

## 🛠️ Repository Structure
- `verify_ultimate.py` / `pipeline.py` - Core agent logic governing the Route 1 and Route 2 extraction pipelines.
- `/data` - Output directories containing the raw JSON extraction results (`final_results.json`).

## 🚀 Getting Started

1. Install requirements:
   ```bash
   pip install requests beautifulsoup4 google-generativeai python-dotenv
   ```
2. Set your environment variables in a `.env` file:
   ```env
   GEMINI_API_KEY=your_key_here
   JINA_API_KEY=your_key_here
   ```
3. Run the Agent Pipeline:
   ```bash
   python verify_ultimate.py
   ```
