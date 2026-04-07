#!/usr/bin/env python3
"""
Scrape routes from the Walkscape wiki Routes page.
Generates routes.py with all route data.
"""

import json
from bs4 import BeautifulSoup
from scraper_utils import *

# Configuration
RESCRAPE = False
ROUTES_URL = 'https://wiki.walkscape.app/wiki/Routes'
CACHE_FILE = get_cache_file('routes_cache.html')

# Create validator instance
validator = ScraperValidator()

def name_to_enum(name):
    """Convert a display name to UPPER_SNAKE_CASE enum format."""
    return re.sub(r'[^A-Z0-9]+', '_', name.upper().replace("'", "")).strip('_')

def normalize_id(name):
    """Convert a display name to lowercase_snake_case ID (matching locations.json format)."""
    return name.lower().replace("'", "").replace("-", "_").replace(" ", "_").strip()

def parse_requirement(note_text):
    """Parse requirement from note text into keyword_counts format."""
    note_lower = note_text.lower()
    
    # Check for collectible requirement: "Have item X with you"
    if 'have item' in note_lower and 'with you' in note_lower:
        # Extract item name from the text
        match = re.search(r'have item\s+(.+?)\s+with you', note_text, re.IGNORECASE)
        if match:
            item_name = match.group(1).strip()
            return ('collectible', item_name)
    
    # Check for ability requirement: "While having X ability"
    if 'while having' in note_lower and 'ability' in note_lower:
        # Extract ability name
        match = re.search(r'while having\s+(.+?)\s+ability', note_text, re.IGNORECASE)
        if match:
            ability_name = match.group(1).strip()
            return ('ability', ability_name)
    
    # Parse keyword requirements with counts (can have multiple on same route)
    keyword_counts = {}
    
    # Check for diving gear requirements - look for [N] unique pattern
    expert_match = re.search(r'\[(\d+)\]\s+unique\s+expert\s+diving\s+gear', note_lower)
    advanced_match = re.search(r'\[(\d+)\]\s+unique\s+advanced\s+diving\s+gear', note_lower)
    diving_match = re.search(r'\[(\d+)\]\s+unique\s+diving\s+gear', note_lower)
    
    if expert_match:
        keyword_counts['expert diving gear'] = int(expert_match.group(1))
    elif advanced_match:
        keyword_counts['advanced diving gear'] = int(advanced_match.group(1))
    elif diving_match:
        keyword_counts['diving gear'] = int(diving_match.group(1))
    elif 'expert diving gear' in note_lower:
        keyword_counts['expert diving gear'] = 3
    elif 'advanced diving gear' in note_lower:
        keyword_counts['advanced diving gear'] = 3
    elif 'diving' in note_lower or 'underwater' in note_lower:
        keyword_counts['diving gear'] = 3
    
    # Check for ski requirements
    if 'skis' in note_lower or 'ski' in note_lower:
        keyword_counts['skis'] = 1
    
    # Check for light source requirements - look for [N] unique pattern
    light_match = re.search(r'\[(\d+)\]\s+unique\s+light\s+source', note_lower)
    if light_match:
        keyword_counts['light source'] = int(light_match.group(1))
    elif '3 light' in note_lower or 'three light' in note_lower:
        keyword_counts['light source'] = 3
    elif '2 light' in note_lower or 'two light' in note_lower:
        keyword_counts['light source'] = 2
    
    # Return keyword_counts if any found
    if keyword_counts:
        return ('keyword_counts', keyword_counts)
    
    return None

def get_region_for_table(table):
    """Determine the region name from the heading preceding a table."""
    # Walk backwards through siblings to find the nearest heading
    current = table.find_previous(['h2', 'h3'])
    if current:
        heading_text = clean_text(current.get_text()).lower()
        # Map wiki section names to region IDs
        if 'jarvonia' in heading_text:
            return 'jarvonia'
        elif 'gdte' in heading_text or 'grand duchy' in heading_text or 'trellin' in heading_text:
            return 'gdte'
        elif 'syrenthia' in heading_text:
            return 'syrenthia'
        elif 'wallisia' in heading_text:
            return 'wallisia'
        elif 'wrentmark' in heading_text:
            return 'wrentmark'
    return ''

def parse_routes():
    """Parse all routes from the cached HTML file."""
    html = download_page(ROUTES_URL, CACHE_FILE, rescrape=RESCRAPE)
    if not html:
        return []

    soup = BeautifulSoup(html, 'html.parser')
    routes = []

    # Find all wikitable tables
    tables = soup.find_all('table', class_='wikitable')

    for table in tables:
        region = get_region_for_table(table)
        rows = table.find_all('tr')[1:]  # Skip header row

        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 6:
                continue

            # New format: 7 columns
            # 0: icon, 1: start location, 2: icon, 3: end location, 4: direction, 5: distance, 6: requirements
            start_loc = clean_text(cells[1].get_text())
            end_loc = clean_text(cells[3].get_text())
            distance_text = clean_text(cells[5].get_text())

            # Parse distance
            try:
                distance = int(distance_text)
            except ValueError:
                print(f"Warning: Could not parse distance '{distance_text}' for {start_loc} -> {end_loc}")
                validator.add_item_issue(f"{start_loc} -> {end_loc}", [f"Invalid distance: {distance_text}"])
                continue

            # Parse requirements from requirements column
            requirement = None
            if len(cells) >= 7:
                note_text = clean_text(cells[6].get_text())
                requirement = parse_requirement(note_text)

            # Convert location names to enum format (for .py output)
            start_enum = name_to_enum(start_loc)
            end_enum = name_to_enum(end_loc)

            # Create route entry
            route = {
                'start': start_enum,
                'end': end_enum,
                'start_name': start_loc,
                'end_name': end_loc,
                'distance': distance,
                'requirement': requirement,
                'region': region,
            }

            routes.append(route)

    return routes

def generate_routes_module(routes):
    """Generate the routes.py module."""
    output_file = get_output_file('routes.py')
    
    print(f"\nGenerating {output_file}...")
    
    # Try to load collectibles for resolution
    collectibles_map = {}
    try:
        from util.autogenerated.collectibles import Collectible
        # Build map of collectible names to enum names
        for attr_name in dir(Collectible):
            if not attr_name.startswith('_'):
                collectible = getattr(Collectible, attr_name)
                if hasattr(collectible, 'name'):
                    collectibles_map[collectible.name.lower()] = f'Collectible.{attr_name}'
    except ImportError:
        print("  Note: Could not import collectibles for resolution")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        write_module_header(f, 'Walkscape Routes Data\nRaw route data extracted from the game wiki.', 'scrape_routes.py')
        write_imports(f, ['from util.autogenerated.locations import Location'])
        lines = [
        'RAW_ROUTES = {',
        ]
        for route in sorted(routes, key=lambda r: (r['start'], r['end'])):
            start = f"Location.{route['start']}"
            end = f"Location.{route['end']}"
            distance = route['distance']
            
            if route['requirement']:
                req_type, req_value = route['requirement']
                
                if req_type == 'collectible':
                    # Try to resolve to Collectible enum
                    collectible_ref = collectibles_map.get(req_value.lower())
                    if collectible_ref:
                        lines.append(f"    ({start}, {end}): {{'distance': {distance}, 'requires': ('collectible', '{collectible_ref}')}},")
                    else:
                        lines.append(f"    ({start}, {end}): {{'distance': {distance}, 'requires': ('collectible', '{req_value}')}},")
                elif req_type == 'ability':
                    lines.append(f"    ({start}, {end}): {{'distance': {distance}, 'requires': ('ability', '{req_value}')}},")
                elif req_type == 'keyword_counts':
                    # New format: keyword_counts dict
                    lines.append(f"    ({start}, {end}): {{'distance': {distance}, 'keyword_counts': {req_value}}},")
            else:
                lines.append(f"    ({start}, {end}): {{'distance': {distance}}},")
        
        lines.append('}')
        write_lines(f, lines)
    
    print(f"Generated {output_file} with {len(routes)} routes")

def generate_routes_json(routes):
    """Generate routes.json for the Streamlit app."""
    output_file = get_output_file('routes.json')

    print(f"\nGenerating {output_file}...")

    json_routes = []
    for route in sorted(routes, key=lambda r: (r['start'], r['end'])):
        start_id = normalize_id(route['start_name'])
        end_id = normalize_id(route['end_name'])

        entry = {
            'id': f"{start_id}__{end_id}",
            'name': f"{route['start_name']} \u2192 {route['end_name']}",
            'start': start_id,
            'end': end_id,
            'distance': route['distance'],
            'region': route['region'],
            'keyword_counts': {},
            'collectible_requirement': None,
            'ability_requirement': None,
        }

        if route['requirement']:
            req_type, req_value = route['requirement']
            if req_type == 'keyword_counts':
                entry['keyword_counts'] = req_value
            elif req_type == 'collectible':
                entry['collectible_requirement'] = req_value
            elif req_type == 'ability':
                entry['ability_requirement'] = req_value

        json_routes.append(entry)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(json_routes, f, indent=2, ensure_ascii=False)

    print(f"Generated {output_file} with {len(json_routes)} routes")

if __name__ == '__main__':
    routes = parse_routes()
    print(f"\nFound {len(routes)} routes")
    generate_routes_module(routes)
    generate_routes_json(routes)

    # Report validation issues (routes don't have stats, but we track other issues)
    validator.report()
