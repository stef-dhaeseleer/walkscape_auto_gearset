#!/usr/bin/env python3
"""
Scrape consumables data from Walkscape wiki and generate consumables.json
Uses Pydantic models for strict schema validation.
"""

import json
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import unquote

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from models import (
    Consumable, Modifier, StatName, 
    Condition, ConditionType
)
from scraper_utils import *

# Configuration
RESCRAPE = False
CONSUMABLES_URL = 'https://wiki.walkscape.app/wiki/Consumables'
CACHE_DIR = get_cache_dir('consumables')
CACHE_FILE = get_cache_file('consumables_cache.html')
OUTPUT_FILE = get_output_file('consumables.json')
SCAN_FOLDER_FOR_NEW_ITEMS = True

validator = ScraperValidator()

def normalize_id(text: str) -> str:
    """Normalize text to snake_case ID."""
    if not text: return "none"
    text = unquote(text)
    text = text.replace('Special:MyLanguage/', '')
    return text.lower().replace("'", "").replace("-", "_").replace(" ", "_").strip()

def extract_values_from_page(url, name):
    """
    Download individual consumable page to get its Coin Value.
    Returns tuple (normal_value, fine_value)
    """
    slug = url.split('/')[-1]
    cache_file = CACHE_DIR / (sanitize_filename(slug) + '.html')
    html = download_page(url, cache_file, rescrape=RESCRAPE)
    
    value = 0
    fine_value = 0
    
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        infobox = soup.find('table', class_='ItemInfobox')
        if infobox:
            for row in infobox.find_all('tr'):
                header = row.find('th')
                if not header: continue
                text = header.get_text()
                
                # Check for Value
                if 'Value' in text and 'Fine Value' not in text:
                    val_cell = row.find('td')
                    if val_cell:
                        v_match = re.search(r'(\d+)', val_cell.get_text())
                        if v_match: value = int(v_match.group(1))
                        
                # Check for Fine Value
                elif 'Fine Value' in text:
                    val_cell = row.find('td')
                    if val_cell:
                        v_match = re.search(r'(\d+)', val_cell.get_text())
                        if v_match: fine_value = int(v_match.group(1))
                        
    return value, fine_value

def parse_attribute_lines(lines) -> list[Modifier]:
    """
    Parse a list of attribute strings into Modifier objects.
    Logic adapted from scrape_equipment to ensure consistency.
    """
    modifiers = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or 'None' in line or 'Attributes:' in line:
            i += 1
            continue

        line_lower = line.lower()
        conditions = []
        
        # Consumables often list conditions inline or next line.
        # Check next line for context
        next_i = i + 1
        
        while next_i < len(lines):
            next_line = lines[next_i].strip()
            next_lower = next_line.lower()

            # Location Check
            loc_text, is_negated = extract_location_from_text(next_line)
            if loc_text:
                conditions.append(Condition(type=ConditionType.LOCATION, target=normalize_location_name(loc_text)))
                next_i += 1
                continue
            
            # Inline "While doing" check on next line
            if next_lower.startswith('while doing'):
                act_match = re.search(r'while doing\s+(\w+)', next_lower)
                if act_match:
                    activity = act_match.group(1).lower()
                    if activity in ACTIVITY_KEYWORDS:
                        conditions.append(Condition(type=ConditionType.SPECIFIC_ACTIVITY, target=activity))
                    else:
                        conditions.append(Condition(type=ConditionType.SKILL_ACTIVITY, target=activity))
                next_i += 1
                continue
            
            # Skill groupings
            if 'gathering skills' in next_lower:
                conditions.append(Condition(type=ConditionType.SKILL_ACTIVITY, target='gathering'))
                next_i += 1
                continue
            if 'artisan skills' in next_lower:
                conditions.append(Condition(type=ConditionType.SKILL_ACTIVITY, target='artisan'))
                next_i += 1
                continue
            
            # Generic "while doing X" on next line
            skill_context = extract_skill_from_text(next_line)
            if skill_context and skill_context != 'global' and len(next_line.split()) < 4:
                 conditions.append(Condition(type=ConditionType.SKILL_ACTIVITY, target=skill_context))
                 next_i += 1
                 continue
                 
            break

        # Check current line for conditions too
        if 'while doing' in line_lower:
            act_match = re.search(r'while doing\s+(\w+)', line_lower)
            if act_match:
                activity = act_match.group(1).lower()
                if activity in ACTIVITY_KEYWORDS:
                    conditions.append(Condition(type=ConditionType.SPECIFIC_ACTIVITY, target=activity))
                else:
                    conditions.append(Condition(type=ConditionType.SKILL_ACTIVITY, target=activity))

        if 'gathering skills' in line_lower:
            if not any(c.target == 'gathering' for c in conditions):
                conditions.append(Condition(type=ConditionType.SKILL_ACTIVITY, target='gathering'))
        elif 'artisan skills' in line_lower:
             if not any(c.target == 'artisan' for c in conditions):
                conditions.append(Condition(type=ConditionType.SKILL_ACTIVITY, target='artisan'))
        else:
             skill_context = extract_skill_from_text(line)
             if skill_context and skill_context != 'global':
                 if not any(c.type == ConditionType.SKILL_ACTIVITY and c.target == skill_context for c in conditions):
                     conditions.append(Condition(type=ConditionType.SKILL_ACTIVITY, target=skill_context))

        # Clean line for value parsing
        clean_line = re.sub(r'while doing\s+\w+', '', line_lower)
        clean_line = re.sub(r'while in\s+[\w\s]+', '', clean_line)
        clean_line = re.sub(r'gathering skills', '', clean_line)
        clean_line = re.sub(r'artisan skills', '', clean_line)
        
        value_match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*(%?)', clean_line)
        
        if value_match:
            value_str = value_match.group(1)
            is_percent = value_match.group(2) == '%'
            
            stat_text = re.sub(r'[+-]?\d+(?:\.\d+)?%?', '', clean_line).strip()
            raw_stat_name = normalize_stat_name(stat_text)
            
            if raw_stat_name:
                final_stat_key = raw_stat_name
                if raw_stat_name in DUAL_FORMAT_STATS:
                     final_stat_key = f"{raw_stat_name}_{'percent' if is_percent else 'add'}"

                try:
                    stat_enum = StatName(final_stat_key)
                    if not conditions:
                        conditions.append(Condition(type=ConditionType.GLOBAL))
                    
                    modifiers.append(Modifier(stat=stat_enum, value=float(value_str), conditions=conditions))
                except ValueError:
                    validator.add_unrecognized_stat("Parsing", f"Enum conversion failed: {final_stat_key}")
            else:
                if len(clean_line) > 3:
                     validator.add_unrecognized_stat("Parsing", line)
        
        i = next_i
        
    return modifiers

def parse_consumables_list():
    """Parse the main consumables table."""
    print("Downloading Consumables page...")
    html = download_page(CONSUMABLES_URL, CACHE_FILE, rescrape=RESCRAPE)
    if not html: return []
    
    soup = BeautifulSoup(html, 'html.parser')
    consumables = []
    
    tables = soup.find_all('table', class_='wikitable')
    print(f"Found {len(tables)} tables.")
    
    for table in tables:
        rows = table.find_all('tr')[1:] # Skip header
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 3: continue
            
            # 1. Name & Link
            link = cells[1].find('a')
            if not link: continue
            
            name = clean_text(link.get_text())
            url = 'https://wiki.walkscape.app' + link.get('href', '')
            slug = link.get('href', '').split('/')[-1]
            
            # 2. Keywords
            keywords = []
            kw_cell = cells[2]
            for kw_link in kw_cell.find_all('a'):
                if 'Keyword' in kw_link.get('title', ''):
                    keywords.append(clean_text(kw_link.get_text()))
            
            # 3. Modifiers (Attributes)
            # The cell might contain "Normal Attributes: ... Fine Attributes: ..."
            attr_cell = cells[3]
            for br in attr_cell.find_all('br'): br.replace_with('\n')
            full_attr_text = attr_cell.get_text()
            
            normal_text = full_attr_text
            fine_text = ""
            
            if "Fine Attributes:" in full_attr_text:
                parts = full_attr_text.split("Fine Attributes:")
                normal_text = parts[0].replace("Normal Attributes:", "")
                fine_text = parts[1]
            elif "Normal Attributes:" in full_attr_text:
                normal_text = full_attr_text.replace("Normal Attributes:", "")

            normal_lines = [l.strip() for l in normal_text.split('\n') if l.strip()]
            fine_lines = [l.strip() for l in fine_text.split('\n') if l.strip()]
            
            normal_mods = parse_attribute_lines(normal_lines)
            fine_mods = parse_attribute_lines(fine_lines)
            
            # 4. Duration
            duration = 0
            if len(cells) > 4:
                dur_text = cells[4].get_text()
                d_match = re.search(r'(\d+)', dur_text)
                if d_match: duration = int(d_match.group(1))
                
            # 5. Value (Get from individual page)
            val, fine_val = extract_values_from_page(url, name)
            
            # Create Normal Consumable
            consumables.append(Consumable(
                id=normalize_id(name),
                wiki_slug=slug,
                name=name,
                value=val,
                keywords=keywords,
                modifiers=normal_mods,
                duration=duration
            ))
            
            # Create Fine Consumable (if differs)
            if fine_mods:
                consumables.append(Consumable(
                    id=normalize_id(name + "_fine"),
                    wiki_slug=slug,
                    name=f"{name} (Fine)",
                    value=fine_val if fine_val else val,
                    keywords=keywords,
                    modifiers=fine_mods,
                    duration=duration
                ))
                
            print(f"  Processed: {name}")

    return consumables

def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    consumables = parse_consumables_list()
    
    # Folder scanning logic if needed (skipped for now as main table covers most)
    
    print(f"\nExporting {len(consumables)} consumables to {OUTPUT_FILE}...")
    data = [c.model_dump(mode='json') for c in consumables]
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    validator.report()
    print("Done.")

if __name__ == "__main__":
    main()