#!/usr/bin/env python3
"""
Scrape containers (chests) from Walkscape wiki and generate containers.json.
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

from models import Container, DropEntry, ChestTableCategory
from scraper_utils import *

# Configuration
RESCRAPE = False
CONTAINERS_URL = 'https://wiki.walkscape.app/wiki/Chests'
CACHE_DIR = get_cache_dir('containers')
CACHE_FILE = get_cache_file('containers_cache.html')
OUTPUT_FILE = get_output_file('containers.json')
SCAN_FOLDER_FOR_NEW_ITEMS = True

validator = ScraperValidator()

def normalize_id(text: str) -> str:
    """Normalize text to snake_case ID."""
    if not text: return "none"
    text = unquote(text)
    text = text.replace('Special:MyLanguage/', '')
    return text.lower().replace("'", "").replace("-", "_").replace(" ", "_").strip()

def map_category(header_text: str) -> ChestTableCategory:
    """Map wiki header text to ChestTableCategory enum."""
    lower = header_text.lower()
    if 'main' in lower: return ChestTableCategory.MAIN
    if 'valuables' in lower: return ChestTableCategory.VALUABLES
    if 'uncommon' in lower: return ChestTableCategory.UNCOMMON
    if 'common' in lower: return ChestTableCategory.COMMON
    if 'rare' in lower: return ChestTableCategory.RARE
    if 'legendary' in lower: return ChestTableCategory.LEGENDARY
    if 'epic' in lower: return ChestTableCategory.EPIC
    if 'ethereal' in lower: return ChestTableCategory.ETHEREAL
    return ChestTableCategory.OTHER

def parse_loot_tables(html, container_name) -> list[DropEntry]:
    """Parse all loot tables from a container page."""
    soup = BeautifulSoup(html, 'html.parser')
    all_drops = []
    
    # Find headers containing "Loot Table"
    headers = soup.find_all(['h2', 'h3'])
    
    for header in headers:
        text = header.get_text()
        if 'Loot Table' not in text: continue
        
        category = map_category(text)
        
        # Find the table following this header
        table = header.find_next('table', class_='wikitable')
        if not table: continue
        
        # Verify it's not the "Sources" table or something else
        # Loot tables usually have headers like Item, Quantity, Chance
        headers_row = table.find('tr')
        if not headers_row or 'Chance' not in headers_row.get_text():
            continue
            
        rows = table.find_all('tr')[1:]
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 4: continue
            
            # Format usually: [Icon] [Name] [Quantity] [Chance Per Roll] [Chance Per Chest]
            name_cell = cells[1]
            qty_cell = cells[2]
            chance_cell = cells[3]
            
            item_name = clean_text(name_cell.get_text())
            qty_text = clean_text(qty_cell.get_text())
            chance_text = clean_text(chance_cell.get_text())
            
            # Parse Quantity (can be "1", "1-5", "N/A")
            min_q, max_q = 0, 0
            if qty_text and qty_text != 'N/A':
                range_match = re.match(r'(\d+)-(\d+)', qty_text)
                if range_match:
                    min_q = int(range_match.group(1))
                    max_q = int(range_match.group(2))
                else:
                    num_match = re.search(r'(\d+)', qty_text)
                    if num_match:
                        min_q = int(num_match.group(1))
                        max_q = min_q
            
            # Parse Chance
            chance_val = None
            if chance_text:
                c_match = re.search(r'([0-9.]+)', chance_text)
                if c_match:
                    chance_val = float(c_match.group(1))
            
            all_drops.append(DropEntry(
                item_id=normalize_id(item_name),
                min_quantity=min_q,
                max_quantity=max_q,
                chance=chance_val,
                category=category
            ))
            
    return all_drops

def parse_containers_list():
    """Parse the main containers page."""
    print("Downloading Containers page...")
    html = download_page(CONTAINERS_URL, CACHE_FILE, rescrape=RESCRAPE)
    if not html: return []
    
    soup = BeautifulSoup(html, 'html.parser')
    containers = []
    
    tables = soup.find_all('table', class_='wikitable')
    print(f"Found {len(tables)} tables.")
    
    for table in tables:
        caption = table.find('caption')
        caption_text = clean_text(caption.get_text()) if caption else ""
        
        c_type = "unknown"
        if 'Skill Chests' in caption_text: c_type = "skill_chest"
        elif 'Unique Openables' in caption_text: c_type = "unique_openable"
        else: continue # Skip other tables like regional chests if not desired, or add logic
        
        rows = table.find_all('tr')[1:]
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 2: continue
            
            # Name usually in 2nd column
            link = cells[1].find('a')
            if not link: continue
            
            name = clean_text(link.get_text())
            url = 'https://wiki.walkscape.app' + link.get('href', '')
            slug = link.get('href', '').split('/')[-1]
            
            # Download individual page for loot tables
            cache_file = CACHE_DIR / (sanitize_filename(slug) + '.html')
            page_html = download_page(url, cache_file, rescrape=RESCRAPE)
            
            drops = []
            if page_html:
                drops = parse_loot_tables(page_html, name)
            
            containers.append(Container(
                id=normalize_id(name),
                wiki_slug=slug,
                name=name,
                type=c_type,
                drops=drops
            ))
            print(f"  Processed: {name} ({len(drops)} drops)")

    return containers

def load_item_values() -> dict[str, int]:
    """Loads the values from already scraped JSON files to calculate EV."""
    values = {"coins": 1} # Hardcoded currency
    
    files_to_load = ["materials.json", "consumables.json", "equipment.json"]
    for filename in files_to_load:
        path = Path(get_output_file(filename))
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for item in data:
                        i_id = item.get("id")
                        if i_id:
                            val = item.get("value", 0)
                            values[i_id] = val
                            
                            # --- FIX: Create Equipment ID Aliases ---
                            # Chests drop the base name (e.g., "fingerpick").
                            # We map "fingerpick_common" -> "fingerpick"
                            if i_id.endswith("_common"):
                                values[i_id.replace("_common", "")] = val
                            # Map "FINGERPICK" (no quality) -> "fingerpick"
                            elif i_id.isupper():
                                values[i_id.lower()] = val
                                
            except Exception as e:
                print(f"Warning: Could not load {filename} for EV calculation: {e}")
                
    return values

def calculate_evs(containers_list: list[Container], item_values: dict[str, int]) -> list[Container]:
    """Calculates total_ev and material_ev for all containers, supporting recursion and fine variants."""
    
    # Map containers for recursive lookups
    container_map = {c.id: c for c in containers_list}
    
    def get_item_ev(item_id: str, depth=0) -> float:
        if depth > 5: return 0.0 # Prevent infinite loops
        if item_id == "coins": return 1.0
        
        # Recursive container check
        if item_id in container_map:
            c = container_map[item_id]
            ev = 0.0
            for drop in c.drops:
                chance = (drop.chance or 0.0) / 100.0
                avg_qty = (drop.min_quantity + drop.max_quantity) / 2.0
                ev += chance * avg_qty * get_item_ev(drop.item_id, depth + 1)
            return ev
            
        # Base item logic
        base_value = float(item_values.get(item_id, 0))
        
        # --- FIX: Factor in the innate 1% chance for Fine Materials ---
        fine_id = f"{item_id}_fine"
        if fine_id in item_values:
            fine_value = float(item_values.get(fine_id, 0))
            return (0.99 * base_value) + (0.01 * fine_value)
            
        return base_value

    updated_containers = []
    
    for c in containers_list:
        total_ev = 0.0
        material_ev = 0.0
        
        for drop in c.drops:
            chance = (drop.chance or 0.0) / 100.0
            avg_qty = (drop.min_quantity + drop.max_quantity) / 2.0
            drop_ev = chance * avg_qty * get_item_ev(drop.item_id)
            
            total_ev += drop_ev
            
            # Check if it's in the Main or Valuables category
            cat_str = drop.category.value if hasattr(drop.category, 'value') else drop.category
            if cat_str in ["Main", "Valuables"]:
                material_ev += drop_ev
                
        # Re-create the container with the new EV values
        updated_containers.append(Container(
            id=c.id,
            wiki_slug=c.wiki_slug,
            name=c.name,
            type=c.type,
            drops=c.drops,
            total_expected_value=total_ev * 4,
            materials_expected_value=material_ev * 4
        ))
        
    return updated_containers

def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    containers = parse_containers_list()
    
    print("Calculating Expected Values (EV) for containers...")
    item_values = load_item_values()
    containers = calculate_evs(containers, item_values)
    
    print(f"\nExporting {len(containers)} containers to {OUTPUT_FILE}...")
    data = [c.model_dump(mode='json') for c in containers]
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    validator.report()
    print("Done.")

if __name__ == "__main__":
    main()