#!/usr/bin/env python3
"""
Scrape services from the Walkscape wiki.
Generates services.json using Pydantic models.
"""

import json
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import unquote

# Add parent directory for imports as requested
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from models import (
    Service, SkillName, Requirement, RequirementType,
    Modifier, StatName, Condition, ConditionType
)
from scraper_utils import *

# Configuration
RESCRAPE = False
SERVICES_URL = 'https://wiki.walkscape.app/wiki/Services'
CACHE_FILE = get_cache_file('services_cache.html')
OUTPUT_FILE = get_output_file('services.json')

validator = ScraperValidator()

def normalize_id(text: str) -> str:
    """Normalize text to snake_case ID."""
    if not text: return "none"
    text = unquote(text)
    text = text.replace('Special:MyLanguage/', '')
    return text.lower().replace("'", "").replace("-", "_").replace(" ", "_").strip()

def parse_skill_enum(text: str) -> SkillName:
    try:
        return SkillName(text.lower())
    except ValueError:
        return SkillName.NONE

def extract_attributes(td) -> list[Modifier]:
    """
    Extract attribute bonuses and convert to Modifiers with Conditions.
    Handles global stats, skill-specific stats, and reputation-gated stats.
    """
    modifiers = []
    text = td.get_text()
    
    if 'None' in text or not text.strip():
        return modifiers
    
    # Clean up text for easier regex matching
    # Replace non-breaking spaces and normalize whitespace
    text = ' '.join(text.split())

    # Regex patterns
    # 1. Global with Reputation: "Global +1% Double rewards Have [5] Faction Reputation"
    global_rep_pattern = r'Global\s+([+-]?\d+(?:\.\d+)?)\s*(%?)\s+(.+?)\s+[Hh]ave\s+\[(\d+)\]\s+(.+?)\s+[Ff]action\s+[Rr]eputation'
    
    # 2. Skill Specific: "+1% Work efficiency While doing Carpentry"
    #    Optionally followed by reputation: "... Have 1000 Faction Reputation"
    skill_pattern = r'([+-]?\d+(?:\.\d+)?)\s*(%?)\s+([A-Za-z\s]+?)\s+While doing\s+([A-Za-z]+)'

    # --- Process Global Reputation Bonuses ---
    for match in re.finditer(global_rep_pattern, text, re.IGNORECASE):
        value_str = match.group(1)
        is_percent = match.group(2) == '%'
        stat_name_raw = match.group(3).strip()
        threshold = int(match.group(4))
        faction = match.group(5).strip().lower().replace(' ', '_')
        
        stat_name = normalize_stat_name(stat_name_raw)
        if not stat_name:
            validator.add_unrecognized_stat('Service', match.group(0))
            continue

        final_stat_name, final_value = parse_stat_value(f"{value_str}{'%' if is_percent else ''}", stat_name)
        
        try:
            stat_enum = StatName(final_stat_name)
            conditions = [
                Condition(type=ConditionType.REPUTATION, target=faction, value=threshold)
            ]
            modifiers.append(Modifier(stat=stat_enum, value=final_value, conditions=conditions))
        except ValueError:
             validator.add_unrecognized_stat('Service', f"Enum error: {final_stat_name}")

    # --- Process Skill Specific Bonuses ---
    for match in re.finditer(skill_pattern, text, re.IGNORECASE):
        value_str = match.group(1)
        is_percent = match.group(2) == '%'
        stat_name_raw = clean_text(match.group(3))
        skill = match.group(4).lower()
        
        stat_name = normalize_stat_name(stat_name_raw)
        if not stat_name:
            validator.add_unrecognized_stat('Service', match.group(0))
            continue

        final_stat_name, final_value = parse_stat_value(f"{value_str}{'%' if is_percent else ''}", stat_name)
        
        # Check for trailing reputation requirement
        # Look ahead in the text after this match
        remaining_text = text[match.end():match.end()+100]
        rep_match = re.search(r'have\s+(?:\[)?(\d+)(?:\])?\s+([A-Za-z\s]+?)\s+Faction Reputation', remaining_text, re.IGNORECASE)
        
        conditions = [
            Condition(type=ConditionType.SKILL_ACTIVITY, target=skill)
        ]
        
        if rep_match:
            threshold = int(rep_match.group(1))
            faction = rep_match.group(2).strip().lower().replace(' ', '_')
            conditions.append(Condition(type=ConditionType.REPUTATION, target=faction, value=threshold))
        
        try:
            stat_enum = StatName(final_stat_name)
            modifiers.append(Modifier(stat=stat_enum, value=final_value, conditions=conditions))
        except ValueError:
             validator.add_unrecognized_stat('Service', f"Enum error: {final_stat_name}")

    return modifiers

def extract_requirements(td) -> list[Requirement]:
    """
    Extract requirements from text.
    """
    text = clean_text(td.get_text())
    requirements = []
    
    if text.lower() == 'none' or not text:
        return requirements
    
    # 1. Diving Gear / Item Counts
    if 'diving gear' in text.lower():
        # Pattern: "Requires [X] unique Diving gear" or "Have X of Diving Gear"
        count = 1
        count_match = re.search(r'(?:\[(\d+)\]|Have (\d+) of)', text, re.IGNORECASE)
        if count_match:
            count = int(count_match.group(1) or count_match.group(2))
        
        target = "advanced diving gear" if 'advanced' in text.lower() else "diving gear"
        requirements.append(Requirement(type=RequirementType.KEYWORD_COUNT, target=normalize_id(target), value=count))
    
    # 2. Reputation
    # "Have X Faction Reputation" or "Have [X] Faction faction reputation"
    rep_match = re.search(r'Have\s+(?:\[)?(\d+)(?:\])?\s+([A-Za-z\s]+?)\s+(?:faction\s+)?Reputation', text, re.IGNORECASE)
    if rep_match:
        amount = int(rep_match.group(1))
        faction = rep_match.group(2).strip().lower().replace(' ', '_')
        requirements.append(Requirement(type=RequirementType.REPUTATION, target=faction, value=amount))

    # 3. Skill Levels
    # "Carpentry lvl. 20" or "Carpentry 20"
    if 'diving gear' not in text.lower() and 'access' not in text.lower():
        skill_pattern = r'([A-Za-z]+)\s+(?:lvl\.?)?\s*(\d+)'
        matches = re.finditer(skill_pattern, text)
        for m in matches:
            name = m.group(1)
            level = int(m.group(2))
            
            # Filter out false positives
            if name.lower() not in ['have', 'reputation', 'level', 'lvl']:
                 requirements.append(Requirement(type=RequirementType.SKILL_LEVEL, target=name.lower(), value=level))

    # 4. Access / Quest
    if 'access' in text.lower():
        access_match = re.search(r'([A-Za-z\s]+)\s+Access', text, re.IGNORECASE)
        if access_match:
            req_name = normalize_id(access_match.group(1).strip() + "_access")
            requirements.append(Requirement(type=RequirementType.QUEST_COMPLETED, target=req_name, value=1))

    return requirements

def parse_services():
    """Parse all services from the cached HTML file."""
    print("Downloading Services page...")
    html = download_page(SERVICES_URL, CACHE_FILE, rescrape=RESCRAPE)
    if not html: return []
    
    soup = BeautifulSoup(html, 'html.parser')
    
    services = []
    seen_services = set()
    current_category = None
    current_tier = None
    
    content_div = soup.find('div', class_='mw-parser-output')
    if not content_div: return []
    
    # Iterate over direct children to handle H2/H3 context
    # Updated to handle MediaWiki 1.44+ struct where headings are wrapped in div.mw-heading
    for element in content_div.children:
        # Check if element is a wrapper div for headings
        heading = None
        if element.name == 'div' and 'mw-heading' in element.get('class', []):
            heading = element.find(['h2', 'h3'])
        elif element.name in ['h2', 'h3']:
            heading = element
        
        # Process Heading
        if heading:
            text = clean_text(heading.get_text())
            text = re.sub(r'^\d+(\.\d+)?\s*', '', text) # Remove numbering
            
            if heading.name == 'h2':
                if 'services' in text.lower():
                    current_category = text.replace(' Services', '').strip()
                else:
                    # Reset context for non-service sections (Levels, Wardrobes, Merchant)
                    current_category = None
                    
            elif heading.name == 'h3':
                # Normalize tier name (remove plural)
                if text.endswith('ches'): current_tier = text[:-2]
                elif text.endswith('s') and not text.endswith('ss'): current_tier = text[:-1]
                else: current_tier = text
        
        # Process Table
        elif element.name == 'table' and 'wikitable' in element.get('class', []):
            if not current_category: continue
            
            # Verify table headers
            headers = [clean_text(th.get_text()) for th in element.find_all('th')]
            if 'Name' not in str(headers) or 'Location' not in str(headers):
                continue

            # Process Rows
            rows = element.find_all('tr')[1:]
            for row in rows:
                cells = row.find_all('td')
                if len(cells) < 4: continue
                
                # 1. Name & Tier
                full_name = clean_text(cells[1].get_text())
                name_match = re.match(r'(.+?)\s*\((Basic|Advanced)\)', full_name)
                if name_match:
                    service_name = name_match.group(1).strip()
                else:
                    service_name = full_name
                
                # 2. Tier (Column 2) - Fallback to current_tier if empty
                cell_tier = clean_text(cells[2].get_text()) if len(cells) > 2 else ""
                tier = cell_tier if cell_tier else current_tier
                
                # 3. Locations (Column 3)
                location_cell = cells[3]
                # Replace <br> with pipe for splitting
                for br in location_cell.find_all('br'): br.replace_with('|')
                loc_text = location_cell.get_text()
                location_names = [l.strip() for l in loc_text.split('|') if l.strip()]
                
                # 4. Attributes (Column 4)
                modifiers = []
                if len(cells) > 4:
                    modifiers = extract_attributes(cells[4])
                
                # 5. Requirements (Column 5)
                requirements = []
                if len(cells) > 5:
                    requirements = extract_requirements(cells[5])
                
                # Create a Service entry for EACH location
                for loc_name in location_names:
                    loc_id = normalize_id(loc_name)
                    service_id = normalize_id(f"{service_name}_{loc_name}")
                    
                    if service_id in seen_services: continue
                    seen_services.add(service_id)
                    
                    try:
                        service = Service(
                            id=service_id,
                            wiki_slug=full_name.replace(' ', '_'),
                            name=service_name,
                            skill=parse_skill_enum(current_category),
                            tier=tier,
                            location=loc_id,
                            requirements=requirements,
                            modifiers=modifiers
                        )
                        services.append(service)
                        print(f"  Processed: {service_name} ({tier}) at {loc_name}")
                    except Exception as e:
                        print(f"  Error creating service {service_name}: {e}")

    return services

def main():
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    data = parse_services()
    
    print(f"\nExporting {len(data)} services to {OUTPUT_FILE}...")
    json_data = [item.model_dump(mode='json') for item in data]
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    
    validator.report()
    print("Done.")

if __name__ == "__main__":
    main()