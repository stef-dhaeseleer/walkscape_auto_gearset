#!/usr/bin/env python3
"""
Scrape recipes from the Walkscape wiki Recipes page.
Generates recipes.json with all recipe data using Pydantic models.
"""

import json
import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import unquote

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from models import Recipe, RecipeMaterial, SkillName
from scraper_utils import *

# Configuration
RESCRAPE = False
RECIPES_URL = 'https://wiki.walkscape.app/wiki/Recipes'
CACHE_DIR = get_cache_dir('recipes')
OUTPUT_FILE = get_output_file('recipes.json')
CACHE_FILE = get_cache_file('recipes_cache.html')

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

# ============================================================================
# PARSING LOGIC
# ============================================================================

def extract_materials(td) -> list[list[RecipeMaterial]]:
    """
    Extract materials list from the materials cell.
    Returns: List of material groups (outer=AND, inner=OR).
    """
    for br in td.find_all('br'):
        br.replace_with(' ')
    
    text = clean_text(td.get_text())
    material_groups = []

    # Helper to parse "5x Item Name" string
    def parse_group_string(group_str):
        group_items = []
        matches = re.findall(r'(\d+)x\s+([A-Za-z\s\(\)\']+?)(?=\s*\d+x|$)', group_str)
        for qty_str, material_name in matches:
            group_items.append(RecipeMaterial(
                item_id=normalize_id(material_name.strip()),
                amount=int(qty_str)
            ))
        return group_items

    # Check for " or " alternatives
    if ' or ' in text.lower():
        options = []
        alternatives = re.split(r'\s+or\s+', text, flags=re.IGNORECASE)
        for alt in alternatives:
            matches = re.findall(r'(\d+)x\s+([A-Za-z\s\(\)\']+?)(?=\s*\d+x|$)', alt)
            for qty, name in matches:
                options.append(RecipeMaterial(item_id=normalize_id(name), amount=int(qty)))
        if options:
            material_groups.append(options)
    else:
        matches = re.findall(r'(\d+)x\s+([A-Za-z\s\(\)\']+?)(?=\s*\d+x|$)', text)
        for qty, name in matches:
            material_groups.append([RecipeMaterial(item_id=normalize_id(name), amount=int(qty))])

    return material_groups

def extract_output_quantity(td):
    text = clean_text(td.get_text())
    match = re.match(r'(\d+)x\s+(.+)', text)
    if match:
        return int(match.group(1)), match.group(2).strip()
    
    text = re.sub(r'^(Create|Craft|Brew|Make|Cook|Prepare)\s+an?\s+', '', text, flags=re.IGNORECASE)
    return 1, text

def extract_service_and_level(service_td, level_td):
    service_text = clean_text(service_td.get_text())
    level_text = clean_text(level_td.get_text())
    
    skill = None
    level = 0
    
    level_match = re.search(r'(\w+)\s+lvl\.?\s+(\d+)', level_text, re.IGNORECASE)
    if level_match:
        skill = level_match.group(1)
        level = int(level_match.group(2))
    
    if not level_match:
        level_match = re.search(r'(\w+)\s+lvl\.?\s+(\d+)', service_text, re.IGNORECASE)
        if level_match:
            skill = level_match.group(1)
            level = int(level_match.group(2))
    
    service_match = re.search(r'Needs\s+(.+?)\s+service', service_text, re.IGNORECASE)
    service_name = service_match.group(1).strip() if service_match else service_text
    
    return normalize_id(service_name), skill, level

def normalize_recipe_name_match(name1, name2):
    """
    Check if two recipe names match, ignoring common prefixes.
    e.g. "Brew beer" == "Beer"
    """
    n1 = name1.lower()
    n2 = name2.lower()
    
    if n1 == n2: return True
    if n1 in n2 or n2 in n1: return True
    
    prefixes = ['create ', 'craft ', 'brew ', 'make ', 'cook ', 'prepare ', 'mix ', 'fry ', 'bake ', 'cut ', 'saw ']
    
    def strip_prefix(s):
        for p in prefixes:
            if s.startswith(p):
                return s[len(p):].strip()
        return s
        
    return strip_prefix(n1) == strip_prefix(n2)

def parse_recipe_experience_from_item_page(item_name, recipe_name, cache_folders):
    """Find and parse item page for recipe stats."""
    
    cache_path = None
    filenames_to_try = [
        sanitize_filename(item_name) + '.html',
        sanitize_filename(item_name).replace(' ', '_') + '.html'
    ]
    
    for folder in cache_folders:
        for fname in filenames_to_try:
            p = folder / fname
            if p.exists():
                cache_path = p
                break
        if cache_path: break
            
    if not cache_path:
        return None
    
    try:
        html = cache_path.read_text(encoding='utf-8')
    except:
        return None
        
    soup = BeautifulSoup(html, 'html.parser')
    
    # Locate Recipe Experience Table
    # Method 1: Look for "Recipe Experience" caption directly
    target_table = None
    tables = soup.find_all('table', class_='wikitable')
    for table in tables:
        caption = table.find('caption')
        if caption and 'Recipe Experience' in caption.get_text():
            target_table = table
            break
            
    if not target_table:
        # Method 2: Look for heading
        recipe_heading = soup.find('h2', id='Primary_Recipe_Output')
        if recipe_heading:
            current = recipe_heading.parent
            while current:
                current = current.find_next_sibling()
                if not current: break
                if current.name == 'table':
                    target_table = current
                    break
                if current.name == 'h2': break

    if target_table:
        rows = target_table.find_all('tr')[1:]
        for data_row in rows:
            cells = data_row.find_all('td')
            if len(cells) >= 7:
                row_recipe_name = clean_text(cells[1].get_text())
                
                # Loose matching:
                # 1. Exact match
                # 2. Normalized match (strip "Brew ", "Craft ", etc)
                # 3. Match against Item Name (e.g. "Beer" recipe for "Beer" item)
                if (row_recipe_name == recipe_name or 
                    normalize_recipe_name_match(row_recipe_name, recipe_name) or
                    normalize_recipe_name_match(row_recipe_name, item_name)):
                    
                    try:
                        base_xp = float(clean_text(cells[2].get_text()))
                        base_steps = int(clean_text(cells[3].get_text()))
                        max_eff_text = clean_text(cells[6].get_text()).replace('%', '')
                        max_efficiency = round(float(max_eff_text) / 100.0, 2)
                        return {
                            'base_xp': base_xp,
                            'base_steps': base_steps,
                            'max_efficiency': max_efficiency
                        }
                    except:
                        continue
                        
    return None

def extract_max_efficiency_fallback(td):
    text = clean_text(td.get_text())
    match = re.search(r'\(\+(\d+\.?\d*)%\)', text)
    if match:
        return float(match.group(1)) / 100.0
    return 0.0

# ============================================================================
# MAIN
# ============================================================================

def main():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    equip_cache = get_cache_dir('equipment')
    mat_cache = get_cache_dir('materials')
    cons_cache = get_cache_dir('consumables')
    cross_ref_folders = [equip_cache, mat_cache, cons_cache]
    
    print("Step 1: Downloading Recipes page...")
    html = download_page(RECIPES_URL, CACHE_FILE, rescrape=RESCRAPE)
    if not html: return

    soup = BeautifulSoup(html, 'html.parser')
    all_recipes = []
    
    current_skill_context = None
    
    tables = soup.find_all('table', class_='wikitable')
    print(f"Found {len(tables)} tables.")

    for table in tables:
        heading = table.find_previous('h2')
        if heading:
            skill_text = clean_text(heading.get_text())
            skill_text = re.sub(r'^\d+\s*', '', skill_text)
            if skill_text and skill_text != 'Contents':
                current_skill_context = skill_text

        rows = table.find_all('tr')[1:]
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 6: continue
            
            recipe_name = clean_text(cells[1].get_text())
            
            output_links = cells[5].find_all('a')
            output_link = next((l for l in output_links if '/wiki/File:' not in l.get('href', '')), None)
            
            if not output_link: continue
            
            output_item_url = unquote(output_link.get('href', '')).replace('/Special:MyLanguage/', '/')
            output_item_name = output_item_url.split('/')[-1].replace('_', ' ')
            
            output_qty, _ = extract_output_quantity(cells[5])
            service_id, skill_str, level = extract_service_and_level(cells[3], cells[2])
            if not skill_str: skill_str = current_skill_context
            
            materials = extract_materials(cells[4])
            
            base_xp, base_steps, max_eff = 0.0, 0, 0.0
            
            # Pass output_item_name explicitly for fuzzy matching against recipe name
            stats = parse_recipe_experience_from_item_page(output_item_name, recipe_name, cross_ref_folders)
            if stats:
                base_xp = stats['base_xp']
                base_steps = stats['base_steps']
                max_eff = stats['max_efficiency']
            else:
                if len(cells) >= 10:
                    try:
                        base_xp = float(clean_text(cells[5].get_text()))
                        base_steps = int(clean_text(cells[6].get_text()))
                        max_eff = extract_max_efficiency_fallback(cells[8])
                    except: pass

            recipe_id = normalize_id(recipe_name)
            
            try:
                recipe = Recipe(
                    id=recipe_id,
                    wiki_slug=output_item_url.split('/')[-1],
                    name=recipe_name,
                    value=0,
                    skill=parse_skill_enum(skill_str or "none"),
                    level=level,
                    service=service_id,
                    output_item_id=normalize_id(output_item_name),
                    output_quantity=output_qty,
                    materials=materials,
                    base_xp=base_xp,
                    base_steps=base_steps,
                    max_efficiency=max_eff
                )
                all_recipes.append(recipe)
                print(f"  Processed: {recipe_name} -> XP: {base_xp}, Steps: {base_steps}")
            except Exception as e:
                print(f"  Error creating recipe {recipe_name}: {e}")

    print(f"\nStep 3: Exporting {len(all_recipes)} recipes to {OUTPUT_FILE}...")
    
    data = [r.model_dump(mode='json') for r in all_recipes]
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        
    print("Done.")

if __name__ == "__main__":
    main()