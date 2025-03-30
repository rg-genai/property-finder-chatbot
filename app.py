import streamlit as st
import time
import google.generativeai as genai
from google.api_core.exceptions import TooManyRequests
import json
import re
from duckduckgo_search import DDGS

# Configure the Gemini API key (Keep this secure, consider using Streamlit secrets)
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# Backend functions (copy your existing functions here)
def search_properties(preferences):
    location = preferences.get('location', 'Mumbai')
    budget = preferences.get('budget', '')
    carpet_area = preferences.get('carpet_area', '')
    floor_preference = preferences.get('floor_preference', '')
    financing = preferences.get('financing', '')

    search_query_parts = [f"property for sale in {location}"]
    if budget:
        search_query_parts.append(f"budget {budget}")
    if carpet_area:
        search_query_parts.append(f"carpet area around {carpet_area} sq ft")
    if floor_preference:
        search_query_parts.append(f"floor preference {floor_preference}")

    search_query = " ".join(search_query_parts)
    st.info(f"Searching for: {search_query}")
    ddgs = DDGS()
    results = list(ddgs.text(search_query, region='in-mh', max_results=5)) # Limiting for Streamlit demo
    return results

def analyze_property_with_gemini_with_retry(search_result, max_retries=3, initial_delay=5):
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"""You are an AI Property Assistant. Analyze the following property listing and extract the information as a JSON object. Do not include any other text or explanations in your response.

{{
  "price": "approximate price if mentioned",
  "area_sqft": "carpet or built-up area in square feet if mentioned",
  "bedrooms": "number of bedrooms if mentioned",
  "bathrooms": "number of bathrooms if mentioned",
  "amenities": ["list of key amenities mentioned"],
  "builder": "name of the builder/constructor if mentioned",
  "builder_reputation_highlights": "any highlights about the builder's reputation or past projects mentioned in the listing",
  "locality_highlights": "key highlights or features of the locality mentioned"
}}

Title: {search_result['title']}
Description: {search_result['body']}

If a piece of information is not available, set its value to null or an empty list/string. Ensure the output is a valid JSON object.
"""
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            raw_response = response.text.strip()
            if raw_response.startswith("```json"):
                raw_response = raw_response[len("```json"):].strip()
            elif raw_response.startswith("```"):
                raw_response = raw_response[len("```"):].strip()
            if raw_response.endswith("```"):
                raw_response = raw_response[:-len("```")].strip()

            if not raw_response.startswith('{'):
                st.warning(f"Gemini's response issue (Attempt {attempt + 1}): {raw_response[:50]}...")
                return {"error": "Response format issue"}

            try:
                analysis_dict = json.loads(raw_response)
                return analysis_dict
            except json.JSONDecodeError as e:
                st.warning(f"JSON Decode Error (Attempt {attempt + 1}): {raw_response}")
                st.error(f"JSONDecodeError: {e}")
                return {"error": "Could not parse analysis"}
        except TooManyRequests as e:
            if attempt < max_retries - 1:
                delay = initial_delay * (2 ** attempt)
                st.warning(f"Rate limit exceeded. Retrying in {delay:.2f} seconds...")
                time.sleep(delay)
            else:
                st.error(f"Failed after {max_retries} retries due to rate limit: {e}")
                return {"error": "Rate limit exceeded"}
        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")
            return {"error": f"Unexpected error: {e}"}
    return {"error": "Analysis failed after multiple retries"}

def compare_properties(analyzed_properties, user_preferences, search_results):
    compared_properties = []
    preferred_location = user_preferences.get('location', '').lower()
    preferred_budget_str = user_preferences.get('budget', '')
    preferred_area_str = user_preferences.get('carpet_area', '')
    preferred_floor = user_preferences.get('floor_preference', '').lower()
    financing_available = user_preferences.get('financing', '').lower()
    preferred_amenities_str = user_preferences.get('preferred_amenities', '').lower()
    preferred_amenities = [amenity.strip() for amenity in preferred_amenities_str.split(',') if amenity.strip()]

    def get_numeric_budget(budget_str):
        budget_str = budget_str.lower().replace('approx.', '').replace('rs.', '').replace(',', '').replace('₹', '')
        parts = budget_str.split('-')
        if len(parts) == 2:
            try:
                return float(parts[0].strip()) * 10000000 if 'cr' in parts[0].lower() else float(parts[0].strip()) * 100000 if 'lac' in parts[0].lower() else float(parts[0].strip()), \
                       float(parts[1].strip()) * 10000000 if 'cr' in parts[1].lower() else float(parts[1].strip()) * 100000 if 'lac' in parts[1].lower() else float(parts[1].strip())
            except ValueError:
                return None, None
        try:
            value = float(budget_str.strip())
            if 'cr' in budget_str.lower():
                return value * 10000000, value * 10000000
            elif 'lac' in budget_str.lower():
                return value * 100000, value * 100000
            else:
                return value, value
        except ValueError:
            return None, None

    min_preferred_budget, max_preferred_budget = get_numeric_budget(preferred_budget_str)

    def get_numeric_area(area_str):
        area_str = area_str.lower().replace('sq ft', '').strip()
        try:
            return float(area_str)
        except ValueError:
            return None

    preferred_area = get_numeric_area(preferred_area_str)

    for i, prop_analysis in enumerate(analyzed_properties):
        if "error" not in prop_analysis:
            comparison_details = {
                'property_index': i + 1,
                'url': search_results[i]['href'],
                'title': search_results[i]['title'],
                'analysis': prop_analysis,
                'comparison_points': []
            }

            # Location Comparison
            location_match = False
            result = search_results[i]
            locality_highlights = prop_analysis.get('locality_highlights')
            if locality_highlights and isinstance(locality_highlights, str) and preferred_location in locality_highlights.lower():
                location_match = True
                comparison_details['comparison_points'].append("Location: Matches preferred location.")
            elif locality_highlights and isinstance(locality_highlights, list) and any(preferred_location in item.lower() for item in locality_highlights):
                location_match = True
                comparison_details['comparison_points'].append("Location: Matches preferred location.")
            elif preferred_location in result['title'].lower() or preferred_location in result['body'].lower():
                location_match = True
                comparison_details['comparison_points'].append("Location: Matches preferred location.")
            else:
                comparison_details['comparison_points'].append("Location: Might not match preferred location.")

            # Budget Comparison
            price = prop_analysis.get('price')
            budget_friendly = False
            if price:
                price_lower = price.lower()
                prop_min_budget, prop_max_budget = get_numeric_budget(price_lower)
                if min_preferred_budget is not None and prop_min_budget is not None:
                    if max_preferred_budget is not None and prop_max_budget is not None:
                        if min_preferred_budget <= prop_max_budget and max_preferred_budget >= prop_min_budget:
                            budget_friendly = True
                            comparison_details['comparison_points'].append("Budget: Potentially within budget.")
                        else:
                            comparison_details['comparison_points'].append("Budget: Potentially outside budget.")
                    elif max_preferred_budget is None and min_preferred_budget <= prop_min_budget:
                         budget_friendly = True
                         comparison_details['comparison_points'].append("Budget: Potentially within budget.")
                    elif prop_max_budget is None and max_preferred_budget >= prop_min_budget:
                        budget_friendly = True
                        comparison_details['comparison_points'].append("Budget: Potentially within budget.")
                    elif prop_min_budget == prop_max_budget and min_preferred_budget <= prop_min_budget <= max_preferred_budget:
                        budget_friendly = True
                        comparison_details['comparison_points'].append("Budget: Potentially within budget.")
                    else:
                        comparison_details['comparison_points'].append("Budget: Potentially outside budget.")
                else:
                    comparison_details['comparison_points'].append("Budget: Price information unclear for comparison.")
            else:
                comparison_details['comparison_points'].append("Budget: No price information found.")

            # Area Comparison
            area_data = prop_analysis.get('area_sqft')
            area_str = ''
            if isinstance(area_data, dict):
                if 'carpet' in area_data and area_data['carpet']:
                    area_str = str(area_data['carpet'])
                elif 'built_up' in area_data and area_data['built_up']:
                    area_str = str(area_data['built_up'])
            elif isinstance(area_data, (int, float, str)):
                area_str = str(area_data)

            prop_area = get_numeric_area(area_str.lower()) if area_str else None
            if preferred_area is not None and prop_area is not None:
                area_difference_percentage = abs(preferred_area - prop_area) / preferred_area
                if area_difference_percentage < 0.1: # Allowing a 10% difference
                    comparison_details['comparison_points'].append(f"Area: Close to preferred area ({preferred_area} sq ft).")
                elif prop_area > preferred_area:
                    comparison_details['comparison_points'].append(f"Area: Larger than preferred area ({preferred_area} sq ft).")
                elif prop_area < preferred_area:
                    comparison_details['comparison_points'].append(f"Area: Smaller than preferred area ({preferred_area} sq ft).")
            elif preferred_area is not None and prop_area is None and area_str:
                comparison_details['comparison_points'].append("Area: Could not determine area for comparison.")
            elif preferred_area is not None and not area_str:
                comparison_details['comparison_points'].append("Area: No area information found.")

            # Floor Preference
            if preferred_floor and preferred_floor in result['title'].lower() or preferred_floor in result['body'].lower():
                comparison_details['comparison_points'].append(f"Floor Preference: Mentions preferred floor ({preferred_floor}).")
            elif preferred_floor:
                comparison_details['comparison_points'].append(f"Floor Preference: Does not mention preferred floor ({preferred_floor}).")

            # Amenities Comparison
            property_amenities = [amenity.lower().strip() for amenity in prop_analysis.get('amenities', [])]
            found_preferred = []
            not_found_preferred = []
            for pref_amenity in preferred_amenities:
                normalized_pref_amenity = pref_amenity.lower().strip()
                if normalized_pref_amenity in property_amenities:
                    found_preferred.append(pref_amenity)
                else:
                    not_found_preferred.append(pref_amenity)

            if found_preferred:
                comparison_details['comparison_points'].append(f"Amenities: Includes preferred amenities: {', '.join(found_preferred)}.")
            if not_found_preferred:
                comparison_details['comparison_points'].append(f"Amenities: Missing some preferred amenities: {', '.join(not_found_preferred)}.")
            elif preferred_amenities and not found_preferred:
                comparison_details['comparison_points'].append("Amenities: Does not mention any preferred amenities.")
            elif not preferred_amenities:
                comparison_details['comparison_points'].append("Amenities: No preferred amenities specified.")

            # Financing
            if financing_available and financing_available in result['title'].lower() or financing_available in result['body'].lower():
                comparison_details['comparison_points'].append(f"Financing: Mentions related financing options ({financing_available}).")
            elif financing_available:
                comparison_details['comparison_points'].append(f"Financing: Does not mention related financing options ({financing_available}).")

            # Builder Reputation Highlights
            builder_reputation = prop_analysis.get('builder_reputation_highlights')
            if builder_reputation:
                comparison_details['comparison_points'].append(f"Builder Reputation: Highlights mentioned in listing.")

            compared_properties.append(comparison_details)

        else:
            st.error(f"Property {i+1} Analysis failed: {prop_analysis['error']}")

    return compared_properties

def get_locality_information(location):
    st.subheader(f"Locality Information for {location}")
    ddgs = DDGS()
    locality_info = {}
    all_snippets = []

    queries = [
        f"{location} schools",
        f"{location} hospitals",
        f"{location} malls",
        f"{location} distance from railway station",
        f"{location} distance from metro station",
        f"{location} distance from airport",
        f"{location} places to visit",
        f"{location} crime rate safety",
        f"{location} problems"
    ]

    for query in queries:
        results = list(ddgs.text(query, region='in-mh', max_results=1)) # Limiting to 1 for brevity in Streamlit
        if results:
            for result in results:
                all_snippets.append(result['body'])
                time.sleep(1)
            locality_info[query] = results
        else:
            locality_info[query] = []
            time.sleep(1)

    locality_summary = ""
    if all_snippets:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""You are a helpful AI assistant summarizing information about the locality of {location} for a potential home buyer. Based on the following information found on the internet, provide a concise summary covering aspects like nearby schools, hospitals, malls, distance from railway station, metro station, airport, places to visit, crime rate, safety parameters, and any potential problems.

Information:
{' '.join(all_snippets)}

Locality Summary for Buyer:
"""
        try:
            response = model.generate_content(prompt)
            locality_summary = response.text.strip()
            st.info(f"Locality Summary:\n{locality_summary}")
        except Exception as e:
            st.error(f"Error summarizing locality information: {e}")
    else:
        st.info("No significant locality information found online to summarize.")

    return locality_summary

def get_builder_information(builder_name):
    builder_summary = ""
    if builder_name:
        st.subheader(f"Builder Information for {builder_name}")
        ddgs = DDGS()
        builder_info = {}
        all_snippets = []
        queries = [
            f"{builder_name} reputation",
            f"{builder_name} past projects",
            f"{builder_name} reviews"
        ]
        for query in queries:
            results = list(ddgs.text(query, region='in-mh', max_results=1)) # Limiting to 1 for brevity
            if results:
                for result in results:
                    all_snippets.append(result['body'])
                    time.sleep(1)
                builder_info[query] = results
            else:
                builder_info[query] = []
                time.sleep(1)

        if all_snippets:
            model = genai.GenerativeModel('gemini-1.5-flash')
            prompt = f"""You are a helpful AI assistant summarizing information about a property builder named {builder_name}. Based on the following information found on the internet, provide a concise summary of potential pros and cons for a buyer.

Information:
{' '.join(all_snippets)}

Summary of potential pros:
-

Summary of potential cons:
-
"""
            try:
                response = model.generate_content(prompt)
                builder_summary = response.text.strip()
                st.info(f"Builder Summary:\n{builder_summary}")
            except Exception as e:
                st.error(f"Error summarizing builder information: {e}")
        else:
            st.info("No significant builder information found online to summarize.")

    return builder_summary

def generate_property_summary(user_preferences, comparison_points):
    model = genai.GenerativeModel('gemini-1.5-flash')
    summary_prompt = f"""Based on your preferences:
Location: {user_preferences.get('location')}
Budget: {user_preferences.get('budget')}
Carpet Area: {user_preferences.get('carpet_area')} sq ft
Floor Preference: {user_preferences.get('floor_preference')}
Preferred Amenities: {user_preferences.get('preferred_amenities')}
Financing Options: {user_preferences.get('financing')}

And the following comparison points for this property:
{' '.join(comparison_points)}

Provide a short, concise summary of how well this property aligns with the user's overall preferences, highlighting potential pros and cons.
"""
    try:
        response = model.generate_content(summary_prompt)
        property_summary = response.text.strip()
        return property_summary
    except Exception as e:
        return f"Error generating property summary: {e}"

# Streamlit App
st.title("AI Property Assistant")
st.write("Enter your preferences to find your dream property in Mumbai!")

with st.form("user_preferences"):
    location = st.text_input("Preferred Location in Mumbai", "Chembur")
    budget = st.text_input("Budget Range (e.g., 1 Cr - 2 Cr)", "1 Cr - 1.5 Cr")
    carpet_area = st.text_input("Expected Carpet Area (in sq ft)", "800")
    floor_preference = st.text_input("Preferred Floor or Specific Requirements", "Any")
    preferred_amenities = st.text_input("Preferred Amenities (comma-separated)", "Parking, Gym")
    financing = st.text_input("Financing Options (e.g., Pre-approved Loan)", "None")
    submitted = st.form_submit_button("Find Properties")

if submitted:
    user_preferences = {
        'location': location,
        'budget': budget,
        'carpet_area': carpet_area,
        'floor_preference': floor_preference,
        'preferred_amenities': preferred_amenities,
        'financing': financing
    }

    with st.spinner("Fetching locality information..."):
        locality_summary = get_locality_information(user_preferences['location'])

    with st.spinner("Searching for properties..."):
        search_results = search_properties(user_preferences)

    analyzed_properties = []
    if search_results:
        st.subheader("Analyzing Properties...")
        with st.spinner("Analyzing properties using AI..."):
            num_results_to_analyze = 3 # Limit for Streamlit demo
            for i, result in enumerate(search_results[:num_results_to_analyze]):
                st.write(f"Analyzing property {i+1}: {result['title']}")
                analysis = analyze_property_with_gemini_with_retry(result)
                if not analysis.get("error"):
                    analyzed_properties.append(analysis)
                else:
                    st.error(f"Analysis failed for: {result['title']} - {analysis.get('error')}")
                time.sleep(1) # Be mindful of API rate limits
    else:
        st.warning("No search results found based on your preferences.")

    ranked_properties = []
    if analyzed_properties and search_results:
        with st.spinner("Comparing properties..."):
            compared_properties = compare_properties(analyzed_properties, user_preferences, search_results[:len(analyzed_properties)])

            def calculate_score(comparison_details):
                score = 0
                for point in comparison_details['comparison_points']:
                    if "Matches preferred location" in point:
                        score += 5
                    elif "Potentially within budget" in point:
                        score += 4
                    elif "Close to preferred area" in point:
                        score += 3
                    elif "Includes preferred amenities" in point:
                        score += 2
                    elif "Mentions preferred floor" in point:
                        score += 1
                return score

            for i, prop in enumerate(compared_properties):
                score = calculate_score(prop)
                prop['score'] = score
                prop['search_result'] = search_results[i] # Store original search result for link
                ranked_properties.append(prop)

            ranked_properties.sort(key=lambda x: x['score'], reverse=True)

    if ranked_properties:
        st.subheader("Top 3 Property Recommendations")
        for i, prop in enumerate(ranked_properties[:3]):
            st.markdown(f"### Recommendation {i + 1}")
            st.write(f"**Property:** {prop['search_result']['title']}")
            st.write(f"**Link:** {prop['search_result']['href']}")

            builder_name = prop['analysis'].get('builder', 'Not mentioned')
            get_builder_information(builder_name)

            property_summary = generate_property_summary(user_preferences, prop['comparison_points'])
            st.info(f"**Property Summary:**\n{property_summary}")
            st.write("---")
    else:
        st.info("No suitable properties found based on your preferences.")