import json

def load_kb():
    with open("poultry_disease_kb.json", "r") as f:
        return json.load(f)

def search_disease_kb(symptoms_text):
    """
    Takes a user's symptom description (plain text) and returns
    the diseases whose symptoms best match, ranked by overlap.
    """
    kb = load_kb()
    symptoms_text_lower = symptoms_text.lower()

    scored_results = []
    for disease in kb["diseases"]:
        score = 0
        for symptom in disease["symptoms"]:
            # crude keyword overlap check
            symptom_words = symptom.lower().split()
            for word in symptom_words:
                if len(word) > 3 and word in symptoms_text_lower:
                    score += 1
        if score > 0:
            scored_results.append((score, disease))

    # sort by score, highest first
    scored_results.sort(key=lambda x: x[0], reverse=True)

    return [disease for score, disease in scored_results[:3]]  # top 3 matches


# Quick test — only runs if you execute this file directly
if __name__ == "__main__":
    test_input = "my birds have greenish diarrhea and some have twisted necks"
    results = search_disease_kb(test_input)
    for r in results:
        print(f"- {r['name']} (urgency: {r['urgency']})")