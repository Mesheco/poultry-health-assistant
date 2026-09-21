# 🐔 AI Poultry Health Diagnostic Assistant

An agentic AI assistant that helps smallholder poultry farmers identify likely causes of illness in their birds and know what to do next — built for farmers who may not have easy or affordable access to a veterinarian.

## How it works

Rather than answering a question once, this assistant follows a genuine multi-step reasoning process:

1. **Assess** — checks if it has enough symptom detail; asks clarifying questions if not
2. **Retrieve** — searches a curated poultry disease knowledge base
3. **Diagnose** — ranks likely conditions by confidence
4. **Self-check** — flags ambiguous cases for a vet visit rather than guessing
5. **Plan** — generates a day-by-day action plan with escalation triggers

Every response includes a color-coded urgency indicator (Low/Medium/High) and a safety disclaimer. The assistant is hardened against being pressured into skipping its own safety process.

## Built with

- **Claude (Anthropic API)** — core reasoning and tool-calling engine
- **Streamlit** — web interface
- A lightweight, extensible JSON knowledge base covering common poultry diseases (Newcastle Disease, Coccidiosis, Fowl Typhoid, Gumboro, Fowl Pox, CRD, Infectious Coryza, and Heat Stress)

## Live demo

🔗 [Try it here](https://poultry-health-assistant-j8jkggtbt6ggdmatkk9a95.streamlit.app)

## Disclaimer

This tool is for informational purposes only and does not replace professional veterinary diagnosis. Always consult a licensed veterinarian or livestock officer, especially for urgent or high-mortality situations.

---

Built as a hackathon submission demonstrating a real-world, deployable use case for agentic AI in an underserved sector.
