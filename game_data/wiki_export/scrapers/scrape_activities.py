#!/usr/bin/env python3
"""
Scrape Activities from Walkscape wiki and generate activities.json
"""

import json
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import unquote

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import (
    Activity, Requirement, RequirementType, DropEntry, 
    FactionReward, SkillName
)
from scraper_utils import *

# Configuration
RESCRAPE = False
ACTIVITIES_URL = 'https://wiki.walkscape.app/wiki/Activities'
CACHE_DIR = get_cache_dir('activities')
OUTPUT_FILE = get_output_file('activities.json')
MAIN_CACHE_FILE = CACHE_DIR / 'activities_list.html'

SKIP_ACTIVITIES = ['Traveling']
validator = ScraperValidator()

# ============================================================================
# HELPERS
# ============================================================================

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

def clean_text(text: str) -> str:
    return ' '.join(text.split()).strip()

def parse_number(text: str) -> float:
    text = text.strip().replace('+', '')
    try:
        return float(text)
    except ValueError:
        return 0.0

# ============================================================================
# ORIGINAL SCRAPER PARSING LOGIC
# ============================================================================

def parse_activities_list():
    """Parse the main activities list to get all activity names and basic info."""
    print("Downloading activities list...")
    html = download_page(ACTIVITIES_URL, MAIN_CACHE_FILE, rescrape=RESCRAPE)
    if not html: return []
    
    soup = BeautifulSoup(html, 'html.parser')
    activities = []
    
    tables = soup.find_all('table', class_='wikitable')
    if len(tables) < 2: return []
    
    table = tables[1]
    rows = table.find_all('tr')[1:]
    
    for row in rows:
        cols = row.find_all('td')
        if len(cols) < 4: continue
        
        link = cols[1].find('a')
        if not link: continue
        
        name = link.get_text(strip=True)
        if name in SKIP_ACTIVITIES: continue
        
        href = link.get('href', '')
        url = 'https://wiki.walkscape.app' + href
        slug = href.split('/wiki/')[-1]
        
        activities.append({'name': name, 'url': url, 'slug': slug})
    
    return activities

def parse_infobox(infobox, activity_data):
    """Parse an infobox table for activity details (Original Logic)."""
    rows = infobox.find_all('tr')
    
    for row in rows:
        header = row.find('th')
        data = row.find('td')
        
        if not header or not data: continue
        
        header_text = clean_text(header.get_text())
        data_text = clean_text(data.get_text())
        
        if 'Main Skill' in header_text:
            skill_link = data.find('a', href=re.compile(r'/wiki/(Special:MyLanguage/)?(Agility|Carpentry|Cooking|Crafting|Fishing|Foraging|Mining|Smithing|Trinketry|Woodcutting)'))
            if skill_link:
                activity_data['primary_skill'] = skill_link.get_text(strip=True)
        
        elif 'Location' in header_text:
            location_links = data.find_all('a')
            for link in location_links:
                loc_name = clean_text(link.get_text())
                if loc_name and loc_name not in activity_data['locations']:
                    activity_data['locations'].append(loc_name)
        
        elif 'Skill' in header_text and 'Level' in header_text:
             # Skill requirements logic
            skill_links = data.find_all('a', href=re.compile(r'/wiki/(Agility|Carpentry|Cooking|Crafting|Fishing|Foraging|Mining|Smithing|Trinketry|Woodcutting)'))
            for link in skill_links:
                skill_name = link.get('title', '').strip()
                if not skill_name: continue
                parent = link.parent
                if parent:
                    text = parent.get_text()
                    level_match = re.search(r'lvl?\s*(\d+)', text, re.IGNORECASE)
                    if level_match:
                        activity_data['skill_requirements'][skill_name] = int(level_match.group(1))

        elif 'Requirements' in header_text or 'Requirement' in header_text:
            # Note: The original scraper called a function that crashed here for dicts.
            # We fix it by parsing the text into the dict structure.
            parse_requirements_text(data_text, activity_data)
        
        elif 'Base Steps' in header_text or 'Steps' in header_text:
            try:
                steps = parse_number(data_text)
                if steps: activity_data['base_steps'] = int(steps)
            except: pass
        
        elif 'Base XP' in header_text or 'Experience' in header_text:
            try:
                xp = parse_number(data_text)
                if xp: activity_data['base_xp'] = xp
            except: pass
        
        elif 'Max Efficiency' in header_text or 'Maximum Efficiency' in header_text:
            try:
                max_eff_match = re.search(r'(\d+(?:\.\d+)?)\s*%', data_text)
                if max_eff_match:
                    max_eff_pct = float(max_eff_match.group(1))
                    activity_data['max_efficiency'] = round((max_eff_pct / 100.0) - 1.0, 2)
            except: pass
        
        elif 'Reputation' in header_text and 'Faction' not in header_text:
            try:
                rep_matches = re.findall(r'([A-Za-z\s]+?)\s*[:\+]\s*\+?(\d+)', data_text)
                for faction, amount in rep_matches:
                    faction = faction.strip()
                    if faction and amount:
                        activity_data['faction_reputation'][faction] = float(amount)
            except: pass

def parse_requirements_text(req_text, activity_data):
    """Parse text requirements into the dict structure."""
    if not req_text or req_text == 'None': return

    # Diving gear
    if 'diving gear' in req_text.lower():
        match = re.search(r'(\d+)\s+diving gear', req_text, re.IGNORECASE)
        count = int(match.group(1)) if match else 1
        activity_data['requirements']['keyword_counts']['diving_gear'] = count
    
    # Tools
    if 'tool' in req_text.lower():
        tool_match = re.search(r'Have\s+(\w+)\s+tool\s+equipped', req_text, re.IGNORECASE)
        if tool_match:
            activity_data['requirements']['tool_equipped'] = tool_match.group(1)
        unique_match = re.search(r'(\d+)\s+unique\s+tools?', req_text, re.IGNORECASE)
        if unique_match:
            activity_data['requirements']['unique_tools'] = int(unique_match.group(1))
    
    # Light sources
    light_match = re.search(r'(\d+)\s+(?:unique\s+)?light\s+sources?', req_text, re.IGNORECASE)
    if light_match:
        activity_data['requirements']['keyword_counts']['light_source'] = int(light_match.group(1))
    
    # Reputation
    rep_match = re.search(r'(\d+)\s+reputation\s+with\s+([^,\.]+)', req_text, re.IGNORECASE)
    if rep_match:
        amount = int(rep_match.group(1))
        faction = clean_text(rep_match.group(2))
        activity_data['requirements']['reputation'][faction] = amount
    
    # Activity completions
    completion_match = re.search(r'completed?\s+(?:the\s+)?(.+?)\s+activity\s+\((\d+)\)\s+times', req_text, re.IGNORECASE)
    if completion_match:
        activity = clean_text(completion_match.group(1))
        count = int(completion_match.group(2))
        activity_data['requirements']['activity_completions'][activity] = count

def parse_locations_section(soup, activity_data):
    """Parse locations from the Location/Locations section (Original Logic)."""
    content = soup.find('div', class_='mw-parser-output')
    if not content: return
    
    location_heading = content.find('h1', id='Location') or content.find('h1', id='Locations')
    if not location_heading: return
    
    next_elem = location_heading.parent.find_next_sibling()
    while next_elem:
        if next_elem.name == 'ul':
            for li in next_elem.find_all('li'):
                location_link = li.find('a', href=re.compile(r'/wiki/(?!File:)'))
                if location_link:
                    loc_name = clean_text(location_link.get_text())
                    if loc_name and loc_name not in activity_data['locations']:
                        activity_data['locations'].append(loc_name)
            break
        elif next_elem.name in ['h1', 'h2']: break
        next_elem = next_elem.find_next_sibling()

def parse_requirements_section(soup, activity_data):
    """Parse requirements section (Original Logic)."""
    content = soup.find('div', class_='mw-parser-output')
    if not content: return
    
    req_heading = content.find('h1', id='Requirement') or content.find('h1', id='Requirements')
    if not req_heading: return
    
    next_elem = req_heading.parent.find_next_sibling()
    while next_elem:
        if next_elem.name in ['h1', 'h2']: break
        
        text = next_elem.get_text()
        
        # Skill Levels
        skill_matches = re.findall(r'At least.*?(\w+)\s+lvl?\.\s*(\d+)', text, re.IGNORECASE)
        for skill_name, level in skill_matches:
            activity_data['skill_requirements'][skill_name] = int(level)
        
        # Keyword Counts (ul)
        if next_elem.name == 'ul':
            for li in next_elem.find_all('li'):
                li_text = li.get_text()
                keyword_links = li.find_all('a', href=re.compile(r'Keyword', re.I))
                for keyword_link in keyword_links:
                    if '/wiki/File:' in keyword_link.get('href', ''): continue
                    keyword_name = clean_text(keyword_link.get_text())
                    if keyword_name:
                        keyword_lower = normalize_id(keyword_name) # Internal ID use
                        count_match = re.search(r'\[(\d+)\].*?' + re.escape(keyword_name), li_text, re.IGNORECASE)
                        count = int(count_match.group(1)) if count_match else 1
                        
                        current = activity_data['requirements']['keyword_counts'].get(keyword_lower, 0)
                        activity_data['requirements']['keyword_counts'][keyword_lower] = max(current, count)
                
                if 'achievement point' in li_text.lower():
                    ap_match = re.search(r'\[(\d+)\].*?achievement point', li_text, re.IGNORECASE)
                    if ap_match:
                        activity_data['requirements']['achievement_points'] = int(ap_match.group(1))

        # Light sources in text
        if 'light source' in text.lower():
            match = re.search(r'\[(\d+)\].*?light\s+sources?', text, re.IGNORECASE)
            if match:
                count = int(match.group(1))
                current = activity_data['requirements']['keyword_counts'].get('light_source', 0)
                activity_data['requirements']['keyword_counts']['light_source'] = max(current, count)

        # Reputation
        rep_match = re.search(r'(\d+)\s+reputation\s+with\s+([^,\.]+)', text, re.IGNORECASE)
        if rep_match:
            amount = int(rep_match.group(1))
            faction = clean_text(rep_match.group(2))
            activity_data['requirements']['reputation'][faction] = amount
        
        # Activity completion
        completion_match = re.search(r'completed?\s+(?:the\s+)?(.+?)\s+activity\s+\((\d+)\)\s+times', text, re.IGNORECASE)
        if completion_match:
            activity_name = clean_text(completion_match.group(1))
            count = int(completion_match.group(2))
            activity_data['requirements']['activity_completions'][activity_name] = count
            
        next_elem = next_elem.find_next_sibling()

def parse_experience_table(soup, activity_data):
    """Parse base XP and steps from Experience Information table (Original Logic)."""
    content = soup.find('div', class_='mw-parser-output')
    if not content: return
    
    exp_heading = content.find('h1', id='Experience_Information')
    if not exp_heading: return
    
    next_elem = exp_heading.parent.find_next_sibling()
    while next_elem:
        if next_elem.name == 'table' and 'wikitable' in next_elem.get('class', []):
            rows = next_elem.find_all('tr')
            if len(rows) < 2: break
            
            data_rows = rows[1:]
            skills_and_xp = []
            base_steps = None
            
            for row_idx, row in enumerate(data_rows):
                cols = row.find_all('td')
                if len(cols) < 3: continue
                
                skill_link = cols[1].find('a', href=re.compile(r'/wiki/(Special:MyLanguage/)?(Agility|Carpentry|Cooking|Crafting|Fishing|Foraging|Mining|Smithing|Trinketry|Woodcutting)'))
                if not skill_link: continue
                
                skill_name = skill_link.get_text(strip=True)
                try:
                    xp = int(clean_text(cols[2].get_text()))
                    skills_and_xp.append((skill_name, xp))
                except: pass
                
                if base_steps is None and row_idx == 0 and len(cols) > 3:
                    try:
                        steps_text = clean_text(cols[3].get_text())
                        base_steps = int(steps_text)
                    except: pass
            
            if base_steps:
                activity_data['base_steps'] = base_steps
            
            if skills_and_xp:
                primary_skill, primary_xp = skills_and_xp[0]
                activity_data['base_xp'] = primary_xp
                for skill_name, xp in skills_and_xp[1:]:
                    activity_data['secondary_xp'][skill_name] = xp
            break
        elif next_elem.name in ['h1', 'h2']: break
        next_elem = next_elem.find_next_sibling()

def parse_faction_reputation(soup, activity_data):
    """Parse faction reputation from headers (Original Logic)."""
    content = soup.find('div', class_='mw-parser-output')
    if not content: return
    
    # Try different heading levels
    rep_heading = None
    for level in ['h3', 'h2', 'h1']:
        rep_heading = content.find(level, id='Faction_Reputation_Reward')
        if rep_heading: break
    
    if not rep_heading:
        # Fuzzy match
        all_headings = content.find_all(['h1', 'h2', 'h3'])
        for heading in all_headings:
            if 'faction' in heading.get_text().lower() and 'reward' in heading.get_text().lower():
                rep_heading = heading
                break
    
    if not rep_heading: return
    
    next_elem = rep_heading.parent.find_next_sibling()
    while next_elem:
        if next_elem.name == 'table' and 'wikitable' in next_elem.get('class', []):
            rows = next_elem.find_all('tr')
            if len(rows) >= 2:
                data_row = rows[1]
                cols = data_row.find_all('td')
                if len(cols) >= 3:
                    faction_name = clean_text(cols[1].get_text())
                    amount_text = clean_text(cols[2].get_text())
                    try:
                        amount_match = re.search(r'\+?([\d.]+)', amount_text)
                        if amount_match and faction_name:
                            activity_data['faction_reputation'][faction_name] = float(amount_match.group(1))
                    except: pass
            break
        elif next_elem.name in ['h1', 'h2', 'h3']: break
        next_elem = next_elem.find_next_sibling()

def parse_drop_tables(soup, activity_data):
    """Parse drop tables (Original Logic + Heuristic Fix)."""
    content = soup.find('div', class_='mw-parser-output')
    if not content: return
    
    tables = content.find_all('table', class_='wikitable')
    faction_names = ['Erdwise', 'Halfling Rebels', 'Jarvonia', 'Syrenthia', 'Trellin']
    skill_names = [s.value.capitalize() for s in SkillName]
    
    for table in tables:
        caption = table.find('caption')
        caption_text = clean_text(caption.get_text()) if caption else ""
        if not caption:
            prev = table.find_previous(['h2', 'h3', 'h4'])
            caption_text = clean_text(prev.get_text()) if prev else ""
            
        if 'reputation' in caption_text.lower() and 'reward' in caption_text.lower(): continue
        
        is_secondary = 'secondary' in caption_text.lower() or 'rare' in caption_text.lower()
        rows = table.find_all('tr')[1:]
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 3: continue
            
            item_link = cols[1].find('a')
            item_name = clean_text(item_link.get_text()) if item_link else clean_text(cols[1].get_text())
            
            if not item_name: continue
            if item_name in skill_names: continue
            if item_name in faction_names: continue
            
            # --- FIX: Filter out lines that look like percentages (e.g. "0.411%") ---
            if item_name.endswith('%') or re.match(r'^\d', item_name):
                continue
            
            if is_secondary and len(cols) >= 4:
                qty_text = clean_text(cols[3].get_text())
                chance_text = clean_text(cols[4].get_text()) if len(cols) > 4 else None
            else:
                qty_text = clean_text(cols[2].get_text())
                chance_text = clean_text(cols[3].get_text()) if len(cols) > 3 else None
            
            # Helper logic for quantity
            min_q, max_q = 0, 0
            if qty_text and qty_text != 'N/A':
                range_match = re.match(r'(\d+)-(\d+)', qty_text)
                if range_match:
                    min_q, max_q = int(range_match.group(1)), int(range_match.group(2))
                else:
                    num_match = re.match(r'(\d+)', qty_text)
                    if num_match: min_q, max_q = int(num_match.group(1)), int(num_match.group(1))
            
            # Helper logic for chance
            chance_val = None
            if chance_text:
                try: chance_val = float(chance_text.strip().replace('%', ''))
                except: pass
            
            drop_entry = DropEntry(
                item_id=normalize_id(item_name),
                min_quantity=min_q,
                max_quantity=max_q,
                chance=chance_val
            )
            
            if is_secondary:
                activity_data['secondary_drop_table'].append(drop_entry)
            else:
                activity_data['drop_table'].append(drop_entry)

# ============================================================================
# MAIN PARSING LOOP
# ============================================================================

def parse_activity_page(activity_info) -> Optional[Activity]:
    name = activity_info['name']
    url = activity_info['url']
    slug = activity_info['slug']
    
    cache_file = CACHE_DIR / (sanitize_filename(name) + '.html')
    html = download_page(url, cache_file)
    if not html: return None
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Initialize dictionary exactly like original script
    data = {
        'name': name,
        'primary_skill': None,
        'locations': [],
        'skill_requirements': {},
        'requirements': {
            'keyword_counts': {},
            'achievement_points': 0,
            'reputation': {},
            'activity_completions': {},
            'tool_equipped': None,
            'unique_tools': 0
        },
        'drop_table': [],
        'secondary_drop_table': [],
        'base_steps': 0,
        'base_xp': 0.0,
        'secondary_xp': {},
        'max_efficiency': 0.0,
        'faction_reputation': {}
    }
    
    # 1. Primary Skill from First Paragraph (Original Logic)
    content = soup.find('div', class_='mw-parser-output')
    if content:
        paragraphs = content.find_all('p')
        for p in paragraphs:
            text = p.get_text()
            if 'activity' in text.lower():
                skill_match = re.search(r'is\s+an?\s+(\w+)\s+activity', text, re.IGNORECASE)
                if skill_match:
                    data['primary_skill'] = skill_match.group(1)
                break
    
    # 2. Infobox Parsing
    infobox = soup.find('table', class_='ItemInfobox')
    if infobox:
        parse_infobox(infobox, data)
        
    # 3. Sections Parsing
    parse_locations_section(soup, data)
    parse_requirements_section(soup, data)
    parse_experience_table(soup, data)
    parse_faction_reputation(soup, data)
    parse_drop_tables(soup, data)
    
    # ========================================================================
    # CONVERT TO MODEL
    # ========================================================================
    
    # Convert Requirements Dict -> List[Requirement]
    reqs_list = []
    
    # Skill Levels
    for sname, level in data['skill_requirements'].items():
        reqs_list.append(Requirement(type=RequirementType.SKILL_LEVEL, target=sname.lower(), value=level))
    
    # Keywords
    for kw, count in data['requirements']['keyword_counts'].items():
        reqs_list.append(Requirement(type=RequirementType.KEYWORD_COUNT, target=kw, value=count))
        
    # AP
    if data['requirements']['achievement_points'] > 0:
        reqs_list.append(Requirement(type=RequirementType.ACHIEVEMENT_POINTS, value=data['requirements']['achievement_points']))
        
    # Reputation
    for fac, amt in data['requirements']['reputation'].items():
        reqs_list.append(Requirement(type=RequirementType.REPUTATION, target=normalize_id(fac), value=amt))
        
    # Activity Completions
    for act, count in data['requirements']['activity_completions'].items():
        reqs_list.append(Requirement(type=RequirementType.ACTIVITY_COMPLETION, target=normalize_id(act), value=count))
        
    # Tools
    if data['requirements']['tool_equipped']:
        reqs_list.append(Requirement(type=RequirementType.TOOL_EQUIPPED, target=data['requirements']['tool_equipped'].lower(), value=1))
    if data['requirements']['unique_tools'] > 0:
        reqs_list.append(Requirement(type=RequirementType.UNIQUE_TOOLS, value=data['requirements']['unique_tools']))

    # Convert Faction Rewards
    rewards_list = []
    for fac, amt in data['faction_reputation'].items():
        rewards_list.append(FactionReward(faction_id=normalize_id(fac), amount=amt))
        
    # Convert Secondary XP
    sec_xp_enum = {}
    for sname, xp in data['secondary_xp'].items():
        sec_xp_enum[parse_skill_enum(sname)] = float(xp)

    return Activity(
        id=normalize_id(name),
        wiki_slug=slug,
        name=name,
        value=0, # BaseItem requires value, implies coin value which is 0
        primary_skill=parse_skill_enum(data['primary_skill'] or "none"),
        locations=[normalize_id(l) for l in data['locations']],
        base_steps=data['base_steps'] or 0,
        base_xp=float(data['base_xp'] or 0),
        secondary_xp=sec_xp_enum,
        max_efficiency=data['max_efficiency'] or 0.0,
        requirements=reqs_list,
        faction_rewards=rewards_list,
        drops=data['drop_table'],
        secondary_drops=data['secondary_drop_table']
    )

def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    print("Step 1: Downloading Activities list...")
    activities_list = parse_activities_list()
    print(f"Found {len(activities_list)} activities.")
    
    all_data = []
    
    for i, item in enumerate(activities_list):
        print(f"[{i+1}/{len(activities_list)}] Parsing {item['name']}...")
        try:
            activity = parse_activity_page(item)
            if activity:
                all_data.append(activity)
        except Exception as e:
            print(f"  Error parsing {item['name']}: {e}")

    print(f"\nStep 2: Exporting {len(all_data)} activities to {OUTPUT_FILE}...")
    
    data = [a.model_dump(mode='json') for a in all_data]
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    print("Done.")

if __name__ == "__main__":
    main()