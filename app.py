import streamlit as st
import openai
import requests
import re

# ------------------------------
# Configuration
# ------------------------------
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
CLICKUP_API_TOKEN = st.secrets["CLICKUP_API_TOKEN"]

HEADERS = {
    "Authorization": CLICKUP_API_TOKEN,
    "Content-Type": "application/json"
}

CUSTOM_FIELDS = {
    "URL Template": "01223fc2-9af0-4be9-8d6e-e43adaeb9fd2",
    "Hypothesis": "279b9d0f-6a12-4823-b0d0-f3c20b005ac0",
    "Devices": "be3f2363-13d0-4636-badd-6158b7083d3c",
    "Primary Conversion Action": "bc225de6-f12d-4858-ad2c-ad2d9d4c4765",
    "Target Confidence": "54e841a3-a91c-49a0-9767-ab42afb25cfe",
    "Target Power": "3bdfec37-d250-4b6c-93e2-dee97933c405",
    "Key Idea Rank": "51e40c23-612f-4a94-ae0a-c467014a49f4",
    "Key Idea Cumulative Priority Score": "46e57c91-81b1-47c0-8b6c-cc379d51e57b"
}

DEVICES_MAPPING = {
    "DESKTOP": "4d2a0166-364d-4dae-a9cb-a27ebe9e7136",
    "MOBILE": "a9831f20-df77-4770-8bf5-581c032bc53f",
    "ALL": "5217daed-4e9c-4eaf-9e85-6030688a44a1"
}

def clean_hypothesis(hypothesis):
    patterns = [
        r"\. and thus increase the [^\.]+ rate\.",
        r"and thus increase the [^\.]+ rate\."
    ]
    for pattern in patterns:
        hypothesis = re.sub(pattern, ".", hypothesis)
    return hypothesis.strip()

def fetch_ideas_by_ids(task_ids):
    ideas = []
    for task_id in task_ids:
        url = f"https://api.clickup.com/api/v2/task/{task_id}"
        response = requests.get(url, headers=HEADERS)
        if response.status_code != 200:
            continue
        task = response.json()
        task_name = task.get('name', '')
        task_number = task_name.split('|')[0].strip() if '|' in task_name else task_id
        url_template = next(
            (field.get('value') for field in task.get('custom_fields', [])
             if field['id'] == CUSTOM_FIELDS['URL Template'] and 'value' in field),
            None
        )
        idea_rank_str = next(
            (field.get('value') for field in task.get('custom_fields', [])
             if field['id'] == CUSTOM_FIELDS['Key Idea Rank'] and 'value' in field),
            None
        )
        try:
            idea_rank = int(idea_rank_str) if idea_rank_str is not None else 0
        except ValueError:
            idea_rank = 0

        ideas.append({
            "ID": task_id,
            "Number": task_number,
            "Name": task_name,
            "URL Template": url_template,
            "IdeaRank": idea_rank
        })
    return ideas

def generate_ab_test_recipe(ideas, primary_conversion_action):
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    idea_descriptions = "\n".join(
        f"- ID: {idea['ID']} | Description: {idea['Name']}" for idea in ideas
    )

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an expert in creating A/B testing recipes..."},
            {"role": "user", "content": f"""
Combine the following A/B testing ideas into a cohesive A/B Test Recipe. 
{idea_descriptions}
... ending with the primary conversion action: '{primary_conversion_action}'.
"""}
        ]
    )
    return response.choices[0].message.content

def parse_recipe(recipe_text, idea_ids, url_template, ideas, primary_conversion_action):
    recipe = {}
    lines = recipe_text.split('\n')
    for line in lines:
        if '**Task Name:**' in line:
            recipe['Task Name'] = line.split('**Task Name:**')[1].strip()
        elif '**Primary Conversion Action:**' in line:
            recipe['Primary Conversion Action'] = primary_conversion_action
        elif '**Devices Targeted:**' in line:
            devices = line.split('**Devices Targeted:**')[1].strip().upper()
            if devices in ['BOTH', 'BOTH MOBILE AND DESKTOP']:
                recipe['Devices'] = 'ALL'
            else:
                recipe['Devices'] = devices
        elif '**Hypothesis:**' in line:
            hypothesis_base = line.split('**Hypothesis:**')[1].strip()
            cleaned = clean_hypothesis(f"{hypothesis_base} and thus increase the {primary_conversion_action} rate.")
            recipe['Hypothesis'] = cleaned
    numbers = [idea['Number'] for idea in ideas]
    recipe['Task Name'] = f"Recipe {'.'.join(numbers)} | {recipe.get('Task Name', 'Untitled')} | {recipe['Devices']}"
    recipe['URL Template'] = url_template if url_template else "Default URL Template"
    recipe['Target Confidence'] = 95
    recipe['Target Power'] = 80
    recipe['Key Idea Cumulative Priority Score'] = sum(idea.get('IdeaRank', 0) for idea in ideas)
    # If Devices was not parsed, default to 'ALL'
if 'Devices' not in recipe:
    recipe['Devices'] = 'ALL'
    return recipe

def send_to_clickup(recipe, recipes_list_id):
    payload = {
        "name": recipe['Task Name'],
        "description": "",
        "status": "To Do",
        "custom_fields": [
            {"id": CUSTOM_FIELDS['Hypothesis'], "value": recipe['Hypothesis']},
            {"id": CUSTOM_FIELDS['Devices'], "value": DEVICES_MAPPING.get(recipe['Devices'], DEVICES_MAPPING['ALL'])},
            {"id": CUSTOM_FIELDS['Primary Conversion Action'], "value": recipe['Primary Conversion Action']},
            {"id": CUSTOM_FIELDS['Target Confidence'], "value": 95},
            {"id": CUSTOM_FIELDS['Target Power'], "value": 80},
            {"id": CUSTOM_FIELDS['URL Template'], "value": recipe['URL Template']},
            {"id": CUSTOM_FIELDS['Key Idea Cumulative Priority Score'], "value": recipe['Key Idea Cumulative Priority Score']}
        ]
    }
    url = f"https://api.clickup.com/api/v2/list/{recipes_list_id}/task"
    response = requests.post(url, headers=HEADERS, json=payload)
    return response.status_code == 200

# ------------------------------
# Streamlit UI
# ------------------------------
st.title("🔬 A/B Test Recipe Generator")

ids_input = st.text_input("Enter Custom Task IDs (comma separated):")
primary_action = st.text_input("Enter Primary Conversion Action:")
target_url = st.text_input("Enter Target URL:")
recipes_list_id = st.text_input("Enter ClickUp Recipes List ID:")

if st.button("Generate & Submit Recipe"):
    try:
        task_ids = [x.strip() for x in ids_input.split(',') if x.strip()]
        ideas = fetch_ideas_by_ids(task_ids)
        url_template = target_url or ideas[0].get('URL Template') if ideas else ""
        recipe_text = generate_ab_test_recipe(ideas, primary_action)
        recipe = parse_recipe(recipe_text, task_ids, url_template, ideas, primary_action)
        success = send_to_clickup(recipe, recipes_list_id)
        if success:
            st.success(f"✅ Recipe '{recipe['Task Name']}' successfully submitted to ClickUp.")
        else:
            st.error("❌ Failed to submit the recipe to ClickUp.")
    except Exception as e:
        st.error(f"⚠️ Error: {e}")
